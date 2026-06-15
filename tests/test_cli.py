from argparse import Namespace
from pathlib import Path

import pytest

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
        ncp_mode="direct",
        ncp_router=False,
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
        ncp_mode="direct",
        ncp_router=False,
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
        ncp_mode="direct",
        ncp_router=False,
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
        ncp_mode="direct",
        ncp_router=False,
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
                    },
                    "dispatch_usage": {
                        "provider_id": "codex",
                        "provider_family": "codex",
                        "dispatch_id": "task-1",
                        "input_tokens": 1200,
                        "output_tokens": 600,
                        "total_tokens": 1800,
                        "estimated": False,
                        "budget_limit": 2000,
                        "budget_remaining": 200,
                        "budget_state": "near_limit",
                        "usage_source": "reported",
                    }
                },
            ),
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
    assert "Token Budget: 1.8k / 2k | remaining: 200 | budget: near_limit | usage source: reported" in output
    assert "Last Completed Node: step-1 - A (attempts: 1)" in output
    assert "Failed Node: step-2 - B (attempts: 1)" in output
    assert "Retryable Node: step-2 - B" in output
    assert "Last Agent: Pravaha" in output
    assert "Escalation: Graph node step-2 failed" in output
    assert "Evidence Ref: /tmp/evidence.json" in output
    assert "Recommended Action: Inspect step-2 and resume" in output


def test_handle_status_prints_compact_supervision_manifest(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-supervision",
        description="Supervise subtasks",
        complexity=Complexity.MEDIUM,
        task_graph_state={
            "parent_task_id": "task-supervision",
            "nodes": [
                {
                    "id": "step-1",
                    "title": "Start",
                    "status": "completed",
                    "depends_on": [],
                    "child_task_ids": ["step-2"],
                },
                {
                    "id": "step-2",
                    "title": "Waiting",
                    "status": "waiting_human",
                    "depends_on": ["step-1"],
                    "last_error": "needs user input",
                    "context_pack_summary": {
                        "objective": "Resolve waiting input",
                        "token_budget": 2200,
                        "estimated_tokens": 160,
                    },
                },
            ],
        },
    )
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_status(Namespace(task_id="task-supervision"))
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Supervision: 0 running, 0 blocked, 1 waiting_user, 0 stale, 1 done" in output
    assert "Task Manifest:" in output
    assert "step-1: Start [done]" in output
    assert "step-2: Waiting [waiting_user]" in output
    assert "parent=task-supervision" in output
    assert "needs_from=step-1" in output
    assert "ctx=Resolve waiting input" in output
    assert "budget=160/2200" in output


def test_handle_watch_once_prints_refresh_snapshot(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-watch",
        description="Watch subtasks",
        complexity=Complexity.MEDIUM,
        task_graph_state={
            "parent_task_id": "task-watch",
            "nodes": [
                {
                    "id": "step-1",
                    "title": "Root",
                    "status": "running",
                    "started_at": "2026-04-23T10:00:00Z",
                }
            ],
        },
    )
    persistence.save_task(task)

    original = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_watch(Namespace(task_id="task-watch", once=True, interval=0.01, stale_after=1))
    finally:
        if original is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original

    output = capsys.readouterr().out
    assert "Watch: task-watch" in output
    assert "Refreshed:" in output
    assert "Supervision:" in output


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


def test_handle_desktop_forwards_args(monkeypatch):
    captured = {}

    def fake_launcher():
        captured["argv"] = cli.sys.argv[:]

    monkeypatch.setattr(cli, "_desktop_launcher_main", lambda: fake_launcher)

    cli.handle_desktop(Namespace(desktop_args=["--print-config", "--service-timeout", "30"]))

    assert captured["argv"] == ["sarathi desktop", "--print-config", "--service-timeout", "30"]


def test_main_desktop_command_accepts_passthrough_flags(monkeypatch):
    captured = {}

    def fake_handle_desktop(args):
        captured["desktop_args"] = args.desktop_args

    class _FakeStdin:
        def isatty(self):
            return True

    monkeypatch.setattr(cli, "handle_desktop", fake_handle_desktop)
    monkeypatch.setattr(cli.sys, "argv", ["sarathi", "desktop", "--print-config", "--service-timeout", "30"])
    monkeypatch.setattr(cli.sys, "stdin", _FakeStdin())

    cli.main()

    assert captured["desktop_args"] == ["--print-config", "--service-timeout", "30"]


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


def test_handle_reuse_requires_running_service(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: None)

    cli.handle_reuse(Namespace(workspace=None))

    output = capsys.readouterr().out
    assert "Sarathi desktop service not running" in output


def test_service_get_json_uses_discovered_bearer_token(tmp_path):
    from tests.test_service_api import running_server

    with running_server(tmp_path / "sarathi.db", token="secret") as base_url:
        data = cli._service_get_json(base_url, "/api/health", token="secret")

    assert data == {"status": "ok"}


def test_handle_reuse_prints_workspace_kit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_read_service_discovery", lambda: {"url": "http://127.0.0.1:8765"})

    def fake_service_get_json(service_url, path, *, token=None):
        assert service_url == "http://127.0.0.1:8765"
        assert token is None
        if path == "/api/workspaces":
            return {
                "workspaces": [
                    {"id": "ws-1", "name": "Sarathi"},
                ]
            }
        if path == "/api/workspaces/ws-1/reuse-kit":
            return {
                "active_saved_view_id": "approvals-inbox",
                "templates": [
                    {
                        "id": "feature-delivery",
                        "name": "Feature delivery",
                        "summary": "Route a feature from PRD through handoff.",
                        "recommended_view_ids": ["approvals-inbox", "handoff-readiness"],
                    }
                ],
                "saved_views": [
                    {"id": "approvals-inbox", "name": "Approval inbox", "metric_label": "pending approvals"},
                ],
                "playbooks": [
                    {
                        "id": "learning-1",
                        "name": "Accepted learning 1",
                        "summary": "Reusable operator guidance from prior accepted work.",
                        "recommended_template_id": "feature-delivery",
                    }
                ],
            }
        raise AssertionError(f"Unexpected path {path}")

    monkeypatch.setattr(cli, "_service_get_json", fake_service_get_json)

    cli.handle_reuse(Namespace(workspace=None))

    output = capsys.readouterr().out
    assert "Workspace reuse kit: Sarathi" in output
    assert "Feature delivery" in output
    assert "Approval inbox" in output
    assert "Accepted learning 1" in output


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


def test_handle_resume_exits_cleanly_when_policy_pack_missing(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-missing-policy",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    persistence.save_task(task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    original_discover = cli.discover_policy_pack
    cli.PersistenceManager = lambda: persistence
    cli.discover_policy_pack = lambda start_path=".": None
    try:
        with pytest.raises(SystemExit) as error:
            cli.handle_resume(Namespace(task_id="task-missing-policy"))
    finally:
        cli.discover_policy_pack = original_discover
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert error.value.code == 1
    assert "Error: No policy pack found." in output


def test_handle_validate_reports_policy_caps_from_budget_section(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    (policy_dir / "escalation.md").write_text(
        """# Escalation

```yaml
budget:
  max_total_tokens: 200000
  max_tool_calls: 50

never_auto_approve_gates:
  - Repository action
  - Final handoff
```
"""
    )

    args = Namespace(policy_pack=str(policy_dir), verbose=False)
    cli.handle_validate(args)
    output = capsys.readouterr().out

    assert "Policy caps (server tier):" in output
    assert "cost_budget_tokens: 200000" in output
    assert "max_tool_calls: 50" in output
    assert "required_approval_gates: ['Repository action', 'Final handoff']" in output


def test_handle_validate_reports_uncapped_when_no_budget_section(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    args = Namespace(policy_pack=str(policy_dir), verbose=False)
    cli.handle_validate(args)
    output = capsys.readouterr().out

    assert "Policy caps (server tier):" in output
    assert "cost_budget_tokens: uncapped" in output
    assert "max_tool_calls: uncapped" in output
    assert "required_approval_gates: none" in output
