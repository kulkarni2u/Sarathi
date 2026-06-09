"""Tests for the Claude CLI bridge: envelope telemetry, error propagation, timeouts."""
from __future__ import annotations

import json
import stat
from pathlib import Path

from src.runtime import DispatchRequest
from src.runtime.providers.cli_bridge import (
    _parse_claude_envelope,
    dispatch_via_cli_bridge,
)


def _request(**overrides) -> DispatchRequest:
    base = dict(
        mode="execute",
        task_id="task-claude-bridge",
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


# ── _parse_claude_envelope ───────────────────────────────────────────────────

def test_parse_claude_envelope_extracts_telemetry():
    raw = json.dumps({
        "type": "result",
        "result": "All done.",
        "is_error": False,
        "session_id": "sess-123",
        "total_cost_usd": 0.042,
        "num_turns": 3,
        "duration_ms": 5400,
        "usage": {"input_tokens": 1200, "output_tokens": 340},
    })
    envelope = _parse_claude_envelope(raw)
    assert envelope is not None
    assert envelope["message"] == "All done."
    assert envelope["is_error"] is False
    assert envelope["usage"] == {"input_tokens": 1200, "output_tokens": 340}
    assert envelope["session_id"] == "sess-123"
    assert envelope["total_cost_usd"] == 0.042


def test_parse_claude_envelope_passes_through_non_envelope_json():
    raw = json.dumps({"success": True, "outputs": {"messages": ["ok"]}})
    assert _parse_claude_envelope(raw) is None


def test_parse_claude_envelope_passes_through_plain_text():
    assert _parse_claude_envelope("plain text output") is None
    assert _parse_claude_envelope("") is None


# ── dispatch through a fake claude CLI ───────────────────────────────────────

def test_claude_envelope_usage_and_session_flow_into_response(tmp_path):
    envelope = {
        "type": "result",
        "result": "Implemented the slice.",
        "is_error": False,
        "session_id": "sess-real",
        "total_cost_usd": 0.10,
        "num_turns": 2,
        "duration_ms": 1234,
        "usage": {"input_tokens": 500, "output_tokens": 100},
    }
    path = _fake_claude(
        tmp_path,
        f"import sys; sys.stdin.read(); print({json.dumps(json.dumps(envelope))})",
    )
    response = dispatch_via_cli_bridge(
        provider="claude", path=path, workspace_root=str(tmp_path), request=_request()
    )
    assert response.success is True
    assert response.usage is not None
    assert response.usage.input_tokens == 500
    assert response.usage.output_tokens == 100
    assert response.usage.usage_source in {"reported", "mixed"}
    assert response.artifacts["claude_session_id"] == "sess-real"
    assert response.artifacts["total_cost_usd"] == 0.10


def test_claude_is_error_envelope_becomes_dispatch_failure(tmp_path):
    # is_error with exit code 0 must NOT be normalized into a fake success.
    envelope = {
        "type": "result",
        "result": "Credit balance too low.",
        "is_error": True,
        "session_id": "sess-err",
    }
    path = _fake_claude(
        tmp_path,
        f"import sys; sys.stdin.read(); print({json.dumps(json.dumps(envelope))})",
    )
    response = dispatch_via_cli_bridge(
        provider="claude", path=path, workspace_root=str(tmp_path), request=_request()
    )
    assert response.success is False
    assert "Credit balance too low." in (response.error or "")
    assert response.artifacts["claude_session_id"] == "sess-err"


def test_claude_model_and_resume_flags_from_constraints(tmp_path):
    path = _fake_claude(
        tmp_path,
        "import json, sys; sys.stdin.read(); "
        "print(json.dumps({'success': True, 'outputs': {'messages': ['ok']}, "
        "'evidence': {'argv': sys.argv[1:]}, 'artifacts': {}}))",
    )
    response = dispatch_via_cli_bridge(
        provider="claude",
        path=path,
        workspace_root=str(tmp_path),
        request=_request(constraints={"model": "claude-opus-4-8", "claude_session_id": "sess-9"}),
    )
    assert response.success is True
    argv = response.evidence["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-4-8"
    assert argv[argv.index("--resume") + 1] == "sess-9"


def test_claude_timeout_returns_structured_failure(tmp_path):
    path = _fake_claude(tmp_path, "import time; time.sleep(30)")
    response = dispatch_via_cli_bridge(
        provider="claude",
        path=path,
        workspace_root=str(tmp_path),
        request=_request(timeout_seconds=1),
    )
    assert response.success is False
    assert response.artifacts["timed_out"] is True
    assert "timed out" in (response.error or "")


def test_codex_timeout_returns_structured_failure(tmp_path):
    path = _fake_claude(tmp_path, "import time; time.sleep(30)")
    response = dispatch_via_cli_bridge(
        provider="codex",
        path=path,
        workspace_root=str(tmp_path),
        request=_request(timeout_seconds=1),
    )
    assert response.success is False
    assert response.artifacts["timed_out"] is True
