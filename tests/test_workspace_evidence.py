"""Tests for measured workspace evidence: snapshot, delta, reconciliation, and bridge wiring."""
from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

from src.runtime import DispatchRequest
from src.runtime.providers.cli_bridge import dispatch_via_cli_bridge
from src.runtime.workspace_evidence import (
    measure_workspace_delta,
    reconcile_claimed_changes,
    snapshot_workspace,
)


def _request(**overrides) -> DispatchRequest:
    base = dict(
        mode="execute",
        task_id="task-workspace-evidence",
        phase="Build",
        prompt="Implement the slice.",
        timeout_seconds=30,
    )
    base.update(overrides)
    return DispatchRequest(**base)


def _fake_claude(tmp_path: Path, body: str) -> str:
    script = tmp_path / "claude"
    script.write_text("#!/usr/bin/env python3\n" + body + "\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], capture_output=True, check=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "seed"], capture_output=True, check=True)


# ── measure_workspace_delta ──────────────────────────────────────────────────

def test_delta_detects_newly_added_file():
    before = {"measured": True, "status": {}}
    after = {"measured": True, "status": {"new_file.py": "??"}}
    delta = measure_workspace_delta(before, after)
    assert delta["measured"] is True
    assert delta["files_changed"] == ["new_file.py"]
    assert delta["change_count"] == 1


def test_delta_detects_modified_file():
    before = {"measured": True, "status": {"src/foo.py": ""}}
    after = {"measured": True, "status": {"src/foo.py": " M"}}
    delta = measure_workspace_delta(before, after)
    assert delta["measured"] is True
    assert delta["files_changed"] == ["src/foo.py"]
    assert delta["change_count"] == 1


def test_delta_reports_no_changes_when_snapshots_match():
    before = {"measured": True, "status": {"src/foo.py": " M"}}
    after = {"measured": True, "status": {"src/foo.py": " M"}}
    delta = measure_workspace_delta(before, after)
    assert delta["measured"] is True
    assert delta["files_changed"] == []
    assert delta["change_count"] == 0


def test_delta_unmeasured_when_before_or_after_unmeasured():
    measured = {"measured": True, "status": {}}
    unmeasured = {"measured": False, "reason": "not_a_git_repo"}

    delta = measure_workspace_delta(unmeasured, measured)
    assert delta["measured"] is False
    assert delta["files_changed"] == []
    assert delta["change_count"] == 0
    assert "not_a_git_repo" in delta["reason"]

    delta2 = measure_workspace_delta(measured, unmeasured)
    assert delta2["measured"] is False
    assert "not_a_git_repo" in delta2["reason"]


# ── reconcile_claimed_changes ────────────────────────────────────────────────

def test_reconcile_claims_match_measured_changes():
    delta = {"measured": True, "files_changed": ["src/foo.py"], "change_count": 1}
    outputs = {"files_changed": ["src/foo.py"]}
    result = reconcile_claimed_changes(delta, outputs)
    assert result["divergence"] is False
    assert result["claimed_files"] == ["src/foo.py"]
    assert result["measured_files"] == ["src/foo.py"]
    assert result["claimed_but_unchanged"] == []
    assert result["changed_but_unclaimed"] == []


def test_reconcile_claimed_but_unchanged_file_is_divergence():
    delta = {"measured": True, "files_changed": [], "change_count": 0}
    outputs = {"files_changed": ["ghost.py"]}
    result = reconcile_claimed_changes(delta, outputs)
    assert result["divergence"] is True
    assert result["claimed_but_unchanged"] == ["ghost.py"]
    assert result["changed_but_unclaimed"] == []


def test_reconcile_changed_but_unclaimed_is_divergence():
    delta = {"measured": True, "files_changed": ["src/foo.py", "src/bar.py"], "change_count": 2}
    outputs = {"files_changed": ["src/foo.py"]}
    result = reconcile_claimed_changes(delta, outputs)
    assert result["divergence"] is True
    assert result["changed_but_unclaimed"] == ["src/bar.py"]
    assert result["claimed_but_unchanged"] == []


def test_reconcile_no_claim_present_returns_none_divergence():
    delta = {"measured": True, "files_changed": ["src/foo.py"], "change_count": 1}
    result = reconcile_claimed_changes(delta, {})
    assert result["divergence"] is None
    assert "reason" in result
    assert result["claimed_files"] == []
    assert result["measured_files"] == ["src/foo.py"]


def test_reconcile_unmeasured_delta_returns_none_divergence():
    delta = {"measured": False, "files_changed": [], "change_count": 0, "reason": "not_a_git_repo"}
    outputs = {"files_changed": ["src/foo.py"]}
    result = reconcile_claimed_changes(delta, outputs)
    assert result["divergence"] is None
    assert "reason" in result
    assert result["claimed_files"] == ["src/foo.py"]
    assert result["measured_files"] == []


def test_reconcile_handles_work_unit_result_files_changed():
    delta = {"measured": True, "files_changed": ["src/foo.py"], "change_count": 1}
    outputs = {"work_unit_result": {"files_changed": ["src/foo.py"]}}
    result = reconcile_claimed_changes(delta, outputs)
    assert result["divergence"] is False
    assert result["claimed_files"] == ["src/foo.py"]


def test_reconcile_is_defensive_about_non_list_types():
    delta = {"measured": True, "files_changed": [], "change_count": 0}
    outputs = {"files_changed": "not-a-list", "work_unit_result": {"files_changed": 123}}
    result = reconcile_claimed_changes(delta, outputs)
    # No usable claim found -> no false agreement.
    assert result["divergence"] is None
    assert result["claimed_files"] == []


# ── snapshot_workspace ────────────────────────────────────────────────────────

def test_snapshot_non_git_workspace_is_unmeasured(tmp_path):
    snapshot = snapshot_workspace(str(tmp_path))
    assert snapshot["measured"] is False
    assert "reason" in snapshot


# ── integration: dispatch_via_cli_bridge wiring ──────────────────────────────

def test_dispatch_attaches_workspace_delta_when_claim_matches_reality(tmp_path):
    _init_git_repo(tmp_path)

    body = (
        "import json, sys\n"
        "sys.stdin.read()\n"
        "with open('newfile.py', 'w') as f:\n"
        "    f.write('print(1)\\n')\n"
        "print(json.dumps({\n"
        "    'success': True,\n"
        "    'outputs': {'messages': ['done'], 'files_changed': ['newfile.py']},\n"
        "    'evidence': {},\n"
        "    'artifacts': {}\n"
        "}))\n"
    )
    path = _fake_claude(tmp_path, body)

    response = dispatch_via_cli_bridge(
        provider="claude", path=path, workspace_root=str(tmp_path), request=_request()
    )

    assert response.success is True
    workspace_delta = response.evidence["workspace_delta"]
    assert workspace_delta["measured"] is True
    assert "newfile.py" in workspace_delta["files_changed"]

    reconciliation = response.evidence["claim_reconciliation"]
    assert reconciliation["divergence"] is False
    assert "newfile.py" in reconciliation["claimed_files"]
    assert "newfile.py" in reconciliation["measured_files"]
    assert "workspace_unchanged_on_success" not in response.evidence


def test_dispatch_flags_divergence_when_claim_is_false(tmp_path):
    _init_git_repo(tmp_path)

    body = (
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({\n"
        "    'success': True,\n"
        "    'outputs': {'messages': ['done'], 'files_changed': ['ghost.py']},\n"
        "    'evidence': {},\n"
        "    'artifacts': {}\n"
        "}))\n"
    )
    path = _fake_claude(tmp_path, body)

    response = dispatch_via_cli_bridge(
        provider="claude", path=path, workspace_root=str(tmp_path), request=_request(phase="Build")
    )

    assert response.success is True
    workspace_delta = response.evidence["workspace_delta"]
    assert workspace_delta["measured"] is True
    assert workspace_delta["change_count"] == 0

    reconciliation = response.evidence["claim_reconciliation"]
    assert reconciliation["divergence"] is True
    assert reconciliation["claimed_but_unchanged"] == ["ghost.py"]

    assert response.evidence["workspace_unchanged_on_success"] is True
    # Evidence stays evidence -- success is not flipped.
    assert response.success is True


def test_dispatch_in_non_git_workspace_attaches_unmeasured_delta(tmp_path):
    body = (
        "import json, sys\n"
        "sys.stdin.read()\n"
        "print(json.dumps({\n"
        "    'success': True,\n"
        "    'outputs': {'messages': ['done']},\n"
        "    'evidence': {},\n"
        "    'artifacts': {}\n"
        "}))\n"
    )
    path = _fake_claude(tmp_path, body)

    response = dispatch_via_cli_bridge(
        provider="claude", path=path, workspace_root=str(tmp_path), request=_request()
    )

    assert response.success is True
    workspace_delta = response.evidence["workspace_delta"]
    assert workspace_delta["measured"] is False
    assert "reason" in workspace_delta

    reconciliation = response.evidence["claim_reconciliation"]
    assert reconciliation["divergence"] is None
