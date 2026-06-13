"""Tests for the terminal dashboard data layer (src/tui_data.py)."""
import io
import json
import time
from pathlib import Path

import pytest

from src import tui_data
from src.engine import Complexity, PersistenceManager, Phase, PhaseResult, TaskContext


@pytest.fixture
def persistence(tmp_path):
    return PersistenceManager(str(tmp_path / "tasks"))


def _save_task(persistence, task, last_updated):
    persistence.save_task(task)
    task_file = persistence.storage_path / f"{task.task_id}.json"
    data = json.loads(task_file.read_text())
    data["last_updated"] = last_updated
    task_file.write_text(json.dumps(data))


@pytest.fixture
def seeded(persistence):
    running = TaskContext(
        task_id="t-running",
        description="Fix null pointer in user service",
        complexity=Complexity.MEDIUM,
    )
    running.current_phase = Phase.BUILD
    running.phase_results.append(
        PhaseResult(
            phase=Phase.PLAN,
            outcome="pass",
            iterations=1,
            artifacts={"agent_role": {"name": "planner"}},
        )
    )
    running.phase_results.append(
        PhaseResult(
            phase=Phase.BUILD,
            outcome="fail",
            iterations=2,
            error="tests failed",
        )
    )
    _save_task(persistence, running, "2026-06-12T10:00:00")

    done = TaskContext(
        task_id="t-done",
        description="Refactor billing module",
        complexity=Complexity.HIGH,
    )
    done.current_phase = None
    done.phase_results.append(
        PhaseResult(
            phase=Phase.LEARN,
            outcome="pass",
            artifacts={
                "learning_record": {
                    "task_id": "t-done",
                    "repeated_failures": [{"phase": "Verify", "count": 2}],
                }
            },
        )
    )
    _save_task(persistence, done, "2026-06-11T09:00:00")

    log_file = persistence.storage_path / "t-running_phases.log"
    entries = [
        {"timestamp": f"2026-06-12T10:00:0{i}", "task_id": "t-running", "phase": "Build", "status": f"iteration-{i}"}
        for i in range(5)
    ]
    log_file.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")
    return persistence


def test_task_summaries_newest_first(seeded):
    summaries = tui_data.task_summaries(seeded)

    assert [summary["task_id"] for summary in summaries] == ["t-running", "t-done"]
    running = summaries[0]
    assert running["description"] == "Fix null pointer in user service"
    assert running["current_phase"] == "Build"
    assert running["phases"] == 2
    assert running["last_outcome"] == "fail"
    assert summaries[1]["current_phase"] == "Completed"


def test_task_summaries_skips_corrupt_files(seeded):
    (seeded.storage_path / "broken.json").write_text("{not json")

    summaries = tui_data.task_summaries(seeded)

    assert [summary["task_id"] for summary in summaries] == ["t-running", "t-done"]


def test_status_snapshot_matches_status_command(seeded):
    snapshot = tui_data.status_snapshot(seeded, "t-running")

    assert "Task: t-running" in snapshot
    assert "Fix null pointer in user service" in snapshot
    assert "Current Phase: Build" in snapshot
    assert tui_data.status_snapshot(seeded, "missing") is None


def test_phase_rows_include_agent_and_error(seeded):
    rows = tui_data.phase_rows(seeded, "t-running")

    assert [row["phase"] for row in rows] == ["Plan", "Build"]
    assert rows[0]["agent"] == "planner"
    assert rows[1]["outcome"] == "fail"
    assert rows[1]["error"] == "tests failed"
    assert tui_data.phase_rows(seeded, "missing") == []


def test_phase_log_tail_limits_lines(seeded):
    tail = tui_data.phase_log_tail(seeded, "t-running", max_lines=2)

    assert len(tail) == 2
    assert json.loads(tail[-1])["status"] == "iteration-4"
    assert tui_data.phase_log_tail(seeded, "t-done") == []


def test_format_log_line():
    line = json.dumps(
        {"timestamp": "2026-06-12T10:00:00", "phase": "Build", "status": "started"}
    )
    assert tui_data.format_log_line(line) == "2026-06-12 10:00:00  Build  started"
    assert tui_data.format_log_line("plain text") == "plain text"


def test_load_proposals_from_learning_records(seeded):
    proposals = tui_data.load_proposals(seeded)

    assert proposals
    assert any("Verify" in proposal.title for proposal in proposals)


def test_decide_proposal_accept_and_reject(seeded, tmp_path):
    policy_pack = tmp_path / "policy-pack"
    policy_pack.mkdir()
    proposals = tui_data.load_proposals(seeded)
    proposal = proposals[0]

    accepted = tui_data.decide_proposal(
        proposal, accept=True, policy_pack=policy_pack
    )
    assert accepted["status"] == "accepted"
    policy_file = policy_pack / proposal.policy_file
    assert policy_file.exists()
    assert proposal.proposal_id in policy_file.read_text()

    rejected = tui_data.decide_proposal(
        proposal, accept=False, policy_pack=policy_pack, reason="not now"
    )
    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "not now"
    decision_file = policy_pack / ".sarathi-proposals" / f"{proposal.proposal_id}.json"
    assert json.loads(decision_file.read_text())["status"] == "rejected"


def test_start_task_runs_lifecycle_and_persists(persistence):
    policy_pack = Path(__file__).resolve().parents[1] / "policy-pack" / "EXAMPLE"

    result = tui_data.start_task(persistence, "Fix typo in README", policy_pack)

    assert result.phase_results
    assert (persistence.storage_path / f"{result.task_id}.json").exists()
    assert result.task_id in [s["task_id"] for s in tui_data.task_summaries(persistence)]


def test_start_task_suppresses_engine_stdout(persistence, capsys):
    policy_pack = Path(__file__).resolve().parents[1] / "policy-pack" / "EXAMPLE"

    tui_data.start_task(persistence, "Fix typo in README", policy_pack)

    captured = capsys.readouterr()
    assert "Gate FAILED" not in captured.out
    assert "Gate advisory" not in captured.out
    assert "[ncp]" not in captured.out
    assert captured.out.strip() == ""
    assert captured.err.strip() == ""


def test_start_task_with_context_includes_transcript(persistence):
    policy_pack = Path(__file__).resolve().parents[1] / "policy-pack" / "EXAMPLE"

    result = tui_data.start_task(
        persistence,
        "Fix typo in README",
        policy_pack,
        context="user: q1\nassistant: a1",
    )

    task_file = persistence.storage_path / f"{result.task_id}.json"
    data = json.loads(task_file.read_text())
    assert "Fix typo in README" in data["description"]
    assert "Context from chat conversation:" in data["description"]
    assert "q1" in data["description"]


def test_start_task_blocked_preflight_raises(persistence, tmp_path):
    sparse_pack = tmp_path / "policy-pack"
    sparse_pack.mkdir()
    (sparse_pack / "commands.md").write_text("# Commands\n")

    with pytest.raises(RuntimeError, match="Preflight blocked"):
        tui_data.start_task(persistence, "Fix typo in README", sparse_pack)


def test_resume_task_missing_raises(persistence):
    with pytest.raises(ValueError):
        tui_data.resume_task(persistence, "missing", "policy-pack")


def test_chat_session_no_provider(monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)

    session = tui_data.ChatSession()
    reply = session.send("hello")

    assert "No agent CLI" in reply


def test_chat_session_claude_session_continuity(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    calls = []

    class FakeCompleted:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return FakeCompleted(
            json.dumps(
                {
                    "type": "result",
                    "result": "hi there",
                    "session_id": "sess-1",
                    "is_error": False,
                }
            )
        )

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()

    first_reply = session.send("hello")
    assert first_reply == "hi there"
    assert "--resume" not in calls[0]

    second_reply = session.send("again")
    assert second_reply == "hi there"
    assert "--resume" in calls[1]
    assert "sess-1" in calls[1]

    assert len(session.history) == 2


def test_chat_session_history_prompt():
    session = tui_data.ChatSession()

    assert session._prompt_with_history("q2") == "q2"

    session.history = [("q1", "a1")]
    prompt = session._prompt_with_history("q2")
    assert "q1" in prompt
    assert "a1" in prompt
    assert "q2" in prompt


@pytest.mark.parametrize(
    "reply",
    [
        "claude error: boom",
        "claude error (exit 1): boom",
        "claude timed out after 180s.",
        "claude exited with 1: boom",
        "opencode exited with 1: boom",
        "codex timed out after 180s.",
        "Could not start claude: [Errno 2] No such file or directory",
    ],
)
def test_is_error_reply_true_for_cli_errors(reply):
    assert tui_data.is_error_reply(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Sure, here's the answer.",
        "(empty response)",
        tui_data.NO_PROVIDER_HELP,
        "claudette is not an error",
    ],
)
def test_is_error_reply_false_for_normal_replies(reply):
    assert not tui_data.is_error_reply(reply)


def test_chat_session_clear_resets_state():
    session = tui_data.ChatSession()
    session.history = [("q", "a")]
    session.pending_context = ["ctx"]
    session.claude_session_id = "sid-1"

    session.clear()

    assert session.history == []
    assert session.pending_context == []
    assert session.claude_session_id is None


def test_chat_session_cancel_kills_active_process():
    session = tui_data.ChatSession()

    class _Running:
        def __init__(self):
            self.killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    proc = _Running()
    session._active_proc = proc

    assert session.cancel() is True
    assert proc.killed is True
    assert session.cancelled is True


def test_chat_session_cancel_no_active_process():
    session = tui_data.ChatSession()
    assert session.cancel() is False
    assert session.cancelled is False


def test_chat_session_claude_error_envelope(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    class FakeCompleted:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(command, **kwargs):
        return FakeCompleted(
            json.dumps({"type": "result", "result": "boom", "is_error": True})
        )

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()
    reply = session.send("hello")

    assert "claude error" in reply
    assert "boom" in reply


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class _FakeStdin:
    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(data)

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(lines)
        self.stderr = None
        self.returncode = returncode
        self._waited = False

    def wait(self, timeout=None):
        self._waited = True
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass


def _fake_popen(lines, returncode=0):
    def popen(command, **kwargs):
        return _FakeProcess(lines, returncode=returncode)

    return popen


class _IterStream:
    """Stdout-like iterable: yields `lines`, optionally blocking before EOF.

    When `block_seconds` is set, iteration sleeps for that long (simulating a
    hung CLI that never writes anything) before raising StopIteration.
    """

    def __init__(self, lines, block_seconds=None):
        self._lines = list(lines)
        self._block_seconds = block_seconds

    def __iter__(self):
        if self._block_seconds is not None:
            time.sleep(self._block_seconds)
            return iter(self._lines)
        return iter(self._lines)


class FakePopen:
    """Reusable fake `subprocess.Popen` for the reader-thread streaming path."""

    def __init__(self, stdout_lines, stderr="", returncode=0, stdout_block_seconds=None):
        self._stdout_lines = stdout_lines
        self.stdin = io.StringIO()
        self.stdout = _IterStream(stdout_lines, stdout_block_seconds)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self._killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self._killed = True


def test_send_streaming_cancel_returns_cancelled(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    session = tui_data.ChatSession()

    class _CancelOnIterStdout:
        def __iter__(self):
            # Simulate the user pressing Esc mid-stream.
            session.cancel()
            return iter([])

    class _CancelFakePopen:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = _CancelOnIterStdout()
            self.stderr = io.StringIO("")
            self._alive = True

        def poll(self):
            return None if self._alive else -9

        def wait(self, timeout=None):
            return -9

        def kill(self):
            self._alive = False

    monkeypatch.setattr(
        tui_data.subprocess, "Popen", lambda *a, **k: _CancelFakePopen()
    )

    reply = session.send_streaming("hi")

    assert reply == "(cancelled)"
    assert session.cancelled is True
    assert session.history == []


def test_send_streaming_accumulates_and_returns_result(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello"}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": ", world"}]},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "result": "Hello, world!",
                "session_id": "sess-stream",
                "is_error": False,
            }
        ),
    ]
    monkeypatch.setattr(tui_data.subprocess, "Popen", _fake_popen(lines))

    session = tui_data.ChatSession()
    seen = []
    reply = session.send_streaming("hi", on_text=lambda text: seen.append(text))

    assert reply == "Hello, world!"
    assert len(seen) >= 2
    assert seen[0] != seen[-1]
    assert seen[-1].startswith("Hello")
    assert session.claude_session_id == "sess-stream"
    assert session.history == [("hi", "Hello, world!")]


def test_send_streaming_is_error_result_not_appended(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    lines = [
        json.dumps({"type": "result", "result": "boom", "is_error": True}),
    ]
    monkeypatch.setattr(tui_data.subprocess, "Popen", _fake_popen(lines))

    session = tui_data.ChatSession()
    reply = session.send_streaming("hi")

    assert reply.startswith("claude error")
    assert session.history == []


def test_send_streaming_non_claude_falls_back_to_send(monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)
    monkeypatch.setattr(tui_data.ChatSession, "send", lambda self, m: f"echo: {m}")

    session = tui_data.ChatSession()
    seen = []
    reply = session.send_streaming("hi", on_text=lambda text: seen.append(text))

    assert reply == "echo: hi"
    assert seen == ["echo: hi"]


def test_available_providers_lists_found_clis(monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("claude", "codex") else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    session = tui_data.ChatSession()
    providers = session.available_providers()

    assert providers == [("claude", "/usr/bin/claude"), ("codex", "/usr/bin/codex")]


def test_set_provider_switches_and_resets_session(monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("claude", "codex") else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    session = tui_data.ChatSession()
    session.resolve_provider()
    session.claude_session_id = "sess-1"

    assert session.set_provider("codex") is True
    assert session.provider == ("codex", "/usr/bin/codex")
    assert session.claude_session_id is None


def test_set_provider_unknown_returns_false(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    session = tui_data.ChatSession()
    session.resolve_provider()

    assert session.set_provider("opencode") is False
    assert session.provider == ("claude", "/usr/bin/claude")


def test_send_streaming_token_deltas_accumulate_without_doubling(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    full_text = "Hello, world!"

    def delta_event(text):
        return json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": text},
                },
            }
        )

    lines = [
        delta_event("Hello"),
        delta_event(", "),
        delta_event("world!"),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": full_text}]},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "result": full_text,
                "session_id": "sess-delta",
                "is_error": False,
            }
        ),
    ]
    monkeypatch.setattr(tui_data.subprocess, "Popen", _fake_popen(lines))

    session = tui_data.ChatSession()
    seen = []
    reply = session.send_streaming("hi", on_text=lambda text: seen.append(text))

    assert reply == full_text
    # Three deltas should have been delivered with progressively growing text.
    assert seen[0] == "Hello"
    assert seen[1] == "Hello, "
    assert seen[2] == "Hello, world!"
    # The assistant event re-delivers the same full text — must not double it.
    assert all(text == full_text for text in seen[2:])
    assert reply.count("Hello, world!") == 1
    assert session.history == [("hi", full_text)]


def test_send_streaming_command_includes_partial_messages_flag(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        lines = [
            json.dumps(
                {
                    "type": "result",
                    "result": "ok",
                    "session_id": "sess-flag",
                    "is_error": False,
                }
            )
        ]
        return _FakeProcess(lines)

    monkeypatch.setattr(tui_data.subprocess, "Popen", fake_popen)

    session = tui_data.ChatSession()
    session.send_streaming("hi")

    assert "--include-partial-messages" in captured["command"]


def test_send_streaming_falls_back_to_blocking_json_on_old_cli(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    # No "result" event and nothing accumulated; nonzero return code as if
    # the older CLI rejected --include-partial-messages.
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "sess-fallback"}),
    ]
    monkeypatch.setattr(tui_data.subprocess, "Popen", _fake_popen(lines, returncode=1))

    class FakeCompleted:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(command, **kwargs):
        return FakeCompleted(
            json.dumps(
                {
                    "type": "result",
                    "result": "fallback reply",
                    "session_id": "sess-fallback-run",
                    "is_error": False,
                }
            )
        )

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()
    seen = []
    reply = session.send_streaming("hi", on_text=lambda text: seen.append(text))

    assert reply == "fallback reply"
    assert seen == ["fallback reply"]
    assert session.history == [("hi", "fallback reply")]


def test_send_streaming_timeout_returns_message_when_no_output(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    created = {}

    def fake_popen(command, **kwargs):
        proc = FakePopen([], returncode=None, stdout_block_seconds=2.0)
        created["proc"] = proc
        return proc

    monkeypatch.setattr(tui_data.subprocess, "Popen", fake_popen)

    session = tui_data.ChatSession()
    session.timeout = 0.3

    start = time.monotonic()
    reply = session.send_streaming("hi")
    elapsed = time.monotonic() - start

    assert "timed out" in reply
    assert elapsed < 1.5
    assert session.history == []
    assert created["proc"]._killed is True


def test_send_streaming_surfaces_error_on_nonzero_exit_no_result(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    def fake_popen(command, **kwargs):
        return FakePopen([], stderr="bad flag", returncode=2)

    monkeypatch.setattr(tui_data.subprocess, "Popen", fake_popen)

    class FakeCompleted:
        def __init__(self, stdout, returncode, stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        # Not valid JSON, and a nonzero return code: _send_claude's fallback
        # should surface this as an error-ish string rather than a clean
        # reply.
        return FakeCompleted("not json", returncode=2, stderr="bad flag")

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()
    reply = session.send_streaming("hi")

    # _send_claude's fallback returns "claude exited with 2: bad flag" for a
    # nonzero, non-JSON completion, which does not start with the
    # error-prefixes _send_claude_streaming checks for, so it is surfaced
    # directly as the reply.
    assert "exit 2" in reply or "bad flag" in reply or "claude error" in reply
    assert session.history == []


def test_add_context_wraps_next_message_once(monkeypatch):
    def fake_which(name):
        return "/usr/bin/claude" if name == "claude" else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    captured = []

    class FakeCompleted:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(command, **kwargs):
        captured.append(kwargs.get("input"))
        return FakeCompleted(
            json.dumps(
                {
                    "type": "result",
                    "result": "ack",
                    "session_id": "sess-ctx",
                    "is_error": False,
                }
            )
        )

    monkeypatch.setattr(tui_data.subprocess, "run", fake_run)

    session = tui_data.ChatSession()
    session.add_context("Status of task t-1", "Phase: Build")

    reply = session.send("what next?")

    assert reply == "ack"
    sent = captured[0]
    assert "Context for this conversation" in sent
    assert "Phase: Build" in sent
    assert "what next?" in sent
    assert session.pending_context == []
    assert session.history[-1][0] == "what next?"

    # A second send should not re-wrap with the (now consumed) context.
    session.send("anything else?")
    second_sent = captured[1]
    assert "Context for this conversation" not in second_sent
