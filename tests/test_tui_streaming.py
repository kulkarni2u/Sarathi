"""Tests for streaming chat output from the codex and opencode providers.

Mirrors the fake-CLI-script pattern in tests/test_cli_bridge_sessions.py: a
throwaway executable script stands in for the real `codex`/`opencode`
binaries, printing output in multiple flushes (with small sleeps in
between) so the incremental-read path in `ChatSession.send_streaming` can
be exercised for real rather than through a monkeypatched `Popen`.
"""
from __future__ import annotations

import json
import stat
import time
from pathlib import Path

from src import tui_data


def _fake_script(tmp_path: Path, name: str, body: str) -> str:
    script = tmp_path / name
    script.write_text("#!/usr/bin/env python3\n" + body + "\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def _which_only(monkeypatch, name: str, path: str) -> None:
    monkeypatch.setattr(
        tui_data.shutil, "which", lambda n: path if n == name else None
    )


# ── codex streaming ──────────────────────────────────────────────────────────

_CODEX_JSONL_SCRIPT = """
import sys, time, json

sys.stdout.write(json.dumps({"type": "agent_message_delta", "delta": "Hello"}) + "\\n")
sys.stdout.flush()
time.sleep(0.15)
sys.stdout.write("not valid json at all\\n")
sys.stdout.flush()
time.sleep(0.05)
sys.stdout.write(json.dumps({"type": "agent_message_delta", "delta": ", world!"}) + "\\n")
sys.stdout.flush()
time.sleep(0.05)
sys.stdout.write(json.dumps({"type": "task_complete", "last_agent_message": "Hello, world!"}) + "\\n")
sys.stdout.flush()
sys.stderr.write("session id: codex-stream-session\\n")
"""


def test_codex_streaming_yields_incremental_deltas_and_skips_malformed_lines(tmp_path, monkeypatch):
    path = _fake_script(tmp_path, "codex", _CODEX_JSONL_SCRIPT)

    def fake_which(name):
        return path if name == "codex" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    session = tui_data.ChatSession(workspace_root=str(tmp_path))
    session.timeout = 10

    seen: list[str] = []
    seen_times: list[float] = []
    start = time.monotonic()
    reply = session.send_streaming(
        "hi",
        on_text=lambda text: (seen.append(text), seen_times.append(time.monotonic() - start)),
    )

    assert reply == "Hello, world!"
    # At least two distinct incremental yields before the final value.
    assert len(seen) >= 2
    assert seen[0] == "Hello"
    assert seen[-1] == "Hello, world!"
    # The malformed line in between must not have raised or broken parsing.
    assert all(isinstance(text, str) for text in seen)
    # Real incremental delivery: the first and last callback are separated
    # by roughly the sleep time between flushes, not delivered in one burst
    # after the process exits.
    assert seen_times[-1] - seen_times[0] > 0.1
    assert session.session_ids.get("codex") == "codex-stream-session"
    assert session.history == [("hi", "Hello, world!")]


def test_codex_streaming_resume_argv_includes_exec_resume_json(tmp_path, monkeypatch):
    captured = {}

    def fake_run_streaming(self, command, stdin_text, on_line):
        captured["command"] = command
        return "", False, 0

    monkeypatch.setattr(
        tui_data.ChatSession, "_run_streaming_subprocess", fake_run_streaming
    )
    _which_only(monkeypatch, "codex", "/usr/bin/codex")

    session = tui_data.ChatSession()
    session.session_ids["codex"] = "codex-prior-session"
    session.send_streaming("continue please")

    command = captured["command"]
    assert command[0] == "/usr/bin/codex"
    assert command[1] == "exec"
    assert command[2] == "resume"
    assert command[3] == "codex-prior-session"
    assert "--json" in command
    assert command[-1] == "continue please"


def test_codex_streaming_no_session_uses_plain_exec_json(monkeypatch):
    captured = {}

    def fake_run_streaming(self, command, stdin_text, on_line):
        captured["command"] = command
        return "", False, 0

    monkeypatch.setattr(
        tui_data.ChatSession, "_run_streaming_subprocess", fake_run_streaming
    )
    _which_only(monkeypatch, "codex", "/usr/bin/codex")

    session = tui_data.ChatSession()
    session.send_streaming("hello")

    command = captured["command"]
    assert command[:2] == ["/usr/bin/codex", "exec"]
    assert "resume" not in command
    assert "--json" in command


def test_codex_streaming_nonzero_exit_with_no_output_is_error(monkeypatch):
    def fake_run_streaming(self, command, stdin_text, on_line):
        return "codex blew up", False, 1

    monkeypatch.setattr(
        tui_data.ChatSession, "_run_streaming_subprocess", fake_run_streaming
    )
    _which_only(monkeypatch, "codex", "/usr/bin/codex")

    session = tui_data.ChatSession()
    reply = session.send_streaming("hi")

    assert "codex exited with 1" in reply
    assert "codex blew up" in reply
    assert session.history == []


# ── opencode streaming ───────────────────────────────────────────────────────

_OPENCODE_SCRIPT = """
import sys, time

sys.stdout.write("Thinking...\\n")
sys.stdout.flush()
time.sleep(0.15)
sys.stdout.write("Here is the answer.\\n")
sys.stdout.flush()
"""


def test_opencode_streaming_yields_chunks_as_they_arrive(tmp_path, monkeypatch):
    path = _fake_script(tmp_path, "opencode", _OPENCODE_SCRIPT)
    monkeypatch.setattr(
        tui_data.shutil, "which", lambda name: path if name == "opencode" else None
    )

    session = tui_data.ChatSession(workspace_root=str(tmp_path))
    session.timeout = 10

    seen: list[str] = []
    reply = session.send_streaming("hi", on_text=lambda text: seen.append(text))

    assert len(seen) >= 2
    assert seen[0] == "Thinking..."
    assert seen[-1] == "Thinking...\nHere is the answer."
    assert reply == "Thinking...\nHere is the answer."
    assert session.history == [("hi", reply)]


def test_opencode_streaming_resume_argv_uses_session_flag(monkeypatch):
    captured = {}

    def fake_run_streaming(self, command, stdin_text, on_line):
        captured["command"] = command
        return "", False, 0

    monkeypatch.setattr(
        tui_data.ChatSession, "_run_streaming_subprocess", fake_run_streaming
    )
    _which_only(monkeypatch, "opencode", "/usr/bin/opencode")

    session = tui_data.ChatSession()
    session.session_ids["opencode"] = "oc-prior-session"
    session.send_streaming("continue please")

    command = captured["command"]
    assert command[0] == "/usr/bin/opencode"
    assert command[1] == "run"
    assert command[command.index("--session") + 1] == "oc-prior-session"
    assert command[-1] == "continue please"


def test_opencode_streaming_session_id_captured_after_stream(monkeypatch):
    def fake_run_streaming(self, command, stdin_text, on_line):
        on_line("Implemented the thing.")
        return "session id: oc-new-session", False, 0

    monkeypatch.setattr(
        tui_data.ChatSession, "_run_streaming_subprocess", fake_run_streaming
    )
    _which_only(monkeypatch, "opencode", "/usr/bin/opencode")

    session = tui_data.ChatSession()
    reply = session.send_streaming("hi")

    assert reply == "Implemented the thing."
    assert session.session_ids["opencode"] == "oc-new-session"


def test_opencode_streaming_nonzero_exit_with_no_output_is_error(monkeypatch):
    def fake_run_streaming(self, command, stdin_text, on_line):
        return "opencode blew up", False, 3

    monkeypatch.setattr(
        tui_data.ChatSession, "_run_streaming_subprocess", fake_run_streaming
    )
    _which_only(monkeypatch, "opencode", "/usr/bin/opencode")

    session = tui_data.ChatSession()
    reply = session.send_streaming("hi")

    assert "opencode exited with 3" in reply
    assert "opencode blew up" in reply
    assert session.history == []


# ── dispatch table / fallback ────────────────────────────────────────────────

def test_provider_without_streaming_impl_falls_back_to_blocking_send(monkeypatch):
    session = tui_data.ChatSession()
    session.provider = ("mystery", "/usr/bin/mystery")
    monkeypatch.setattr(session, "send", lambda message: f"blocking reply to {message}")

    seen = []
    reply = session.send_streaming("hi", on_text=lambda text: seen.append(text))

    assert reply == "blocking reply to hi"
    assert seen == ["blocking reply to hi"]
