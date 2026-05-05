from argparse import Namespace
from pathlib import Path

from src import cli
from src.engine import Complexity, PersistenceManager, Phase, PhaseResult, TaskContext


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


def test_format_preflight_summary_blocking():
    lines = cli.format_preflight_summary(
        {
            "passed": 1,
            "warning_count": 2,
            "todo": 3,
            "blocking": True,
            "artifact_ref": "/tmp/preflight.json",
        }
    )

    assert lines[0] == "Preflight: 1 PASS, 2 WARN, 3 TODO"
    assert any("Blocking issues detected" in line for line in lines)


def test_handle_run_dry_run_prints_phases(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    args = Namespace(
        task_description="Add auth flow",
        policy_pack=str(policy_dir),
        complexity="high",
        dry_run=True,
    )

    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Running task: Add auth flow" in output
    assert "PlanningAdvisor" in output


def test_handle_run_blocks_on_preflight(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir, minimal=True)
    args = Namespace(
        task_description="Add auth flow",
        policy_pack=str(policy_dir),
        complexity="low",
        dry_run=False,
    )

    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Preflight:" in output
    assert "Blocking issues detected" in output
    assert "Executing lifecycle phases:" not in output


def test_handle_run_executes_when_preflight_passes(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    args = Namespace(
        task_description="Fix bug",
        policy_pack=str(policy_dir),
        complexity="low",
        dry_run=False,
    )

    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Preflight:" in output
    assert "Executing lifecycle phases:" in output
    assert "Task completed:" in output
    assert "Agent" in output
    assert "Marga" in output
    assert "Pravaha" in output


def test_handle_run_reports_paused_graph_execution(tmp_path, capsys, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "1")
    args = Namespace(
        task_description="Fix bug",
        policy_pack=str(policy_dir),
        complexity="low",
        dry_run=False,
    )

    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Task paused:" in output
    assert "Resume from: Build" in output


def test_handle_status_prints_summary(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-1",
        description="Test task",
        complexity=Complexity.LOW,
        preflight_validation={"passed": 2, "warning_count": 1, "todo": 0},
        task_graph_state={
            "nodes": [
                {
                    "id": "step-1",
                    "title": "A",
                    "status": "completed",
                    "depends_on": [],
                    "attempts": 1,
                    "completed_at": "2026-04-23T10:00:00Z",
                },
                {
                    "id": "step-2",
                    "title": "B",
                    "status": "failed",
                    "depends_on": ["step-1"],
                    "attempts": 1,
                    "failed_at": "2026-04-23T10:05:00Z",
                    "last_error": "boom",
                },
            ]
        },
        phase_results=[
            PhaseResult(
                phase=Phase.BUILD,
                outcome="escalate",
                artifacts={
                    "agent_role": {
                        "key": "pravaha",
                        "name": "Pravaha",
                        "purpose": "executor",
                        "description": "Execution role.",
                        "aliases": [],
                    },
                    "escalation_bundle": {
                        "reason": "Graph node step-2 failed",
                        "recommended_action": "Inspect step-2 and resume",
                        "graph_node": {"id": "step-2", "title": "B", "status": "failed"},
                        "artifact_refs": ["/tmp/evidence.json"],
                    }
                },
            )
        ],
    )
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_status(Namespace(task_id="task-1"))
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Task: task-1" in output
    assert "Preflight: 2 PASS, 1 WARN, 0 TODO" in output
    assert "Task Graph: 1 completed, 0 pending, 2 total" in output
    assert "Last Completed Node: step-1 - A (attempts: 1)" in output
    assert "Failed Node: step-2 - B (attempts: 1)" in output
    assert "Retryable Node: step-2 - B" in output
    assert "Last Agent: Pravaha" in output
    assert "Escalation: Graph node step-2 failed" in output
    assert "Evidence Ref: /tmp/evidence.json" in output
    assert "Recommended Action: Inspect step-2 and resume" in output


def test_handle_log_prints_escalation_summary(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-log",
        description="Test task",
        complexity=Complexity.LOW,
        phase_results=[
            PhaseResult(
                phase=Phase.BUILD,
                outcome="escalate",
                evidence={"human_attention_required": True},
                artifacts={
                    "agent_role": {
                        "key": "pravaha",
                        "name": "Pravaha",
                        "purpose": "executor",
                        "description": "Execution role.",
                        "aliases": [],
                    },
                    "escalation_bundle": {
                        "reason": "Graph node step-1 exhausted retry budget",
                        "recommended_action": "Fix step-1 and resume",
                        "graph_node": {"id": "step-1", "title": "A", "status": "waiting_human"},
                    }
                },
            )
        ],
    )
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_log(Namespace(task_id="task-log"))
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Agent" in output
    assert "Pravaha" in output
    assert "Escalation: Graph node step-1 exhausted retry budget" in output
    assert "Escalation Node: step-1 - A (waiting_human)" in output
    assert "Recommended Action: Fix step-1 and resume" in output


def test_handle_proposals_prints_policy_proposals(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
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
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_proposals()
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Policy Proposals: 1" in output
    assert "[" in output
    assert "Add Verify failure recovery guidance -> commands.md" in output


def test_handle_proposals_accepts_policy_proposal(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    persistence = PersistenceManager(str(tmp_path / "tasks"))
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
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_proposals(Namespace(policy_pack=str(policy_dir), accept=""))
        list_output = capsys.readouterr().out
        proposal_id = list_output.split("[", 1)[1].split("]", 1)[0]
        cli.handle_proposals(Namespace(policy_pack=str(policy_dir), accept=proposal_id[:8], reject=None, reason=None))
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Accepted proposal" in output
    assert "accepted_proposals:" in (policy_dir / "commands.md").read_text()


def test_handle_proposals_rejects_policy_proposal(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    persistence = PersistenceManager(str(tmp_path / "tasks"))
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
                        "summary": "Review escalated repeatedly",
                        "lessons": [],
                        "repeated_failures": [],
                        "escalations": [{"phase": "Review", "count": 2}],
                        "iteration_hotspots": [],
                        "phase_outcomes": [],
                    }
                },
            )
        ],
    )
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_proposals()
        list_output = capsys.readouterr().out
        proposal_id = list_output.split("[", 1)[1].split("]", 1)[0]
        cli.handle_proposals(
            Namespace(policy_pack=str(policy_dir), accept=None, reject=proposal_id, reason="Not needed")
        )
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Rejected proposal" in output
    assert list((policy_dir / ".sarathi-proposals").glob("*.json"))


def test_handle_agents_prints_role_registry(capsys):
    cli.handle_agents()

    output = capsys.readouterr().out
    assert "Sarathi Agent Roles: 10" in output
    assert "Disha (planner)" in output
    assert "Pravaha (executor)" in output
    assert "Lifecycle Phase Mapping:" in output
    assert "Route: Marga (routing)" in output
    assert "PhaseLog: Sutra (workflow spine/message bus)" in output


def test_handle_resume_executes_saved_prephase_task(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-resume",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    persistence.save_task(task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    original_discover = cli.discover_policy_pack
    cli.PersistenceManager = lambda: persistence
    cli.discover_policy_pack = lambda start_path=".": str(policy_dir)
    try:
        cli.handle_resume(Namespace(task_id="task-resume"))
    finally:
        cli.discover_policy_pack = original_discover
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert "Resumed task: task-resume" in output
    assert "Phases executed:" in output


def test_handle_resume_continues_partial_task(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-partial",
        description="Fix bug",
        complexity=Complexity.LOW,
        preflight_validation={"passed": 7, "warning_count": 0, "todo": 0, "blocking": False},
        phase_results=[
            PhaseResult(
                phase=Phase.ROUTE,
                outcome="pass",
                evidence={},
                artifacts={"routing_decision": "minimal"},
            )
        ],
    )
    persistence.save_task(task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    original_discover = cli.discover_policy_pack
    cli.PersistenceManager = lambda: persistence
    cli.discover_policy_pack = lambda start_path=".": str(policy_dir)
    try:
        cli.handle_resume(Namespace(task_id="task-partial"))
    finally:
        cli.discover_policy_pack = original_discover
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert "Resumed task: task-partial" in output
    assert "Phases executed:" in output


def test_handle_resume_reports_paused_build_task(tmp_path, capsys, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "1")

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    engine = cli.Engine(policy_pack_path=str(policy_dir))
    engine.persistence = persistence
    task = TaskContext(
        task_id="task-paused",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    paused_task = engine.run_task(task)
    persistence.save_task(paused_task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    original_discover = cli.discover_policy_pack
    cli.PersistenceManager = lambda: persistence
    cli.discover_policy_pack = lambda start_path=".": str(policy_dir)
    try:
        cli.handle_resume(Namespace(task_id="task-paused"))
    finally:
        cli.discover_policy_pack = original_discover
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert "Resumed task: task-paused" in output
    assert "Current phase: Build" in output
