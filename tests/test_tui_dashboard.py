"""Headless smoke tests for the terminal dashboard (src/tui.py).

Skipped automatically when the optional `textual` dependency is missing.
"""
import asyncio
import json
import threading

import pytest

textual = pytest.importorskip("textual")

from src import tui_data
from src.engine import Complexity, PersistenceManager, Phase, PhaseResult, TaskContext
from src.tui import ChatScreen, SarathiDashboard, TasksScreen
from textual.widgets import DataTable, Input, Static


@pytest.fixture
def persistence(tmp_path):
    manager = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="t-1",
        description="Fix flaky verify step",
        complexity=Complexity.LOW,
    )
    task.current_phase = Phase.VERIFY
    task.phase_results.append(PhaseResult(phase=Phase.BUILD, outcome="pass", iterations=1))
    manager.save_task(task)
    log_file = manager.storage_path / "t-1_phases.log"
    log_file.write_text(
        json.dumps({"timestamp": "2026-06-12T10:00:00", "phase": "Build", "status": "pass"})
        + "\n"
    )
    return manager


def test_dashboard_lists_tasks_and_detail(persistence):
    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()
            tasks = app.screen.query_one("#tasks", DataTable)
            assert tasks.row_count == 1
            assert app.screen.selected_task_id == "t-1"
            snapshot = app.screen.query_one("#snapshot", Static)
            assert "t-1" in str(snapshot.content)
            phases = app.screen.query_one("#phases", DataTable)
            assert phases.row_count == 1

    asyncio.run(scenario())


def test_dashboard_opens_proposals_screen(persistence):
    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            detail = app.screen.query_one("#proposal-detail", Static)
            assert "No policy proposals" in str(detail.content)
            await pilot.press("escape")

    asyncio.run(scenario())


def test_dashboard_new_task_screen_opens_and_cancels(persistence, tmp_path, monkeypatch):
    from src.tui import NewTaskScreen

    pack = tmp_path / "policy-pack"
    pack.mkdir()
    for name in ("commands", "conventions", "review"):
        (pack / f"{name}.md").write_text(f"# {name}\n")
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda: str(pack))

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, NewTaskScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, NewTaskScreen)

    asyncio.run(scenario())


def test_dashboard_empty_state(tmp_path):
    async def scenario():
        manager = PersistenceManager(str(tmp_path / "empty-tasks"))
        app = SarathiDashboard(persistence=manager, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()
            assert app.screen.selected_task_id is None
            snapshot = app.screen.query_one("#snapshot", Static)
            assert "No saved tasks" in str(snapshot.content)

    asyncio.run(scenario())


def test_chat_is_default_mode(persistence):
    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, ChatScreen)
            assert not app.screen.has_class("-started")

    asyncio.run(scenario())


def test_chat_submit_message_gets_reply(persistence, monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)
    monkeypatch.setattr(tui_data.ChatSession, "send", lambda self, m: f"echo: {m}")

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(*"hi")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.screen.has_class("-started")
            messages = app.screen.query(".chat-msg")
            contents = [str(widget.content) for widget in messages]
            assert any("hi" in content for content in contents if "you" in content)
            assert any("echo: hi" in content for content in contents)

    asyncio.run(scenario())


def test_ctrl_t_toggles_chat_and_tasks(persistence):
    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, ChatScreen)
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert isinstance(app.screen, TasksScreen)
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert isinstance(app.screen, ChatScreen)

    asyncio.run(scenario())


def test_slash_tasks_command_switches_mode(persistence):
    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            for ch in "/tasks":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, TasksScreen)

    asyncio.run(scenario())


def test_run_command_passes_chat_context(persistence, tmp_path, monkeypatch):
    pack = tmp_path / "policy-pack"
    pack.mkdir()
    for name in ("commands", "conventions", "review"):
        (pack / f"{name}.md").write_text(f"# {name}\n")
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda: str(pack))

    captured = {}

    class DummyResult:
        task_id = "t-x"
        current_phase = None

    def fake_start_task(persistence, description, policy_pack, context=None):
        captured["description"] = description
        captured["context"] = context
        return DummyResult()

    monkeypatch.setattr(tui_data, "start_task", fake_start_task)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.session.history.append(("what is foo?", "foo is a thing"))

            for ch in "/run fix it":
                await pilot.press(ch)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())

    assert captured["description"] == "fix it"
    assert captured["context"] is not None
    assert "what is foo?" in captured["context"]
    assert "foo is a thing" in captured["context"]


def test_task_completion_posts_chat_event(persistence, tmp_path, monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)
    monkeypatch.setattr(tui_data.ChatSession, "send", lambda self, m: "ok")

    pack = tmp_path / "policy-pack"
    pack.mkdir()
    for name in ("commands", "conventions", "review"):
        (pack / f"{name}.md").write_text(f"# {name}\n")
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda: str(pack))

    class DummyResult:
        task_id = "t-done"
        current_phase = None

    monkeypatch.setattr(
        tui_data, "start_task", lambda *a, **k: DummyResult()
    )

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()

            # Start the chat thread so the chat screen is "-started".
            await pilot.press(*"hi")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            for ch in "/run something":
                await pilot.press(ch)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("Task completed" in content for content in contents)

    asyncio.run(scenario())


def test_context_command_attaches_task_status_and_reports_missing(persistence, monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()

            for ch in "/context t-1":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("t-1" in content for content in contents)
            assert app.screen.session.pending_context

            for ch in "/context missing":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("not found" in content for content in contents)

    asyncio.run(scenario())


def test_chat_input_disabled_while_reply_pending(persistence, monkeypatch):
    release = threading.Event()

    def fake_send_streaming(self, message, on_text=None):
        release.wait(timeout=5)
        return "done"

    monkeypatch.setattr(tui_data.ChatSession, "send_streaming", fake_send_streaming)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(*"hi")
            await pilot.press("enter")
            await pilot.pause()

            chat_input = app.screen.query_one("#chat-input", Input)
            assert chat_input.disabled

            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert not chat_input.disabled

    asyncio.run(scenario())


def test_chat_error_reply_is_styled(persistence, monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)
    monkeypatch.setattr(tui_data.ChatSession, "send", lambda self, m: "claude error: boom")

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(*"hi")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            messages = app.screen.query(".chat-msg.sarathi")
            assert any(widget.has_class("error") for widget in messages)
            contents = [str(widget.content) for widget in messages]
            assert any("claude error: boom" in content for content in contents)

    asyncio.run(scenario())


def test_model_command_lists_and_switches_provider(persistence, monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}" if name in ("claude", "codex") else None

    monkeypatch.setattr(tui_data.shutil, "which", fake_which)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()

            for ch in "/model":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any(
                "claude" in content and "codex" in content for content in contents
            )

            for ch in "/model codex":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("codex" in content for content in contents)
            assert app.screen.session.provider[0] == "codex"

    asyncio.run(scenario())
