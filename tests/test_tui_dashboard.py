"""Headless smoke tests for the terminal dashboard (src/tui.py).

Skipped automatically when the optional `textual` dependency is missing.
"""
import asyncio
import json
import threading
import time

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
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda *a, **k: str(pack))

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
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda *a, **k: str(pack))

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
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda *a, **k: str(pack))

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


def test_clear_command_resets_conversation(persistence, monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)
    monkeypatch.setattr(tui_data.ChatSession, "send", lambda self, m: "echo")

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(*"hi")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.screen.has_class("-started")
            app.screen.session.history.append(("q", "a"))

            for ch in "/clear":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            assert not app.screen.has_class("-started")
            assert app.screen.session.history == []
            assert app.screen.query(".chat-msg").__len__() == 0

    asyncio.run(scenario())


def test_context_command_truncates_large_snapshot(persistence, monkeypatch):
    from src.tui import MAX_CONTEXT_CHARS

    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)
    big = "x" * (MAX_CONTEXT_CHARS + 500)
    monkeypatch.setattr(tui_data, "status_snapshot", lambda p, t: big)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            for ch in "/context t-1":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            attached = "\n\n".join(app.screen.session.pending_context)
            assert "…(truncated)" in attached
            assert len(attached) < len(big)

            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("truncated to" in content for content in contents)

    asyncio.run(scenario())


def test_escape_cancels_pending_reply(persistence, monkeypatch):
    def fake_send_streaming(self, message, on_text=None):
        for _ in range(100):
            if self.cancelled:
                return "(cancelled)"
            time.sleep(0.02)
        return "done"

    def fake_cancel(self):
        self.cancelled = True
        return True

    monkeypatch.setattr(tui_data.ChatSession, "send_streaming", fake_send_streaming)
    monkeypatch.setattr(tui_data.ChatSession, "cancel", fake_cancel)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(*"hi")
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen._chat_pending
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert not app.screen._chat_pending
            chat_input = app.screen.query_one("#chat-input", Input)
            assert not chat_input.disabled
            messages = app.screen.query(".chat-msg.sarathi")
            contents = [str(widget.content) for widget in messages]
            assert any("cancelled" in content for content in contents)

    asyncio.run(scenario())


def test_init_command_reports_created_policy_pack(persistence, monkeypatch):
    monkeypatch.setattr(tui_data.shutil, "which", lambda name: None)

    captured = {}

    def fake_init_workspace(path, engine="markdown"):
        captured["path"] = path
        return {
            "policy_pack": f"{path}/policy-pack",
            "languages": ["Python"],
            "build_tools": [],
            "validation_passed": 24,
            "validation_total": 24,
        }

    monkeypatch.setattr(tui_data, "init_workspace", fake_init_workspace)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            for ch in "/init":
                await pilot.press(ch)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert captured["path"] == app.workspace
            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("Initialized policy pack" in content for content in contents)
            assert any("24/24" in content for content in contents)

    asyncio.run(scenario())


def test_cd_command_switches_workspace(persistence, tmp_path):
    repo = tmp_path / "other-repo"
    repo.mkdir()

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            for ch in f"/cd {repo}":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            assert app.workspace == str(repo)
            assert str(repo) in str(app.persistence.storage_path)
            assert app.screen.session.workspace_root == str(repo)
            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("Workspace set to" in content for content in contents)

    asyncio.run(scenario())


def test_cd_command_rejects_missing_directory(persistence, tmp_path):
    missing = tmp_path / "nope"

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.workspace
            for ch in f"/cd {missing}":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            assert app.workspace == original
            messages = app.screen.query(".chat-msg.system")
            contents = [str(widget.content) for widget in messages]
            assert any("Not a directory" in content for content in contents)

    asyncio.run(scenario())


def test_dashboard_init_workspace_screen_opens_and_cancels(persistence):
    from src.tui import InitWorkspaceScreen

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, InitWorkspaceScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, InitWorkspaceScreen)

    asyncio.run(scenario())


def test_launch_init_reports_success_and_refreshes(persistence, monkeypatch):
    captured = {}

    def fake_init_workspace(path, engine="markdown"):
        captured["path"] = path
        return {
            "policy_pack": f"{path}/policy-pack",
            "languages": ["Python"],
            "build_tools": [],
            "validation_passed": 24,
            "validation_total": 24,
        }

    monkeypatch.setattr(tui_data, "init_workspace", fake_init_workspace)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()

            assert app.launch_init(app.workspace) is True
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert captured["path"] == app.workspace
            assert app._init_active is False

    asyncio.run(scenario())


def test_launch_init_rejects_when_already_active(persistence, monkeypatch):
    release = threading.Event()

    def fake_init_workspace(path, engine="markdown"):
        release.wait(timeout=5)
        return {
            "policy_pack": f"{path}/policy-pack",
            "languages": [],
            "build_tools": [],
            "validation_passed": 1,
            "validation_total": 1,
        }

    monkeypatch.setattr(tui_data, "init_workspace", fake_init_workspace)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            app.switch_mode("tasks")
            await pilot.pause()

            assert app.launch_init(app.workspace) is True
            assert app._init_active is True
            assert app.launch_init(app.workspace) is False

            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app._init_active is False

    asyncio.run(scenario())


def test_launch_task_rejects_while_run_active(persistence, tmp_path, monkeypatch):
    pack = tmp_path / "policy-pack"
    pack.mkdir()
    for name in ("commands", "conventions", "review"):
        (pack / f"{name}.md").write_text(f"# {name}\n")
    monkeypatch.setattr("src.tui._discover_policy_pack", lambda *a, **k: str(pack))

    release = threading.Event()

    class DummyResult:
        task_id = "t-x"
        current_phase = None

    def fake_start_task(persistence, description, policy_pack, context=None):
        release.wait(timeout=5)
        return DummyResult()

    monkeypatch.setattr(tui_data, "start_task", fake_start_task)

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()

            assert app.launch_task("first task") is True
            assert app._run_active is True
            assert app.launch_task("second task") is False

            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app._run_active is False

    asyncio.run(scenario())


def test_cd_command_resets_agent_session(persistence, tmp_path):
    repo = tmp_path / "other-repo"
    repo.mkdir()

    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.session.claude_session_id = "sid-old"

            for ch in f"/cd {repo}":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            assert app.workspace == str(repo)
            assert app.screen.session.claude_session_id is None

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
