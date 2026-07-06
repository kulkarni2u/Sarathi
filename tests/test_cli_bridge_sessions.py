"""Tests for codex/opencode session resume support in the CLI bridge and TUI.

Mirrors the fake-CLI-script pattern in tests/test_cli_bridge_claude.py: a
throwaway executable script stands in for the real `codex`/`opencode`
binaries so argv construction and output parsing can be asserted on without
a live provider.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

from src.runtime import DispatchRequest
from src.runtime.providers.cli_bridge import (
    _build_codex_command,
    _build_opencode_command,
    _extract_session_id,
    dispatch_via_cli_bridge,
)
from src import tui_data


def _request(**overrides) -> DispatchRequest:
    base = dict(
        mode="execute",
        task_id="task-session-bridge",
        phase="Build",
        prompt="Implement the slice.",
        timeout_seconds=30,
    )
    base.update(overrides)
    return DispatchRequest(**base)


def _fake_script(tmp_path: Path, name: str, body: str) -> str:
    script = tmp_path / name
    script.write_text("#!/usr/bin/env python3\n" + body + "\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


# ── _extract_session_id (pure function) ──────────────────────────────────────

def test_extract_session_id_from_json_dict():
    raw = json.dumps({"session_id": "sess-json"})
    assert _extract_session_id(raw) == "sess-json"


def test_extract_session_id_from_jsonl_line():
    raw = "some log preamble\n" + json.dumps({"thread_id": "thread-abc"}) + "\nmore log"
    assert _extract_session_id(raw) == "thread-abc"


def test_extract_session_id_from_plain_text_line():
    raw = "Starting up...\nsession id: sess-plain-123\nDone."
    assert _extract_session_id(raw) == "sess-plain-123"


def test_extract_session_id_checks_multiple_chunks_in_order():
    assert _extract_session_id("", None, "conversation_id: conv-9") == "conv-9"


def test_extract_session_id_returns_none_when_absent():
    assert _extract_session_id("nothing to see here", "", None) is None


def test_extract_session_id_never_raises_on_garbage():
    assert _extract_session_id("{not valid json", "\x00\x01binary-ish") is None


# ── _build_codex_command / _build_opencode_command (argv builders) ──────────

def test_build_codex_command_without_session_is_plain_exec(tmp_path):
    command = _build_codex_command(
        "codex",
        output_path=tmp_path / "out.txt",
        model=None,
        session_id=None,
        prompt="do the thing",
    )
    assert command[:2] == ["codex", "exec"]
    assert "resume" not in command
    assert command[-1] == "do the thing"


def test_build_codex_command_with_session_inserts_resume_before_flags(tmp_path):
    command = _build_codex_command(
        "codex",
        output_path=tmp_path / "out.txt",
        model="gpt-5-codex",
        session_id="codex-sess-1",
        prompt="do the thing",
    )
    assert command[0] == "codex"
    assert command[1] == "exec"
    assert command[2] == "resume"
    assert command[3] == "codex-sess-1"
    # Same flags as a fresh run still present, after the resume slot.
    assert "--skip-git-repo-check" in command
    assert "--model" in command
    assert command[command.index("--model") + 1] == "gpt-5-codex"
    assert command[-1] == "do the thing"


def test_build_opencode_command_without_session_uses_dash_c():
    command = _build_opencode_command(
        "opencode", workspace_root="/workspace", session_id=None, prompt="hello"
    )
    assert "-c" in command
    assert "--session" not in command
    assert command[-1] == "hello"


def test_build_opencode_command_with_session_uses_dash_dash_session():
    command = _build_opencode_command(
        "opencode", workspace_root="/workspace", session_id="oc-sess-1", prompt="hello"
    )
    assert "-c" not in command
    assert command[command.index("--session") + 1] == "oc-sess-1"
    assert command[-1] == "hello"


# ── dispatch through a fake codex CLI ────────────────────────────────────────

def test_codex_resume_flows_through_dispatch_argv(tmp_path):
    body = (
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "o_idx = argv.index('-o')\n"
        "with open(argv[o_idx + 1], 'w') as f:\n"
        "    f.write('Implemented the resumed slice.')\n"
        "print('session id: codex-new-session', file=sys.stderr)\n"
    )
    path = _fake_script(tmp_path, "codex", body)
    response = dispatch_via_cli_bridge(
        provider="codex",
        path=path,
        workspace_root=str(tmp_path),
        request=_request(constraints={"codex_session_id": "codex-prior-session"}),
    )
    assert response.success is True
    command = response.artifacts["command"]
    assert command[1] == "exec"
    assert command[2] == "resume"
    assert command[3] == "codex-prior-session"
    # The id captured off this run's own output, not the resumed-from id.
    assert response.artifacts["codex_session_id"] == "codex-new-session"


def test_codex_without_session_constraint_uses_plain_exec(tmp_path):
    body = (
        "import sys\n"
        "argv = sys.argv[1:]\n"
        "o_idx = argv.index('-o')\n"
        "with open(argv[o_idx + 1], 'w') as f:\n"
        "    f.write('Implemented the slice.')\n"
    )
    path = _fake_script(tmp_path, "codex", body)
    response = dispatch_via_cli_bridge(
        provider="codex", path=path, workspace_root=str(tmp_path), request=_request()
    )
    assert response.success is True
    command = response.artifacts["command"]
    assert "resume" not in command
    # No session id anywhere in output -> telemetry key simply absent.
    assert "codex_session_id" not in response.artifacts


def test_codex_session_id_captured_from_output_file_json(tmp_path):
    body = (
        "import sys, json\n"
        "argv = sys.argv[1:]\n"
        "o_idx = argv.index('-o')\n"
        "with open(argv[o_idx + 1], 'w') as f:\n"
        "    f.write(json.dumps({'session_id': 'codex-file-session'}))\n"
    )
    path = _fake_script(tmp_path, "codex", body)
    response = dispatch_via_cli_bridge(
        provider="codex", path=path, workspace_root=str(tmp_path), request=_request()
    )
    assert response.success is True
    assert response.artifacts["codex_session_id"] == "codex-file-session"


def test_codex_dispatch_uses_workspace_dir_constraint_for_cwd(tmp_path):
    parent_workspace = tmp_path / "parent"
    isolated_workspace = tmp_path / "isolated"
    parent_workspace.mkdir()
    isolated_workspace.mkdir()
    body = (
        "import json, os, sys\n"
        "argv = sys.argv[1:]\n"
        "o_idx = argv.index('-o')\n"
        "with open(argv[o_idx + 1], 'w') as f:\n"
        "    f.write(json.dumps({"
        "'success': True,"
        "'outputs': {'summary': 'ok'},"
        "'evidence': {'cwd': os.getcwd()},"
        "'artifacts': {'cwd': os.getcwd()}"
        "}))\n"
    )
    path = _fake_script(tmp_path, "codex", body)

    response = dispatch_via_cli_bridge(
        provider="codex",
        path=path,
        workspace_root=str(parent_workspace),
        request=_request(constraints={"workspace_dir": str(isolated_workspace)}),
    )

    assert response.success is True
    assert response.evidence["cwd"] == str(isolated_workspace)
    assert response.artifacts["cwd"] == str(isolated_workspace)
    assert response.artifacts["workspace_root"] == str(isolated_workspace)


# ── dispatch through a fake opencode CLI ─────────────────────────────────────

def test_opencode_resume_flows_through_dispatch_argv(tmp_path):
    body = (
        "import sys\n"
        "print('Implemented via resumed session.')\n"
        "print('session id: opencode-new-session', file=sys.stderr)\n"
    )
    path = _fake_script(tmp_path, "opencode", body)
    response = dispatch_via_cli_bridge(
        provider="opencode",
        path=path,
        workspace_root=str(tmp_path),
        request=_request(constraints={"opencode_session_id": "opencode-prior-session"}),
    )
    assert response.success is True
    command = response.artifacts["command"]
    assert "-c" not in command
    assert command[command.index("--session") + 1] == "opencode-prior-session"
    assert response.artifacts["opencode_session_id"] == "opencode-new-session"


def test_opencode_without_session_constraint_falls_back_to_dash_c(tmp_path):
    body = "print('Implemented the slice.')\n"
    path = _fake_script(tmp_path, "opencode", body)
    response = dispatch_via_cli_bridge(
        provider="opencode", path=path, workspace_root=str(tmp_path), request=_request()
    )
    assert response.success is True
    command = response.artifacts["command"]
    assert "-c" in command
    assert "--session" not in command
    assert "opencode_session_id" not in response.artifacts


def test_opencode_dispatch_uses_workspace_dir_constraint_for_dir_and_cwd(tmp_path):
    parent_workspace = tmp_path / "parent"
    isolated_workspace = tmp_path / "isolated"
    parent_workspace.mkdir()
    isolated_workspace.mkdir()
    body = (
        "import json, os, sys\n"
        "print(json.dumps({"
        "'success': True,"
        "'outputs': {'summary': 'ok'},"
        "'evidence': {'cwd': os.getcwd(), 'argv': sys.argv[1:]},"
        "'artifacts': {'cwd': os.getcwd(), 'argv': sys.argv[1:]}"
        "}))\n"
    )
    path = _fake_script(tmp_path, "opencode", body)

    response = dispatch_via_cli_bridge(
        provider="opencode",
        path=path,
        workspace_root=str(parent_workspace),
        request=_request(constraints={"workspace_dir": str(isolated_workspace)}),
    )

    assert response.success is True
    assert response.evidence["cwd"] == str(isolated_workspace)
    assert response.artifacts["cwd"] == str(isolated_workspace)
    command = response.artifacts["command"]
    assert command[command.index("--dir") + 1] == str(isolated_workspace)
    assert response.artifacts["workspace_root"] == str(isolated_workspace)


# ── TUI ChatSession: per-provider session tracking ───────────────────────────

def test_chat_session_claude_session_id_property_backward_compat():
    session = tui_data.ChatSession()
    assert session.claude_session_id is None
    session.claude_session_id = "sid-1"
    assert session.claude_session_id == "sid-1"
    assert session.session_ids == {"claude": "sid-1"}
    session.claude_session_id = None
    assert session.claude_session_id is None
    assert "claude" not in session.session_ids


def test_chat_session_tracks_codex_session_id_across_turns(monkeypatch):
    def fake_which(name):
        return "/usr/bin/codex" if name == "codex" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    calls = []

    class FakeCompleted:
        def __init__(self, stdout, stderr=""):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        calls.append(command)
        return FakeCompleted("ok", stderr="session id: codex-tui-session")

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()
    first = session.send("hello")
    assert first == "ok"
    assert "resume" not in calls[0]
    assert session.session_ids["codex"] == "codex-tui-session"

    second = session.send("again")
    assert "resume" in calls[1]
    assert "codex-tui-session" in calls[1]
    assert second == "ok"


def test_chat_session_tracks_opencode_session_id_across_turns(monkeypatch):
    def fake_which(name):
        return "/usr/bin/opencode" if name == "opencode" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    calls = []

    class FakeCompleted:
        def __init__(self, stdout, stderr=""):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        calls.append(command)
        return FakeCompleted("ok", stderr="session id: oc-tui-session")

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()
    first = session.send("hello")
    assert first == "ok"
    assert "--session" not in calls[0]
    assert session.session_ids["opencode"] == "oc-tui-session"

    second = session.send("again")
    assert "--session" in calls[1]
    assert "oc-tui-session" in calls[1]
    assert second == "ok"


def test_chat_session_clear_and_reset_drop_all_provider_sessions():
    session = tui_data.ChatSession()
    session.session_ids = {"claude": "sid-1", "codex": "sid-2"}
    session.history = [("q", "a")]

    session.reset_session()
    assert session.session_ids == {}
    assert session.history == [("q", "a")]

    session.session_ids = {"claude": "sid-1", "codex": "sid-2"}
    session.clear()
    assert session.session_ids == {}
    assert session.history == []


def test_set_provider_clears_all_stored_sessions(monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("claude", "codex") else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    session = tui_data.ChatSession()
    session.session_ids = {"claude": "sid-1", "codex": "sid-2"}

    assert session.set_provider("codex") is True
    assert session.session_ids == {}
