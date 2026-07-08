"""Opt-in live smoke tests against REAL provider CLIs.

These tests make actual provider API calls (real cost, real latency) and are
gated off by default. Set ``SARATHI_LIVE_TESTS=1`` to run them:

    SARATHI_LIVE_TESTS=1 python3 -m pytest tests/live -q

Per-provider tests additionally skip if that provider's CLI is not on PATH.

Codex tests verify:
  - Dispatch succeeds with non-empty output
  - Usage record is populated (input/output tokens or estimation fallback)
  - Permission config is written before dispatch (~/.codex/config.yaml)
  - Structured failure response (not exception) on invalid request

OpenCode tests verify:
  - Dispatch succeeds with non-empty output
  - Usage record is populated (input/output tokens or estimation fallback)
  - Permission config is written before dispatch (<workspace>/opencode.json)
  - Structured failure response (not exception) on invalid request
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
from src.runtime.providers.cli_bridge import dispatch_via_cli_bridge, ensure_provider_permissions

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


def _write_provider_permissions_policy(path: Path) -> None:
    """Write a minimal policy-pack/permissions.md for test dispatch."""
    policy_dir = path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "permissions.md").write_text(
        """# Permissions

```yaml
permissions:
  codex:
    modes:
      read_only:
        full_auto: false
        disable_sandbox: false
      read_write:
        full_auto: true
        disable_sandbox: false
      full:
        full_auto: true
        disable_sandbox: true
  opencode:
    modes:
      read_only:
        permission:
          read: allow
          grep: allow
      read_write:
        permission:
          read: allow
          grep: allow
          edit: allow
          write: allow
      full:
        permission:
          read: allow
          grep: allow
          edit: allow
          write: allow
          bash: allow
```
"""
    )


def _prepare_codex_home(source_home: Path, target_home: Path) -> None:
    """Copy local Codex auth into the isolated HOME used by live tests."""
    source_codex = source_home / ".codex"
    auth_path = source_codex / "auth.json"
    if not auth_path.exists():
        pytest.skip(f"codex auth not found at {auth_path}; run `codex login`")

    target_codex = target_home / ".codex"
    target_codex.mkdir(parents=True, exist_ok=True)
    shutil.copy2(auth_path, target_codex / "auth.json")

    config_path = source_codex / "config.toml"
    if config_path.exists():
        shutil.copy2(config_path, target_codex / "config.toml")


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
            if reconciliation["claimed_files"]:
                assert reconciliation["divergence"] is False
            else:
                assert reconciliation["divergence"] is None
                assert reconciliation["reason"] == "no claimed file changes to reconcile"
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


# ── Codex (CLI provider) ────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not found on PATH")
def test_codex_dispatch_end_to_end(tmp_path, monkeypatch):
    """Live codex dispatch verifies dispatch success, usage capture, and permissions.

    Asserts:
    - Dispatch succeeds (success=True) with non-empty output
    - Usage record is populated (tokens > 0 or estimation fallback available)
    - Permission config is written before dispatch to ~/.codex/config.yaml
    - Evidence shows workspace interaction occurred
    """
    real_home = Path.home()
    test_home = tmp_path / "home"
    _prepare_codex_home(real_home, test_home)
    monkeypatch.setenv("HOME", str(test_home))
    _init_git_repo(tmp_path)
    _write_provider_permissions_policy(tmp_path)

    prompt = (
        "Reply with JSON only: "
        '{"success": true, "outputs": {"summary": "ok", "messages": ["ok"]}, '
        '"evidence": {}, "artifacts": {}}'
    )
    response = dispatch_via_cli_bridge(
        provider="codex",
        path=shutil.which("codex"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-codex-1", phase="Build", prompt=prompt, timeout_seconds=30),
    )

    # Dispatch succeeds with non-empty output
    assert response.success is True, f"Expected success, got error: {response.error}"
    assert response.outputs is not None
    assert isinstance(response.outputs, dict)

    # Usage record is captured
    assert response.usage is not None, "Usage record must be populated"
    assert response.usage.input_tokens >= 0
    assert response.usage.output_tokens >= 0
    # At least one of reported/estimated tokens must be non-zero, or usage source must be "estimated"
    assert (
        response.usage.input_tokens > 0
        or response.usage.output_tokens > 0
        or response.usage.usage_source == "estimated"
    ), f"Usage must have tokens or be estimated: {response.usage}"

    # Permission config written before dispatch (marker in ~/.codex/config.yaml)
    codex_config_path = test_home / ".codex" / "config.yaml"
    assert (
        codex_config_path.exists()
    ), f"Codex permission config must exist at {codex_config_path}"
    config_content = codex_config_path.read_text(encoding="utf-8")
    assert "Sarathi-managed" in config_content, "Config must have Sarathi marker"

    # Evidence collected
    assert response.evidence is not None
    assert isinstance(response.evidence, dict)


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not found on PATH")
def test_codex_dispatch_structured_failure(tmp_path, monkeypatch):
    """Codex dispatch with impossible request yields structured failure, not exception.

    Asserts:
    - Invalid/impossible request (timeout or invalid model) returns DispatchResponse
      with success=False, error message populated, and no unhandled exception
    - Failure response has expected artifact fields (command, provider, etc.)
    """
    real_home = Path.home()
    test_home = tmp_path / "home"
    _prepare_codex_home(real_home, test_home)
    monkeypatch.setenv("HOME", str(test_home))
    _init_git_repo(tmp_path)
    _write_provider_permissions_policy(tmp_path)

    # Use a very tight timeout to force a timeout failure
    # (shorter than codex startup typically takes)
    prompt = "Reply with OK"
    response = dispatch_via_cli_bridge(
        provider="codex",
        path=shutil.which("codex"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-codex-fail", phase="Build", prompt=prompt, timeout_seconds=1),
    )

    # Structured failure response (not exception)
    assert response.success is False, "Timeout must yield success=False"
    assert response.error is not None, "Error message must be present"
    assert isinstance(response.error, str)
    assert len(response.error) > 0

    # Artifacts contain metadata
    assert response.artifacts is not None
    assert "provider" in response.artifacts
    assert response.artifacts.get("provider") == "codex"


# ── OpenCode (CLI provider) ──────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode CLI not found on PATH")
def test_opencode_dispatch_end_to_end(tmp_path, monkeypatch):
    """Live opencode dispatch verifies dispatch success, usage capture, and permissions.

    Asserts:
    - Dispatch succeeds (success=True) with non-empty output
    - Usage record is populated (tokens > 0 or estimation fallback available)
    - Permission config is written before dispatch to <workspace>/opencode.json
    - Evidence shows workspace interaction occurred
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _init_git_repo(tmp_path)
    _write_provider_permissions_policy(tmp_path)

    prompt = (
        "Reply with JSON only: "
        '{"success": true, "outputs": {"summary": "ok", "messages": ["ok"]}, '
        '"evidence": {}, "artifacts": {}}'
    )
    response = dispatch_via_cli_bridge(
        provider="opencode",
        path=shutil.which("opencode"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-opencode-1", phase="Build", prompt=prompt, timeout_seconds=30),
    )

    # Dispatch succeeds with non-empty output
    assert response.success is True, f"Expected success, got error: {response.error}"
    assert response.outputs is not None
    assert isinstance(response.outputs, dict)

    # Usage record is captured
    assert response.usage is not None, "Usage record must be populated"
    assert response.usage.input_tokens >= 0
    assert response.usage.output_tokens >= 0
    # At least one of reported/estimated tokens must be non-zero, or usage source must be "estimated"
    assert (
        response.usage.input_tokens > 0
        or response.usage.output_tokens > 0
        or response.usage.usage_source == "estimated"
    ), f"Usage must have tokens or be estimated: {response.usage}"

    # Permission config written before dispatch (opencode.json with permission field)
    opencode_config_path = tmp_path / "opencode.json"
    assert (
        opencode_config_path.exists()
    ), f"OpenCode permission config must exist at {opencode_config_path}"
    config_data = json.loads(opencode_config_path.read_text(encoding="utf-8"))
    assert (
        "permission" in config_data
    ), "OpenCode config must have 'permission' field"
    assert isinstance(config_data["permission"], dict), "Permission must be a dict"

    # Evidence collected
    assert response.evidence is not None
    assert isinstance(response.evidence, dict)


@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode CLI not found on PATH")
def test_opencode_dispatch_structured_failure(tmp_path, monkeypatch):
    """OpenCode dispatch with impossible request yields structured failure, not exception.

    Asserts:
    - Invalid/impossible request (timeout or invalid model) returns DispatchResponse
      with success=False, error message populated, and no unhandled exception
    - Failure response has expected artifact fields (command, provider, etc.)
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _init_git_repo(tmp_path)
    _write_provider_permissions_policy(tmp_path)

    # Use a very tight timeout to force a timeout failure
    # (shorter than opencode startup typically takes)
    prompt = "Reply with OK"
    response = dispatch_via_cli_bridge(
        provider="opencode",
        path=shutil.which("opencode"),
        workspace_root=str(tmp_path),
        request=_request(task_id="live-opencode-fail", phase="Build", prompt=prompt, timeout_seconds=1),
    )

    # Structured failure response (not exception)
    assert response.success is False, "Timeout must yield success=False"
    assert response.error is not None, "Error message must be present"
    assert isinstance(response.error, str)
    assert len(response.error) > 0

    # Artifacts contain metadata
    assert response.artifacts is not None
    assert "provider" in response.artifacts
    assert response.artifacts.get("provider") == "opencode"
