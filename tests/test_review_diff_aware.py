"""Tests for diff-aware Review: measured workspace evidence feeds into review."""
from __future__ import annotations

import subprocess
from pathlib import Path

from src.engine import Phase, PolicyPack
from src.phases.review import ReviewHandler
from src.runtime import DispatchRequest, DispatchResponse, ReviewRunner
from src.runtime.workspace_evidence import collect_review_context


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], capture_output=True, check=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "seed"], capture_output=True, check=True)


# ── collect_review_context ──────────────────────────────────────────────────

def test_collect_review_context_reports_modified_tracked_file(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "seed.txt").write_text("seed\nmodified\n", encoding="utf-8")

    context = collect_review_context(str(tmp_path))

    assert context["measured"] is True
    assert "seed.txt" in context["diff_stat"]
    assert "modified" in context["diff"]
    assert context["diff_truncated"] is False


def test_collect_review_context_lists_untracked_files(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("print('hello')\n", encoding="utf-8")

    context = collect_review_context(str(tmp_path))

    assert context["measured"] is True
    assert "new_file.py" in context["untracked_files"]


def test_collect_review_context_truncates_large_diff(tmp_path):
    _init_git_repo(tmp_path)
    big_content = "\n".join(f"line {i}" for i in range(2000))
    (tmp_path / "seed.txt").write_text(big_content, encoding="utf-8")

    context = collect_review_context(str(tmp_path), max_diff_bytes=200)

    assert context["measured"] is True
    assert context["diff_truncated"] is True
    assert context["diff"].endswith("\n... [diff truncated at 200 bytes]")
    # Truncated body (excluding marker) must fit within the byte budget.
    marker = "\n... [diff truncated at 200 bytes]"
    body = context["diff"][: -len(marker)]
    assert len(body.encode("utf-8")) <= 200


def test_collect_review_context_non_git_dir_returns_unmeasured(tmp_path):
    context = collect_review_context(str(tmp_path))

    assert context["measured"] is False
    assert "reason" in context


# ── _collect_build_workspace_evidence ──────────────────────────────────────

def _task_with_build_result(artifacts: dict) -> object:
    return type(
        "Task",
        (),
        {
            "task_id": "task-1",
            "description": "Implement the slice.",
            "phase_results": [
                type("Result", (), {"phase": Phase.BUILD, "evidence": {}, "artifacts": artifacts})()
            ],
        },
    )()


def test_collect_build_workspace_evidence_from_graph_event():
    artifacts = {
        "task_graph_execution": {
            "events": [
                {
                    "node_id": "step-1",
                    "title": "Build step",
                    "action": "execute",
                    "provider_result": {
                        "success": True,
                        "evidence": {
                            "workspace_delta": {
                                "measured": True,
                                "files_changed": ["src/a.py"],
                                "change_count": 1,
                            },
                            "claim_reconciliation": {
                                "claimed_files": ["src/a.py"],
                                "measured_files": ["src/a.py"],
                                "claimed_but_unchanged": [],
                                "changed_but_unclaimed": [],
                                "divergence": False,
                            },
                        },
                    },
                }
            ]
        }
    }
    task = _task_with_build_result(artifacts)
    handler = ReviewHandler(policy_pack=PolicyPack())

    evidence = handler._collect_build_workspace_evidence(task)

    assert evidence["workspace_delta"]["change_count"] == 1
    assert evidence["claim_reconciliation"]["divergence"] is False


def test_collect_build_workspace_evidence_returns_empty_when_missing():
    task = _task_with_build_result({"task_graph_execution": {"events": []}})
    handler = ReviewHandler(policy_pack=PolicyPack())

    evidence = handler._collect_build_workspace_evidence(task)

    assert evidence == {}


def test_collect_build_workspace_evidence_returns_empty_when_no_build_phase():
    task = type("Task", (), {"task_id": "t", "description": "d", "phase_results": []})()
    handler = ReviewHandler(policy_pack=PolicyPack())

    evidence = handler._collect_build_workspace_evidence(task)

    assert evidence == {}


# ── ReviewRunner divergence findings ───────────────────────────────────────

def test_review_runner_flags_claim_divergence_as_blocking():
    verdict = ReviewRunner().review(
        evidence={
            "spec_text": "Implement the slice.",
            "measured_changes": {
                "claim_reconciliation": {
                    "claimed_files": ["src/a.py", "src/b.py"],
                    "measured_files": ["src/a.py"],
                    "claimed_but_unchanged": ["src/b.py"],
                    "changed_but_unclaimed": [],
                    "divergence": True,
                },
            },
        }
    )
    artifact = verdict.to_artifact()

    divergence_findings = [f for f in artifact["findings"] if f["check"] == "workspace_claim_divergence"]
    assert len(divergence_findings) == 1
    finding = divergence_findings[0]
    assert finding["passed"] is False
    assert finding["severity"] == "critical"
    assert "src/b.py" in finding["message"]

    # A high-severity (critical) finding must prevent a clean pass.
    assert artifact["outcome"] != "pass"


def test_review_runner_flags_workspace_unchanged_on_success_as_blocking():
    verdict = ReviewRunner().review(
        evidence={
            "spec_text": "Implement the slice.",
            "measured_changes": {
                "workspace_unchanged_on_success": True,
            },
        }
    )
    artifact = verdict.to_artifact()

    blocking = [f for f in artifact["findings"] if f["check"] == "workspace_unchanged_on_success"]
    assert len(blocking) == 1
    assert blocking[0]["passed"] is False
    assert blocking[0]["severity"] == "critical"
    assert artifact["outcome"] != "pass"


def test_review_runner_no_evidence_unchanged_behavior():
    control = ReviewRunner().review(
        evidence={"spec_text": "Implement the slice."}
    )
    with_empty_measured_changes = ReviewRunner().review(
        evidence={"spec_text": "Implement the slice.", "measured_changes": {}}
    )

    control_artifact = control.to_artifact()
    other_artifact = with_empty_measured_changes.to_artifact()

    assert control_artifact["findings"] == other_artifact["findings"]
    assert control_artifact["outcome"] == other_artifact["outcome"]
    assert not any(f["check"].startswith("workspace_") for f in control_artifact["findings"])


def test_review_runner_no_divergence_no_blocking_finding():
    verdict = ReviewRunner().review(
        evidence={
            "spec_text": "Implement the slice.",
            "measured_changes": {
                "workspace_delta": {"measured": True, "files_changed": ["src/a.py"], "change_count": 1},
                "claim_reconciliation": {
                    "claimed_files": ["src/a.py"],
                    "measured_files": ["src/a.py"],
                    "claimed_but_unchanged": [],
                    "changed_but_unclaimed": [],
                    "divergence": False,
                },
            },
        }
    )
    artifact = verdict.to_artifact()

    assert not any(f["check"] == "workspace_claim_divergence" for f in artifact["findings"])
    assert not any(f["check"] == "workspace_unchanged_on_success" for f in artifact["findings"])


# ── ReviewHandler integration ──────────────────────────────────────────────

class _CapturingDispatcher:
    """Stub dispatcher that records the last DispatchRequest it received."""

    def __init__(self):
        self.last_request: DispatchRequest | None = None

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.last_request = request
        return DispatchResponse(success=True, outputs={}, artifacts={"provider": "captured"})


def test_review_handler_dispatch_includes_measured_changes_and_workspace_diff(monkeypatch, tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "seed.txt").write_text("seed\nmodified\n", encoding="utf-8")
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))

    artifacts = {
        "task_graph_execution": {
            "events": [
                {
                    "node_id": "step-1",
                    "title": "Build step",
                    "action": "execute",
                    "provider_result": {
                        "success": True,
                        "evidence": {
                            "workspace_delta": {
                                "measured": True,
                                "files_changed": ["seed.txt"],
                                "change_count": 1,
                            },
                            "claim_reconciliation": {
                                "claimed_files": ["seed.txt"],
                                "measured_files": ["seed.txt"],
                                "claimed_but_unchanged": [],
                                "changed_but_unclaimed": [],
                                "divergence": False,
                            },
                        },
                    },
                }
            ]
        }
    }
    task = _task_with_build_result(artifacts)
    dispatcher = _CapturingDispatcher()
    handler = ReviewHandler(policy_pack=PolicyPack(), dispatcher=dispatcher)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert dispatcher.last_request is not None
    inputs = dispatcher.last_request.inputs
    assert inputs["measured_changes"]["workspace_delta"]["change_count"] == 1
    assert inputs["measured_changes"]["claim_reconciliation"]["divergence"] is False
    assert inputs["workspace_diff"]["measured"] is True
    assert "seed.txt" in inputs["workspace_diff"]["diff"]

    review_inputs_summary = result.artifacts["review_inputs_summary"]
    assert review_inputs_summary["measured_changes_present"] is True
    assert review_inputs_summary["diff_bytes"] > 0
    assert review_inputs_summary["diff_truncated"] is False


def test_review_handler_surfaces_rejected_diff_review_decisions(monkeypatch, tmp_path):
    """A file rejected via the TUI's DiffReviewScreen (recorded onto a Build
    phase result by `record_review_decision`) must reach the Review phase's
    dispatch inputs and prompt on the next run, so the reviewer treats it as
    a finding that must be addressed — see `src/review_data.find_diff_review`
    and its use in `ReviewHandler._review_inputs`/`execute`."""
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))  # not a git repo -> no live diff noise

    artifacts = {
        "diff_review": {
            "decisions": [
                {
                    "path": "src/risky.py",
                    "hunk_index": None,
                    "decision": "rejected",
                    "note": "unsafe eval",
                    "decided_at": "2026-07-07T00:00:00",
                },
                {
                    "path": "src/fine.py",
                    "hunk_index": None,
                    "decision": "approved",
                    "note": None,
                    "decided_at": "2026-07-07T00:00:00",
                },
            ]
        }
    }
    task = _task_with_build_result(artifacts)
    dispatcher = _CapturingDispatcher()
    handler = ReviewHandler(policy_pack=PolicyPack(), dispatcher=dispatcher)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert dispatcher.last_request is not None
    diff_review = dispatcher.last_request.inputs["diff_review"]
    rejected = [d for d in diff_review["decisions"] if d["decision"] == "rejected"]
    assert rejected and rejected[0]["path"] == "src/risky.py"
    assert "src/risky.py" in dispatcher.last_request.prompt

    assert result.evidence["diff_review_rejected_files"] == ["src/risky.py"]
    assert result.artifacts["review_inputs_summary"]["diff_review_rejected_files"] == 1
    assert result.artifacts["review_inputs"]["diff_review"] == artifacts["diff_review"]


def test_review_handler_no_diff_review_decisions_omits_them(monkeypatch, tmp_path):
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))

    task = _task_with_build_result({"task_graph_execution": {"events": []}})
    dispatcher = _CapturingDispatcher()
    handler = ReviewHandler(policy_pack=PolicyPack(), dispatcher=dispatcher)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert dispatcher.last_request.inputs["diff_review"] == {}
    assert result.evidence["diff_review_rejected_files"] == []
    assert result.artifacts["review_inputs_summary"]["diff_review_rejected_files"] == 0
    assert "diff_review" not in result.artifacts["review_inputs"]


def test_review_handler_no_measured_evidence_records_absence(monkeypatch, tmp_path):
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))  # not a git repo

    task = type(
        "Task",
        (),
        {"task_id": "task-2", "description": "No build evidence", "phase_results": []},
    )()
    handler = ReviewHandler(policy_pack=PolicyPack())

    result = handler.execute(task=task, phase=Phase.REVIEW)

    review_inputs_summary = result.artifacts["review_inputs_summary"]
    assert review_inputs_summary["measured_changes_present"] is False
    assert review_inputs_summary["diff_bytes"] == 0
    assert review_inputs_summary["diff_truncated"] is False
    assert "measured_changes" not in result.artifacts["review_inputs"]
    assert not any(
        f["check"] in {"workspace_claim_divergence", "workspace_unchanged_on_success"}
        for f in result.artifacts["review_verdict"]["findings"]
    )


# ── zero-diff fast path: skip the model dispatch, not the verdict ──────────

def test_review_handler_skips_dispatch_when_no_changes_to_review(monkeypatch, tmp_path):
    """A provably empty workspace diff shouldn't burn a model call -- the
    same local ReviewRunner fallback already used on dispatch failure can
    render the (correctly failing) verdict deterministically."""
    _init_git_repo(tmp_path)  # clean checkout, no modifications made after init
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))

    task = _task_with_build_result({})
    dispatcher = _CapturingDispatcher()
    handler = ReviewHandler(policy_pack=PolicyPack(), dispatcher=dispatcher)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert dispatcher.last_request is None
    assert result.evidence["review_dispatch_skipped_reason"] == "no_changes_to_review"
    assert result.evidence["provider_review"] is False
    findings = result.artifacts["review_verdict"]["findings"]
    assert any(f["check"] == "diff_evidence" and not f["passed"] for f in findings)


def test_review_handler_dispatches_when_untracked_files_present(monkeypatch, tmp_path):
    """An untracked new file is a real (if unstaged) change -- must not be
    treated as 'nothing to review' even though `git diff` alone is empty."""
    _init_git_repo(tmp_path)
    (tmp_path / "new_file.py").write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))

    task = _task_with_build_result({})
    dispatcher = _CapturingDispatcher()
    handler = ReviewHandler(policy_pack=PolicyPack(), dispatcher=dispatcher)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert dispatcher.last_request is not None
    assert result.evidence["review_dispatch_skipped_reason"] is None


def test_review_handler_dispatches_when_diff_measurement_unavailable(monkeypatch, tmp_path):
    """Not a git repo -> workspace_diff['measured'] is False -> never skip;
    ambiguity always falls through to the real dispatch."""
    monkeypatch.setenv("SARATHI_WORKDIR", str(tmp_path))  # tmp_path is not a git repo

    task = _task_with_build_result({})
    dispatcher = _CapturingDispatcher()
    handler = ReviewHandler(policy_pack=PolicyPack(), dispatcher=dispatcher)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert dispatcher.last_request is not None
    assert result.evidence["review_dispatch_skipped_reason"] is None


def test_no_changes_to_review_helper_directly():
    from src.phases.review import ReviewHandler

    assert ReviewHandler._no_changes_to_review(
        workspace_diff={"measured": True, "diff": "", "untracked_files": []},
        diff_summary={"changed_files": 0},
    ) is True
    assert ReviewHandler._no_changes_to_review(
        workspace_diff={"measured": True, "diff": "diff --git a/x b/x\n", "untracked_files": []},
        diff_summary={"changed_files": 1},
    ) is False
    assert ReviewHandler._no_changes_to_review(
        workspace_diff={"measured": False, "reason": "not_a_git_repo"},
        diff_summary=None,
    ) is False
    assert ReviewHandler._no_changes_to_review(
        workspace_diff={"measured": True, "diff": "", "untracked_files": ["new.py"]},
        diff_summary=None,
    ) is False
