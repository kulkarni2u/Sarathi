"""Headless smoke tests for the terminal dashboard (src/tui.py).

Skipped automatically when the optional `textual` dependency is missing.
"""
import asyncio
import json

import pytest

textual = pytest.importorskip("textual")

from src import tui_data
from src.engine import Complexity, PersistenceManager, Phase, PhaseResult, TaskContext
from src.tui import ChatScreen, SarathiDashboard, TasksScreen
from textual.widgets import DataTable, Static


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
