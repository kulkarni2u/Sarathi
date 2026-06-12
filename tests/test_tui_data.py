"""Tests for the terminal dashboard data layer (src/tui_data.py)."""
import json
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


def test_start_task_blocked_preflight_raises(persistence, tmp_path):
    sparse_pack = tmp_path / "policy-pack"
    sparse_pack.mkdir()
    (sparse_pack / "commands.md").write_text("# Commands\n")

    with pytest.raises(RuntimeError, match="Preflight blocked"):
        tui_data.start_task(persistence, "Fix typo in README", sparse_pack)


def test_resume_task_missing_raises(persistence):
    with pytest.raises(ValueError):
        tui_data.resume_task(persistence, "missing", "policy-pack")
