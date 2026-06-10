"""Opt-in live smoke tests against REAL provider CLIs.

These tests make actual provider API calls (real cost, real latency) and are
gated off by default. Set ``SARATHI_LIVE_TESTS=1`` to run them:

    SARATHI_LIVE_TESTS=1 python3 -m pytest tests/live -q

Per-provider tests additionally skip if that provider's CLI is not on PATH.
The codex/opencode tests below are scaffolding: they assert the same gating
pattern but have no real assertions yet, so they will skip (no CLI present).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from src.runtime import DispatchRequest
from src.runtime.providers.cli_bridge import dispatch_via_cli_bridge

pytestmark = pytest.mark.skipif(
    not os.environ.get("SARATHI_LIVE_TESTS"),
    reason="set SARATHI_LIVE_TESTS=1 to run live provider tests",
)


def _init_git_repo(path: Path) -> None:
    """Seed a tmp git repo, mirroring tests/test_workspace_evidence.py."""
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "commit.gpgsign", "false"], capture_output=True, check=True)
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "seed"], capture_output=True, check=True)


def _request(**overrides) -> DispatchRequest:
    base = dict(
        mode="execute",
        task_id="live-1",
        phase="Build",
        prompt="",
        timeout_seconds=240,
    )
    base.update(overrides)
    return DispatchRequest(**base)


# ── Claude (real CLI, authenticated) ─────────────────────────────────────────

@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not found on PATH")
def test_claude_dispatch_end_to_end(tmp_path):
    """Round-trip a real `claude -p --output-format json` dispatch.

    Validates Sarathi's measurement (usage capture, session id, cost,
    workspace-delta evidence, claim reconciliation) -- not whether Claude
    actually wrote the file. Either outcome (file created or not) is
    acceptable as long as Sarathi's evidence is internally consistent.
    """
    _init_git_repo(tmp_path)

    prompt = (
        "Create a file named hello.txt containing exactly 'hello sarathi'. "
        "Then respond with JSON only: "
        '{"success": true, "outputs": {"summary": "created hello.txt", '
        '"files_changed": ["hello.txt"], "messages": ["done"]}, '
        '"evidence": {"implementation_complete": true}, "artifacts": {}}'
    )

    response = dispatch_via_cli_bridge(
        provider="claude",
        path=shutil.which("claude"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-1", phase="Build", prompt=prompt, timeout_seconds=240),
    )

    assert response.success is True, response.error

    # Usage telemetry must be real, reported (or mixed) provider data.
    assert response.usage is not None
    assert response.usage.usage_source in {"reported", "mixed"}
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0

    # Session/cost artifacts from the Claude Code envelope.
    assert isinstance(response.artifacts.get("claude_session_id"), str)
    assert response.artifacts["claude_session_id"]
    assert response.artifacts.get("total_cost_usd", 0) > 0

    # Workspace evidence must be measured (tmp repo is a real git repo).
    workspace_delta = response.evidence["workspace_delta"]
    assert workspace_delta["measured"] is True

    reconciliation = response.evidence["claim_reconciliation"]

    # Validate Sarathi's measurement is internally consistent regardless of
    # whether Claude actually wrote hello.txt.
    if workspace_delta["change_count"] > 0:
        # Something changed in the workspace -- reconciliation must reflect
        # the measured files, and "unchanged on success" must not fire.
        assert reconciliation["measured_files"] == workspace_delta["files_changed"]
        assert "workspace_unchanged_on_success" not in response.evidence
        if (tmp_path / "hello.txt").exists():
            assert "hello.txt" in workspace_delta["files_changed"]
            assert reconciliation["divergence"] is False
            assert (tmp_path / "hello.txt").read_text(encoding="utf-8").strip() == "hello sarathi"
    else:
        # Claude declined to write the file -- Sarathi must have flagged the
        # unchanged-workspace evidence rather than fabricating agreement.
        assert response.evidence.get("workspace_unchanged_on_success") is True
        assert reconciliation["divergence"] is not True


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not found on PATH")
def test_claude_session_resume(tmp_path):
    """Dispatch twice with --resume and confirm session continuity."""
    _init_git_repo(tmp_path)

    first_prompt = (
        "Remember the codeword 'sarathi-mango'. Reply with JSON only: "
        '{"success": true, "outputs": {"summary": "ok", "messages": ["ok"]}, '
        '"evidence": {}, "artifacts": {}}'
    )
    first = dispatch_via_cli_bridge(
        provider="claude",
        path=shutil.which("claude"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-2a", phase="Build", prompt=first_prompt, timeout_seconds=240),
    )
    assert first.success is True, first.error
    session_id = first.artifacts.get("claude_session_id")
    assert isinstance(session_id, str) and session_id

    second_prompt = (
        'What was the codeword? Reply with JSON only: '
        '{"success": true, "outputs": {"summary": "<codeword>", '
        '"messages": ["<codeword>"]}, "evidence": {}, "artifacts": {}}'
    )
    second = dispatch_via_cli_bridge(
        provider="claude",
        path=shutil.which("claude"),
        workspace_root=str(tmp_path),
        request=_request(
            task_id="live-2b",
            phase="Build",
            prompt=second_prompt,
            timeout_seconds=240,
            constraints={"claude_session_id": session_id},
        ),
    )
    assert second.success is True, second.error

    haystack = json.dumps(second.outputs).lower()
    assert "sarathi-mango" in haystack


# ── Codex / OpenCode scaffolding (skip in this environment) ─────────────────

@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not found on PATH")
def test_codex_dispatch_end_to_end_placeholder(tmp_path):
    """Scaffolding for a future live codex smoke test.

    Mirrors the claude dispatch shape; intentionally minimal until a codex
    CLI is available in CI/dev environments.
    """
    _init_git_repo(tmp_path)
    prompt = (
        "Reply with JSON only: "
        '{"success": true, "outputs": {"summary": "ok", "messages": ["ok"]}, '
        '"evidence": {}, "artifacts": {}}'
    )
    response = dispatch_via_cli_bridge(
        provider="codex",
        path=shutil.which("codex"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-codex", phase="Build", prompt=prompt, timeout_seconds=240),
    )
    assert response.success is True, response.error


@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode CLI not found on PATH")
def test_opencode_dispatch_end_to_end_placeholder(tmp_path):
    """Scaffolding for a future live opencode smoke test.

    Mirrors the claude dispatch shape; intentionally minimal until an
    opencode CLI is available in CI/dev environments.
    """
    _init_git_repo(tmp_path)
    prompt = (
        "Reply with JSON only: "
        '{"success": true, "outputs": {"summary": "ok", "messages": ["ok"]}, '
        '"evidence": {}, "artifacts": {}}'
    )
    response = dispatch_via_cli_bridge(
        provider="opencode",
        path=shutil.which("opencode"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-opencode", phase="Build", prompt=prompt, timeout_seconds=240),
    )
    assert response.success is True, response.error
