"""Tests for policy proposals as NCP improvement records and the post-accept check."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ncp_adapter.improvement import NCPImprovementTracker, OutcomeLog

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_TEMPLATE = REPO_ROOT / "docs" / "ncp" / "run.py.example"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evolve import EvolutionPolicy, PolicyProposal, ProposalReviewStore  # noqa: E402


def _proposal(**overrides) -> PolicyProposal:
    fields = dict(
        title="Repeated failures in Verify",
        policy_file="review.md",
        rationale="Verify failed 3 times on lint",
        suggested_change="Add a lint step before tests",
        evidence_refs=["t1:verify"],
        confidence=0.7,
        source="learning",
    )
    fields.update(overrides)
    return PolicyProposal(**fields)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A git workspace with a real NCP store, the v3 bridge and a policy pack."""
    pytest.importorskip("ncp")
    if shutil.which("git") is None:
        pytest.skip("git required for NCP project-root discovery")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ncp_dir = tmp_path / ".ncp"
    ncp_dir.mkdir()
    (ncp_dir / "config.toml").write_text(
        '[store]\ntype = "sqlite"\npath = ".ncp/store.db"\n\n[embedding]\nenabled = false\n'
    )
    shutil.copyfile(BRIDGE_TEMPLATE, ncp_dir / "run.py")
    (ncp_dir / "run.py").chmod(0o755)
    (tmp_path / "policy-pack").mkdir()
    (tmp_path / "policy-pack" / "review.md").write_text("# Review\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _ncp_attempts(root: Path) -> list[dict]:
    probe = (
        "import json; from pathlib import Path; from ncp import configure; "
        "from ncp.stores import create_store; "
        "s = create_store(configure(cwd=Path('.'))); "
        "print(json.dumps([a.model_dump() for a in s.list_improvement_attempts()]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=root
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def _log(tracker: NCPImprovementTracker, results: list[bool], task_class="codegen/patch"):
    for i, ok in enumerate(results):
        tracker.record_task_outcome(
            task_id=f"t{i}", task_class=task_class, success=ok, weight=1.0, output_tokens=100
        )


# ── real NCP round trip ────────────────────────────────────────────────────


def test_proposal_lifecycle_and_post_accept_regression_reach_ncp(workspace):
    tracker = NCPImprovementTracker.for_workspace(workspace)
    assert tracker is not None
    proposal = _proposal()

    first = tracker.record_proposals([proposal.to_artifact()], task_class="codegen/patch")
    again = tracker.record_proposals([proposal.to_artifact()], task_class="codegen/patch")
    note = first[proposal.proposal_id]
    assert note["attempt_id"].startswith("att_") and note["reused"] is False
    assert again[proposal.proposal_id]["reused"] is True  # recurring proposal: one attempt
    assert again[proposal.proposal_id]["attempt_id"] == note["attempt_id"]

    _log(tracker, [True] * 5)  # pre-accept anchor: 5/5
    ProposalReviewStore(workspace / "policy-pack", mirror=False).accept(proposal)
    [attempt] = _ncp_attempts(workspace)
    assert attempt["status"] == "applied" and attempt["accepted"] is True

    assert tracker.check_accepted("codegen/patch")[0]["verdict"] == "pending"
    _log(tracker, [True, False, True, False, True])  # 3/5 after accepting
    [verdict] = tracker.check_accepted("codegen/patch")
    assert verdict["verdict"] == "regressed"
    assert verdict["before_rate"] == 1.0 and verdict["after_rate"] == 0.6
    assert verdict["recommendation"] == f"sarathi proposals --rollback {proposal.proposal_id}"

    [attempt] = _ncp_attempts(workspace)
    assert (attempt["passed"], attempt["total"], attempt["anchor_rate"]) == (3.0, 5.0, 1.0)
    assert attempt["mean_output_tokens"] == 100.0
    assert "regressed, consider rollback" in attempt["note"]


def test_rollback_and_history_shown_on_the_next_proposal(workspace):
    tracker = NCPImprovementTracker.for_workspace(workspace)
    store = ProposalReviewStore(workspace / "policy-pack", mirror=False)
    proposal = _proposal()
    tracker.record_proposals([proposal.to_artifact()], task_class="codegen/patch")
    store.accept(proposal)
    store.rollback(proposal.proposal_id)
    [attempt] = _ncp_attempts(workspace)
    assert attempt["status"] == "rolled_back"

    # The same change proposed again (new evidence) is a new attempt, and the
    # reviewer sees that it was rolled back before.
    retry = _proposal(rationale="Verify failed 4 more times on lint")
    note = tracker.record_proposals([retry.to_artifact()], task_class="codegen/patch")[
        retry.proposal_id
    ]
    assert note["reused"] is False
    assert note["previously"] == ["rolled_back"]
    assert [p["status"] for p in note["prior_attempts"]] == ["rolled_back"]

    rejected = _proposal(suggested_change="Skip lint on docs-only changes")
    tracker.record_proposals([rejected.to_artifact()], task_class="codegen/patch")
    store.reject(rejected, reason="lint must always run")
    statuses = sorted(a["status"] for a in _ncp_attempts(workspace))
    assert statuses == ["proposed", "rejected", "rolled_back"]
    assert any(a["note"] == "rejected: lint must always run" for a in _ncp_attempts(workspace))


def test_post_accept_check_holds_and_writes_once(workspace):
    tracker = NCPImprovementTracker.for_workspace(workspace)
    proposal = _proposal()
    tracker.record_proposals([proposal.to_artifact()], task_class="codegen/patch")
    _log(tracker, [True, True, True, True, False])  # 0.8 before
    ProposalReviewStore(workspace / "policy-pack", mirror=False).accept(proposal)
    _log(tracker, [True] * 4 + [False])  # 0.8 after
    _log(tracker, [False] * 5, task_class="analysis")  # other class: ignored

    calls = []
    original = tracker._call_bridge

    def counting(command, args):
        calls.append(command)
        return original(command, args)

    tracker._call_bridge = counting  # type: ignore[method-assign]
    assert tracker.check_accepted("codegen/patch")[0]["verdict"] == "held"
    assert tracker.check_accepted("codegen/patch")[0]["verdict"] == "held"
    assert calls == ["improvement_update"]  # no new outcomes: no second write
    assert tracker.check_accepted("analysis") == []


# ── degraded paths ─────────────────────────────────────────────────────────


def test_mcp_mode_reports_improvement_records_unsupported(tmp_path):
    tracker = NCPImprovementTracker(mode="mcp", workspace_root=tmp_path)
    note = tracker.record_proposals([_proposal().to_artifact()], task_class="x")
    assert "direct mode" in next(iter(note.values()))["error"]


def test_old_bridge_reports_upgrade_hint(tmp_path):
    bridge = tmp_path / ".ncp" / "run.py"
    bridge.parent.mkdir()
    bridge.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "print(f'unknown command: {sys.argv[1]!r}', file=sys.stderr)\nsys.exit(2)\n"
    )
    bridge.chmod(0o755)
    tracker = NCPImprovementTracker.for_workspace(tmp_path)
    note = tracker.record_proposals([_proposal().to_artifact()], task_class="x")
    assert "sarathi init" in next(iter(note.values()))["error"]


def test_review_store_without_ncp_is_unchanged(tmp_path):
    (tmp_path / "policy-pack").mkdir()
    assert NCPImprovementTracker.for_workspace(tmp_path) is None
    decision = ProposalReviewStore(tmp_path / "policy-pack", mirror=False).accept(_proposal())
    assert decision["status"] == "accepted"


def test_outcome_log_skips_torn_lines(tmp_path):
    log = OutcomeLog(tmp_path / "o.jsonl")
    log.append({"task_class": "a", "success": True, "at": 1})
    with log.path.open("a") as handle:
        handle.write('{"task_class": "a", "succ')
    log.append({"task_class": "a", "success": False, "at": 2})
    assert [e["success"] for e in log.entries("a")] == [True, False]


def test_post_accept_thresholds_come_from_escalation_policy():
    policy = EvolutionPolicy.from_escalation(
        {"learn_evolve": {"post_accept_min_outcomes": 8, "post_accept_gate_ratio": 0.75}}
    )
    assert (policy.post_accept_min_outcomes, policy.post_accept_gate_ratio) == (8, 0.75)
    defaults = EvolutionPolicy.from_escalation({"learn_evolve": {"post_accept_min_outcomes": 0}})
    assert (defaults.post_accept_min_outcomes, defaults.post_accept_gate_ratio) == (1, 0.9)


# ── LEARN wiring ───────────────────────────────────────────────────────────


def test_learn_annotates_proposals_and_reports_post_accept_checks():
    from unittest.mock import patch

    from src.engine import Phase
    from src.phases.learn import LearnHandler

    tracker = MagicMock()
    proposal = _proposal()
    tracker.record_proposals.return_value = {proposal.proposal_id: {"attempt_id": "att_1"}}
    tracker.check_accepted.return_value = [{"verdict": "regressed", "proposal_id": "p"}]
    handler = LearnHandler(SimpleNamespace(escalation={}), ncp_improvement_tracker=tracker)
    outcome = SimpleNamespace(
        task_id="t", task_class=SimpleNamespace(value="codegen/patch"),
        quality_signals={}, signal_provenance={}, rollback_triggered=False, agent_used="claude",
    )
    task = SimpleNamespace(task_id="t", phase_results=[], harness_config=object())
    with patch("src.harness.measure_outcome", return_value=outcome), patch.object(
        handler.learning_store,
        "build_artifacts",
        return_value={"learning_record": {}, "lessons_learned": [], "patterns_updated": False},
    ), patch.object(handler.evolver, "ingest_harness_outcome", return_value=[]), patch.object(
        handler.evolver, "generate_policy_proposals", return_value=[proposal]
    ):
        result = handler.execute(task, Phase.LEARN)

    assert result.artifacts["policy_proposals"][0]["improvement"] == {"attempt_id": "att_1"}
    tracker.record_task_outcome.assert_called_once()
    assert tracker.record_task_outcome.call_args.kwargs["task_class"] == "codegen/patch"
    assert result.artifacts["post_accept_checks"] == [{"verdict": "regressed", "proposal_id": "p"}]
    assert result.evidence["post_accept_regressions"] == 1
