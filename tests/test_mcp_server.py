from pathlib import Path

import pytest

from src import mcp_server as ms
from src.engine import Complexity, Engine, PersistenceManager, Phase, PhaseResult, TaskContext

EXAMPLE_POLICY_PACK = str(Path(__file__).resolve().parents[1] / "policy-pack" / "EXAMPLE")


def _write_policy_pack(policy_dir: Path, minimal: bool = False) -> None:
    policy_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "complexity.md": """# Complexity

classification_thresholds: present
skip_rules: present
""",
        "conventions.md": """# Conventions

conventions: present
brainstorming_protocol: present
""",
        "commands.md": """# Commands

```yaml
build:
  command: "echo build"
test:
  command: "echo test"
```
""",
        "review.md": """# Review

max_rounds: 5
min_coverage: 80
""",
        "escalation.md": """# Escalation

auto_fix: configured
review: configured
""",
        "skills.md": """# Skills

pattern_detection: enabled
evolution_threshold: 0.8
""",
        "task-tracking.md": """# Task Tracking

task: configured
options: configured
""",
    }
    if minimal:
        files = {"commands.md": "# Commands\n"}
    for name, content in files.items():
        (policy_dir / name).write_text(content)


@pytest.fixture
def isolated_persistence(tmp_path, monkeypatch):
    """Isolate PersistenceManager so tests don't pollute the repo's .sarathi."""
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    monkeypatch.setattr(ms, "PersistenceManager", lambda *args, **kwargs: persistence)
    return persistence


# ============================================================================
# run_task
# ============================================================================

def test_run_task_dry_run_lists_planned_phases(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    result = ms.run_task("Add auth flow", policy_pack=str(policy_dir), complexity="high", dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    phase_names = [entry["phase"] for entry in result["planned_phases"]]
    assert phase_names[0] == "Route"
    assert phase_names[-1] == "Learn"
    assert "PlanningAdvisor" in phase_names
    # high complexity should not skip PlanningAdvisor
    advisor = next(e for e in result["planned_phases"] if e["phase"] == "PlanningAdvisor")
    assert "skip" not in advisor


def test_run_task_dry_run_skips_planning_advisor_for_low_complexity(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    result = ms.run_task("Fix a typo", policy_pack=str(policy_dir), complexity="low", dry_run=True)

    assert result["ok"] is True
    advisor = next(e for e in result["planned_phases"] if e["phase"] == "PlanningAdvisor")
    assert advisor.get("skip") is True


def test_run_task_completes_with_example_policy_pack(isolated_persistence):
    result = ms.run_task("Fix a small bug in the parser", policy_pack=EXAMPLE_POLICY_PACK, complexity="low")

    assert result["ok"] is True
    assert result["blocked"] is False
    assert result["final_status"] in ("completed", "paused")
    assert result["task_id"]

    phases_by_name = {p["phase"]: p for p in result["phases"]}
    assert "Verify" in phases_by_name
    assert phases_by_name["Verify"]["outcome"] == "unverified"

    # Plan phase fails its evidence gate on this minimal task and is retried.
    assert "Plan" in phases_by_name
    assert phases_by_name["Plan"].get("gate") in ("retry", "advisory", "ok")


def test_run_task_blocks_on_preflight(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir, minimal=True)

    result = ms.run_task("Add auth flow", policy_pack=str(policy_dir), complexity="low")

    assert result["ok"] is True
    assert result["blocked"] is True
    assert result["final_status"] == "blocked_on_preflight"
    assert result["phases"] == []


def test_run_task_invalid_policy_pack_returns_error(isolated_persistence):
    result = ms.run_task("Do something", policy_pack="/no/such/policy-pack")

    assert result["ok"] is False
    assert "error" in result


def test_run_task_invalid_complexity_returns_error(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    result = ms.run_task("Do something", policy_pack=str(policy_dir), complexity="extreme")

    assert result["ok"] is False
    assert "error" in result


# ============================================================================
# task_status / list_tasks / task_log / resume_task round-trip
# ============================================================================

def test_task_status_list_tasks_and_log_round_trip(isolated_persistence):
    run_result = ms.run_task("Fix a small bug in the parser", policy_pack=EXAMPLE_POLICY_PACK, complexity="low")
    assert run_result["ok"] is True
    task_id = run_result["task_id"]

    status = ms.task_status(task_id)
    assert status["ok"] is True
    assert status["task_id"] == task_id
    assert status["description"] == "Fix a small bug in the parser"
    assert status["complexity"] == "low"
    assert isinstance(status["phases"], list) and status["phases"]

    listing = ms.list_tasks(limit=20)
    assert listing["ok"] is True
    assert task_id in listing["task_ids"]

    log = ms.task_log(task_id)
    assert log["ok"] is True
    assert log["task_id"] == task_id
    assert any(p["phase"] == "Verify" and p["outcome"] == "unverified" for p in log["phases"])


def test_task_status_nonexistent_task_returns_error(isolated_persistence):
    result = ms.task_status("does-not-exist")

    assert result["ok"] is False
    assert "error" in result
    assert "available_tasks" in result


def test_resume_task_nonexistent_task_returns_error(isolated_persistence):
    result = ms.resume_task("does-not-exist")

    assert result["ok"] is False
    assert "error" in result


def test_resume_task_already_completed(isolated_persistence):
    # Resuming an already-completed task should not error; engine.resume_task
    # short-circuits to current_phase=None when Learn has already completed.
    run_result = ms.run_task("Fix a small bug in the parser", policy_pack=EXAMPLE_POLICY_PACK, complexity="low")
    assert run_result["ok"] is True
    task_id = run_result["task_id"]

    result = ms.resume_task(task_id, policy_pack=EXAMPLE_POLICY_PACK)
    assert result["ok"] is True
    assert result["task_id"] == task_id
    assert result["final_status"] == "completed"


def test_task_log_nonexistent_task_returns_error(isolated_persistence):
    result = ms.task_log("does-not-exist")

    assert result["ok"] is False
    assert "error" in result


# ============================================================================
# approve_task
# ============================================================================

def _write_waiting_human_policy_pack(policy_dir: Path) -> None:
    policy_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": """```yaml
task: configured
options: configured
graph_execution:
  step_limit: 1
  max_retries: 1
  require_human_after_retries: true
```
""",
    }
    for name, content in files.items():
        (policy_dir / name).write_text(content)


def _run_to_waiting_human_pause(tmp_path, isolated_persistence, monkeypatch, task_id):
    policy_dir = tmp_path / "policy-pack"
    _write_waiting_human_policy_pack(policy_dir)
    monkeypatch.setenv("SARATHI_GRAPH_FAIL_NODE", "step-1")

    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = isolated_persistence
    task = TaskContext(task_id=task_id, description="Fix bug", complexity=Complexity.LOW)
    paused = engine.run_task(task)
    assert paused.phase_results[-1].evidence["human_attention_required"] is True

    monkeypatch.delenv("SARATHI_GRAPH_FAIL_NODE")
    return str(policy_dir)


def test_resume_task_blocked_pending_approval(tmp_path, isolated_persistence, monkeypatch):
    policy_dir = _run_to_waiting_human_pause(tmp_path, isolated_persistence, monkeypatch, "task-mcp-blocked")

    result = ms.resume_task("task-mcp-blocked", policy_pack=policy_dir)

    assert result["ok"] is True
    assert result["stop_reason"] == "approval_required"
    assert result["final_status"] == "awaiting_approval"

    reloaded = isolated_persistence.load_task("task-mcp-blocked")
    assert not any(pr.artifacts.get("approval") for pr in reloaded.phase_results)


def test_approve_task_approves_and_resumes(tmp_path, isolated_persistence, monkeypatch):
    policy_dir = _run_to_waiting_human_pause(tmp_path, isolated_persistence, monkeypatch, "task-mcp-approve")

    result = ms.approve_task("task-mcp-approve", note="looks safe", policy_pack=policy_dir)

    assert result["ok"] is True
    assert result["decision"] == "approved"
    assert result["task_id"] == "task-mcp-approve"

    reloaded = isolated_persistence.load_task("task-mcp-approve")
    approvals = [pr.artifacts.get("approval") for pr in reloaded.phase_results if pr.artifacts.get("approval")]
    assert approvals
    assert approvals[0]["approved"] is True
    assert approvals[0]["approved_by"] == "mcp"
    assert approvals[0]["note"] == "looks safe"


def test_approve_task_reject_leaves_task_paused(tmp_path, isolated_persistence, monkeypatch):
    policy_dir = _run_to_waiting_human_pause(tmp_path, isolated_persistence, monkeypatch, "task-mcp-reject")

    result = ms.approve_task("task-mcp-reject", note="not safe", reject=True, policy_pack=policy_dir)

    assert result["ok"] is True
    assert result["decision"] == "rejected"
    assert result["final_status"] == "rejected"

    reloaded = isolated_persistence.load_task("task-mcp-reject")
    approvals = [pr.artifacts.get("approval") for pr in reloaded.phase_results if pr.artifacts.get("approval")]
    assert approvals
    assert approvals[0]["approved"] is False

    # A rejected task stays blocked -- a bare resume must not proceed.
    resumed = ms.resume_task("task-mcp-reject", policy_pack=policy_dir)
    assert resumed["stop_reason"] == "rejected"
    assert resumed["final_status"] == "rejected"


def test_approve_task_nonexistent_task_returns_error(isolated_persistence):
    result = ms.approve_task("does-not-exist")

    assert result["ok"] is False
    assert "error" in result


def test_approve_task_non_paused_task_returns_error(isolated_persistence):
    run_result = ms.run_task("Fix a small bug in the parser", policy_pack=EXAMPLE_POLICY_PACK, complexity="low")
    assert run_result["ok"] is True
    task_id = run_result["task_id"]

    result = ms.approve_task(task_id, policy_pack=EXAMPLE_POLICY_PACK)

    assert result["ok"] is False
    assert "error" in result


# ============================================================================
# proposals
# ============================================================================

def test_list_proposals_returns_generated_proposals(isolated_persistence):
    task = TaskContext(
        task_id="task-proposal",
        description="Test task",
        complexity=Complexity.LOW,
        phase_results=[
            PhaseResult(
                phase=Phase.LEARN,
                outcome="pass",
                artifacts={
                    "learning_record": {
                        "task_id": "task-proposal",
                        "complexity": "low",
                        "generated_at": "2026-04-23T10:00:00Z",
                        "summary": "Verify failed repeatedly",
                        "lessons": [],
                        "repeated_failures": [{"phase": "Verify", "count": 2}],
                        "escalations": [],
                        "iteration_hotspots": [],
                        "phase_outcomes": [],
                    }
                },
            )
        ],
    )
    isolated_persistence.save_task(task)

    result = ms.list_proposals()

    assert result["ok"] is True
    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    assert proposal["policy_file"] == "commands.md"
    assert "id" in proposal


def test_accept_and_reject_proposal_round_trip(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    task = TaskContext(
        task_id="task-proposal",
        description="Test task",
        complexity=Complexity.LOW,
        phase_results=[
            PhaseResult(
                phase=Phase.LEARN,
                outcome="pass",
                artifacts={
                    "learning_record": {
                        "task_id": "task-proposal",
                        "complexity": "low",
                        "generated_at": "2026-04-23T10:00:00Z",
                        "summary": "Verify failed repeatedly",
                        "lessons": [],
                        "repeated_failures": [{"phase": "Verify", "count": 2}],
                        "escalations": [],
                        "iteration_hotspots": [],
                        "phase_outcomes": [],
                    }
                },
            )
        ],
    )
    isolated_persistence.save_task(task)

    proposals = ms.list_proposals()
    assert proposals["ok"] is True
    proposal_id = proposals["proposals"][0]["id"]

    accepted = ms.accept_proposal(proposal_id, policy_pack=str(policy_dir))
    assert accepted["ok"] is True
    assert accepted["decision"]["policy_file"] == "commands.md"
    assert f"id: {proposal_id}" in (policy_dir / "commands.md").read_text()


def test_reject_proposal(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    task = TaskContext(
        task_id="task-proposal",
        description="Test task",
        complexity=Complexity.LOW,
        phase_results=[
            PhaseResult(
                phase=Phase.LEARN,
                outcome="pass",
                artifacts={
                    "learning_record": {
                        "task_id": "task-proposal",
                        "complexity": "low",
                        "generated_at": "2026-04-23T10:00:00Z",
                        "summary": "Verify failed repeatedly",
                        "lessons": [],
                        "repeated_failures": [{"phase": "Verify", "count": 2}],
                        "escalations": [],
                        "iteration_hotspots": [],
                        "phase_outcomes": [],
                    }
                },
            )
        ],
    )
    isolated_persistence.save_task(task)

    proposals = ms.list_proposals()
    proposal_id = proposals["proposals"][0]["id"]

    rejected = ms.reject_proposal(proposal_id, reason="Not applicable", policy_pack=str(policy_dir))
    assert rejected["ok"] is True
    assert rejected["decision"]["status"] == "rejected"


def test_accept_proposal_not_found_returns_error(tmp_path, isolated_persistence):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    result = ms.accept_proposal("does-not-exist", policy_pack=str(policy_dir))

    assert result["ok"] is False
    assert "error" in result


# ============================================================================
# validate_policy_pack
# ============================================================================

def test_validate_policy_pack_example():
    result = ms.validate_policy_pack(EXAMPLE_POLICY_PACK)

    assert result["ok"] is True
    summary = result["summary"]
    assert summary == {"pass": 24, "drift": 0, "todo": 0, "total": 24}
    assert len(result["items"]) == summary["total"]


def test_validate_policy_pack_nonexistent_returns_error():
    result = ms.validate_policy_pack("/no/such/policy-pack")

    assert result["ok"] is False
    assert "error" in result


# ============================================================================
# create_server
# ============================================================================

def _mcp_available() -> bool:
    try:
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _mcp_available(), reason="mcp package not installed")
def test_create_server_registers_expected_tools():
    server = ms.create_server()

    tools = server._tool_manager.list_tools()
    names = {tool.name for tool in tools}

    expected = {
        "run_task",
        "task_status",
        "resume_task",
        "approve_task",
        "list_tasks",
        "task_log",
        "list_proposals",
        "accept_proposal",
        "reject_proposal",
        "validate_policy_pack",
    }
    assert expected.issubset(names)
