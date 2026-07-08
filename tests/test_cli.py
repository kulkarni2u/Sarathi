from argparse import Namespace
from pathlib import Path

import pytest

from src import cli
from src import service_client
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


def test_handle_run_dry_run_unknown_agent_exits(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    args = Namespace(
        task_description="Add auth flow",
        policy_pack=str(policy_dir),
        complexity="high",
        dry_run=True,
        ncp_mode="direct",
        ncp_router=False,
        agent="does-not-exist",
        agents_dir=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_run(args)

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Error: Unknown agent 'does-not-exist'" in output
    assert "(none found)" in output


def test_handle_run_dry_run_known_agent_dispatches(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    agents_dir = policy_dir / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "patch-bot.md").write_text(
        """# Patch Bot

```yaml
name: Patch Bot
key: patch-bot
purpose: custom patch agent
description: Applies small scoped patches.
task_class: codegen/patch
tools:
  - name: apply_patch
    callable: os.path:basename
    description: Apply a unified diff
```

```yaml
prompt: |
  You fix small, scoped bugs.
```
"""
    )

    args = Namespace(
        task_description="Fix the off-by-one bug",
        policy_pack=str(policy_dir),
        complexity="low",
        dry_run=True,
        ncp_mode="direct",
        ncp_router=False,
        agent="patch-bot",
        agents_dir=None,
    )

    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Using declarative agent: Patch Bot (patch-bot)" in output
    assert "Tools: apply_patch" in output
    assert "Running task: Fix the off-by-one bug" in output


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


def test_handle_autoresearch_register_evidence_and_verdict(tmp_path, capsys):
    register_args = Namespace(
        action="register",
        store=str(tmp_path),
        hypothesis="Review packets reduce reviewer tool calls",
        prediction="Reviewer tool calls drop below 2 per review",
        tier="MINE",
        method="Mine existing review runs",
        quality_gate="Manual inspection confirms no missing spec verdicts",
        created_by="vichara",
    )

    cli.handle_autoresearch(register_args)
    register_output = capsys.readouterr().out

    assert "Registered experiment" in register_output
    experiment_id = register_output.split("Registered experiment ", 1)[1].split()[0]

    evidence_args = Namespace(
        action="evidence",
        store=str(tmp_path),
        experiment_id=experiment_id,
        summary="Reviewer tool calls fell from 6.4 to 1.0",
        uri="sarathi://runs/review-package",
        metric=["tool_calls=1.0", "baseline=6.4"],
        recorded_by="nirnaya",
    )
    cli.handle_autoresearch(evidence_args)
    evidence_output = capsys.readouterr().out
    assert "Recorded evidence" in evidence_output
    evidence_id = evidence_output.split("Recorded evidence ", 1)[1].split()[0]

    verdict_args = Namespace(
        action="verdict",
        store=str(tmp_path),
        experiment_id=experiment_id,
        verdict="confirmed",
        summary="Keep review-package handoff",
        evidence_ref=[evidence_id],
        cost_usd=0.0,
        recorded_by="sarathi",
    )
    cli.handle_autoresearch(verdict_args)
    verdict_output = capsys.readouterr().out
    assert "Recorded verdict confirmed" in verdict_output

    list_args = Namespace(action="list", store=str(tmp_path), status=None)
    cli.handle_autoresearch(list_args)
    list_output = capsys.readouterr().out
    assert "Autoresearch Experiments: 1" in list_output
    assert "Review packets reduce reviewer tool calls" in list_output
    assert "confirmed" in list_output


def test_handle_autoresearch_unknown_experiment_error_has_no_stray_quotes(tmp_path):
    evidence_args = Namespace(
        action="evidence",
        store=str(tmp_path),
        experiment_id="does-not-exist",
        summary="n/a",
        uri=None,
        metric=[],
        recorded_by="sarathi",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_autoresearch(evidence_args)

    assert str(exc_info.value) == "Unknown autoresearch experiment: does-not-exist"


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


def _run_cli_with_persistence(persistence, policy_dir, fn):
    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    original_discover = cli.discover_policy_pack
    cli.PersistenceManager = lambda: persistence
    cli.discover_policy_pack = lambda start_path=".": str(policy_dir)
    try:
        fn()
    finally:
        cli.discover_policy_pack = original_discover
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm


def test_handle_approve_approves_and_resumes_waiting_human_task(tmp_path, capsys, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    _write_waiting_human_policy_pack(policy_dir)
    monkeypatch.setenv("SARATHI_GRAPH_FAIL_NODE", "step-1")

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    engine = cli.Engine(policy_pack_path=str(policy_dir))
    engine.persistence = persistence
    task = TaskContext(task_id="task-approve", description="Fix bug", complexity=Complexity.LOW)
    paused_task = engine.run_task(task)
    assert paused_task.phase_results[-1].evidence["human_attention_required"] is True
    persistence.save_task(paused_task)
    monkeypatch.delenv("SARATHI_GRAPH_FAIL_NODE")

    _run_cli_with_persistence(
        persistence,
        policy_dir,
        lambda: cli.handle_approve(Namespace(task_id="task-approve", note="looks safe", reject=False)),
    )

    output = capsys.readouterr().out
    assert "Approved task: task-approve" in output
    assert "Resumed task: task-approve" in output

    reloaded = persistence.load_task("task-approve")
    # The approval was recorded on the phase result that triggered the pause;
    # find it among the persisted phase results.
    approvals = [pr.artifacts.get("approval") for pr in reloaded.phase_results if pr.artifacts.get("approval")]
    assert approvals, "expected an approval artifact to be persisted"
    assert approvals[0]["approved"] is True
    assert approvals[0]["note"] == "looks safe"


def test_handle_approve_rejects_waiting_human_task(tmp_path, capsys, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    _write_waiting_human_policy_pack(policy_dir)
    monkeypatch.setenv("SARATHI_GRAPH_FAIL_NODE", "step-1")

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    engine = cli.Engine(policy_pack_path=str(policy_dir))
    engine.persistence = persistence
    task = TaskContext(task_id="task-reject", description="Fix bug", complexity=Complexity.LOW)
    paused_task = engine.run_task(task)
    persistence.save_task(paused_task)

    _run_cli_with_persistence(
        persistence,
        policy_dir,
        lambda: cli.handle_approve(Namespace(task_id="task-reject", note="not safe", reject=True)),
    )

    output = capsys.readouterr().out
    assert "Rejected task: task-reject" in output
    assert "Resumed task:" not in output

    reloaded = persistence.load_task("task-reject")
    approvals = [pr.artifacts.get("approval") for pr in reloaded.phase_results if pr.artifacts.get("approval")]
    assert approvals
    assert approvals[0]["approved"] is False


def test_handle_approve_nonexistent_task_exits_nonzero(tmp_path, capsys):
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    with pytest.raises(SystemExit) as error:
        _run_cli_with_persistence(
            persistence,
            policy_dir,
            lambda: cli.handle_approve(Namespace(task_id="does-not-exist", note=None, reject=False)),
        )

    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "not found" in output


def test_handle_approve_non_paused_task_exits_nonzero(tmp_path, capsys):
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="task-not-paused",
        description="Fix bug",
        complexity=Complexity.LOW,
        phase_results=[PhaseResult(phase=Phase.ROUTE, outcome="pass")],
    )
    persistence.save_task(task)

    with pytest.raises(SystemExit) as error:
        _run_cli_with_persistence(
            persistence,
            policy_dir,
            lambda: cli.handle_approve(Namespace(task_id="task-not-paused", note=None, reject=False)),
        )

    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "Cannot approve task" in output


# ---------------------------------------------------------------------------
# Service-client unification: CLI handlers route through the local service
# when available, falling back to local persistence otherwise.
# ---------------------------------------------------------------------------

_SERVICE_DISCOVERY = {"url": "http://fake-svc:8765"}


def _make_get_fn(*, known_task_ids=None):
    """Factory: returns a _service_get mock that knows about workspaces and
    optionally known task IDs.  When a task ID is not known (or
    known_task_ids is None), returns ok-with-null-data so the caller sees
    ``get_task(…) → None`` and falls through to local persistence."""
    known = set(known_task_ids or [])

    def _fake_get(url, path, *, token=None):
        if "/api/workspaces" in path and "tasks" not in path and "events" not in path:
            return {
                "ok": True,
                "data": {
                    "workspaces": [
                        {
                            "id": "ws-1",
                            "name": "Test Workspace",
                            "root_path": str(Path.cwd()),
                        }
                    ]
                },
            }
        if "/api/workspaces/" in path and "/tasks" in path:
            return {
                "ok": True,
                "data": {
                    "tasks": [
                        {
                            "id": "svc-task-1",
                            "title": "Svc task",
                            "description": "A service task",
                            "status": "prd_pending",
                            "metadata": {"complexity": "low"},
                            "created_at": "2026-07-07T10:00:00Z",
                            "updated_at": "2026-07-07T10:00:00Z",
                        }
                    ]
                },
            }
        if "/api/tasks/" in path and "/messages" in path:
            _id = _extract_task_id(path, "/api/tasks/", "/messages")
            if _id not in known:
                return {"ok": True, "data": {}}
            return {
                "ok": True,
                "data": {
                    "messages": [
                        {"role": "user", "content": "do it", "created_at": "2026-07-07T10:00:00Z"}
                    ]
                },
            }
        if "/api/tasks/" in path and "/approvals" in path:
            _id = _extract_task_id(path, "/api/tasks/", "/approvals")
            if _id not in known:
                return {"ok": True, "data": {}}
            return {
                "ok": True,
                "data": {
                    "approval_gates": [
                        {
                            "id": "gate-1",
                            "name": "PRD/AC",
                            "status": "pending",
                        }
                    ]
                },
            }
        if "/api/events" in path:
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(path).query)
            _id = (qs.get("task_id") or [""])[0]
            if _id not in known:
                return {"ok": True, "data": {}}
            return {
                "ok": True,
                "data": {
                    "events": [
                        {
                            "id": "ev-1",
                            "event_type": "task.draft_created",
                            "created_at": "2026-07-07T10:00:00Z",
                        }
                    ]
                },
            }
        if "/api/tasks/" in path:
            _id = _extract_task_id(path, "/api/tasks/")
            if _id not in known:
                return {"ok": True, "data": {}}
            return {
                "ok": True,
                "data": {
                    "task": {
                        "id": _id,
                        "workspace_id": "ws-1",
                        "title": "Test task",
                        "description": "A test",
                        "status": "prd_pending",
                        "metadata": {"complexity": "low"},
                        "created_at": "2026-07-07T10:00:00Z",
                        "updated_at": "2026-07-07T10:00:00Z",
                    }
                },
            }
        return {"ok": True, "data": {}}

    return _fake_get


def _extract_task_id(path, prefix, suffix=""):
    """Extract a task ID from a URL path like /api/tasks/ID/messages."""
    rest = path.split(prefix, 1)[-1] if prefix in path else path
    if suffix:
        rest = rest.split(suffix, 1)[0]
    return rest.strip("/").split("/", 1)[0].strip() if rest else ""


def _service_post_task_draft(url, path, body, *, token=None):
    return {
        "ok": True,
        "data": {
            "task": {"id": "svc-task-1", "title": "Test task", "status": "prd_pending"},
            "approval_gate": {"id": "gate-1", "name": "PRD/AC", "status": "pending"},
            "messages": [
                {"role": "user", "content": body.get("prompt", "")},
                {"role": "sarathi", "content": "Draft created."},
            ],
        },
    }


def _configure_service(monkeypatch, *, known_task_ids=None):
    monkeypatch.setattr(service_client, "_read_service_discovery", lambda: _SERVICE_DISCOVERY)
    monkeypatch.setattr(service_client, "_service_get", _make_get_fn(known_task_ids=known_task_ids))
    monkeypatch.setattr(service_client, "_service_post", _service_post_task_draft)


def _clear_service(monkeypatch):
    monkeypatch.setattr(service_client, "_read_service_discovery", lambda: None)


def test_handle_run_via_service_creates_draft(monkeypatch, capsys):
    _configure_service(monkeypatch)

    args = Namespace(
        task_description="Test task",
        policy_pack=None,
        complexity="auto",
        dry_run=False,
        ncp_mode="direct",
        ncp_router=False,
        recipe=None,
        agent=None,
        agents_dir=None,
        ncp=False,
        no_ncp=False,
    )
    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Created service task draft: svc-task-1" in output
    assert "PRD/AC approval gate: gate-1" in output
    assert "awaiting PRD/AC approval" in output


def test_handle_run_via_service_skipped_when_dry_run(monkeypatch, capsys, tmp_path):
    _configure_service(monkeypatch)
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    args = Namespace(
        task_description="Test task",
        policy_pack=str(policy_dir),
        complexity="auto",
        dry_run=True,
        ncp_mode="direct",
        ncp_router=False,
        recipe=None,
        agent=None,
        agents_dir=None,
        ncp=False,
        no_ncp=False,
    )
    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Created service task draft" not in output
    assert "Route" in output


def test_handle_run_fallback_when_no_service(monkeypatch, capsys, tmp_path):
    _clear_service(monkeypatch)
    policy_dir = tmp_path / "policy-pack"
    _write_policy_pack(policy_dir)

    args = Namespace(
        task_description="Fix bug",
        policy_pack=str(policy_dir),
        complexity="low",
        dry_run=False,
        ncp_mode="direct",
        ncp_router=False,
        recipe=None,
        agent=None,
        agents_dir=None,
        ncp=False,
        no_ncp=False,
    )
    cli.handle_run(args)
    output = capsys.readouterr().out

    assert "Created service task draft" not in output
    assert "Executing lifecycle phases:" in output
    assert "Task completed:" in output


def test_handle_status_via_service(monkeypatch, capsys):
    _configure_service(monkeypatch, known_task_ids={"svc-task-1"})

    cli.handle_status(Namespace(task_id="svc-task-1"))
    output = capsys.readouterr().out

    assert "Task: svc-task-1" in output
    assert "Status: prd_pending" in output
    assert "Approval Gates:" in output
    assert "PRD/AC: pending" in output


def test_handle_status_fallback_when_task_not_in_service(monkeypatch, capsys, tmp_path):
    _configure_service(monkeypatch, known_task_ids=set())

    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="local-task-1",
        description="Local task",
        complexity=Complexity.LOW,
        preflight_validation={"passed": 2, "warning_count": 0, "todo": 0},
    )
    persistence.save_task(task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_status(Namespace(task_id="local-task-1"))
    finally:
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert "Task: local-task-1" in output
    assert "Local task" in output


def test_handle_status_fallback_when_service_unavailable(monkeypatch, capsys, tmp_path):
    _clear_service(monkeypatch)
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="local-task-2",
        description="Local task",
        complexity=Complexity.LOW,
    )
    persistence.save_task(task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_status(Namespace(task_id="local-task-2"))
    finally:
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert "Task: local-task-2" in output


def test_handle_log_via_service(monkeypatch, capsys):
    _configure_service(monkeypatch, known_task_ids={"svc-task-1"})

    cli.handle_log(Namespace(task_id="svc-task-1"))
    output = capsys.readouterr().out

    assert "Task: svc-task-1" in output
    assert "Status: prd_pending" in output
    assert "Lifecycle Events" in output


def test_handle_list_tasks_via_service(monkeypatch, capsys):
    _configure_service(monkeypatch)

    cli.handle_list_tasks()
    output = capsys.readouterr().out

    assert "Service tasks" in output
    assert "svc-task-1" in output


def test_handle_list_tasks_fallback(monkeypatch, capsys, tmp_path):
    _clear_service(monkeypatch)
    persistence = PersistenceManager(str(tmp_path / "tasks"))
    task = TaskContext(
        task_id="local-list-1",
        description="Local",
        complexity=Complexity.LOW,
    )
    persistence.save_task(task)

    original_pm = cli.PersistenceManager if hasattr(cli, "PersistenceManager") else None
    cli.PersistenceManager = lambda: persistence
    try:
        cli.handle_list_tasks()
    finally:
        if original_pm is None:
            delattr(cli, "PersistenceManager")
        else:
            cli.PersistenceManager = original_pm

    output = capsys.readouterr().out
    assert "Saved tasks" in output
    assert "local-list-1" in output
