"""Headless smoke tests for the terminal dashboard (src/tui.py).

Skipped automatically when the optional `textual` dependency is missing.
"""
import asyncio
import json

import pytest

textual = pytest.importorskip("textual")

from src.engine import Complexity, PersistenceManager, Phase, PhaseResult, TaskContext
from src.tui import SarathiDashboard
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
            await pilot.pause()
            tasks = app.query_one("#tasks", DataTable)
            assert tasks.row_count == 1
            assert app.selected_task_id == "t-1"
            snapshot = app.query_one("#snapshot", Static)
            assert "t-1" in str(snapshot.content)
            phases = app.query_one("#phases", DataTable)
            assert phases.row_count == 1

    asyncio.run(scenario())


def test_dashboard_opens_proposals_screen(persistence):
    async def scenario():
        app = SarathiDashboard(persistence=persistence, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.pause()
            detail = app.screen.query_one("#proposal-detail", Static)
            assert "No policy proposals" in str(detail.content)
            await pilot.press("escape")

    asyncio.run(scenario())


def test_dashboard_empty_state(tmp_path):
    async def scenario():
        manager = PersistenceManager(str(tmp_path / "empty-tasks"))
        app = SarathiDashboard(persistence=manager, refresh_interval=60.0)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.selected_task_id is None
            snapshot = app.query_one("#snapshot", Static)
            assert "No saved tasks" in str(snapshot.content)

    asyncio.run(scenario())
