"""Engine-level test for declarative user agents (T5.2).

Verifies that when ``TaskContext.agent_spec`` is set, RouteHandler.execute
builds a HarnessConfig via HarnessConfig.from_agent_spec, and that the
agent-spec key + tool bindings flow through to evidence/artifacts (so the
existing measure_outcome/quality_signals machinery picks them up once the
run is measured).
"""
from __future__ import annotations

from pathlib import Path

from src.engine import Engine, Phase, PersistenceManager, TaskContext
from src.runtime.agent_spec import AgentSpec, ToolSpec
from src.task_class import TaskClass


def _minimal_policy_dir(tmp_path: Path) -> Path:
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "complexity.md").write_text("classification_thresholds: present\nskip_rules: present\n")
    (policy_dir / "conventions.md").write_text("conventions: present\nbrainstorming_protocol: present\n")
    (policy_dir / "commands.md").write_text("# Commands\n")
    (policy_dir / "review.md").write_text("max_rounds: 5\nmin_coverage: 80\n")
    (policy_dir / "escalation.md").write_text("auto_fix: configured\nreview: configured\n")
    (policy_dir / "skills.md").write_text("pattern_detection: enabled\nevolution_threshold: 0.8\n")
    (policy_dir / "task-tracking.md").write_text("task: configured\noptions: configured\n")
    return policy_dir


def _engine(tmp_path: Path) -> Engine:
    engine = Engine(policy_pack_path=str(_minimal_policy_dir(tmp_path)), ncp_enabled=False)
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))
    return engine


def _agent_spec() -> AgentSpec:
    return AgentSpec(
        key="patch-bot",
        name="Patch Bot",
        prompt="You fix small, scoped bugs.",
        purpose="custom patch agent",
        description="A declarative agent that applies small patches.",
        task_class=TaskClass.CODEGEN_PATCH,
        tools=[
            ToolSpec(
                name="apply_patch",
                description="Apply a unified diff to the workspace",
                callable_path="os.path:basename",
                parameters={
                    "type": "object",
                    "properties": {"diff": {"type": "string"}},
                    "required": ["diff"],
                },
            )
        ],
    )


def test_route_handler_uses_agent_spec_for_harness_config(tmp_path: Path):
    engine = _engine(tmp_path)
    agent_spec = _agent_spec()

    task = TaskContext(
        task_id=engine.generate_task_id("apply a small patch"),
        description="apply a small patch to fix the bug",
    )
    task.agent_spec = agent_spec

    result = engine.phase_handlers[Phase.ROUTE].execute(task, Phase.ROUTE)

    assert result.outcome == "pass"
    assert result.artifacts["agent_spec_key"] == agent_spec.key
    assert result.evidence["agent_spec_key"] == agent_spec.key

    harness_config = result.artifacts["harness_config"]
    assert harness_config["task_class"] == agent_spec.task_class.value
    assert harness_config["agent_spec_key"] == agent_spec.key
    assert harness_config["tool_bindings"] == [tool.to_artifact() for tool in agent_spec.tools]


def test_route_handler_without_agent_spec_has_no_agent_spec_key(tmp_path: Path):
    engine = _engine(tmp_path)

    task = TaskContext(
        task_id=engine.generate_task_id("analyze this code"),
        description="analyze the codebase and report findings",
    )

    result = engine.phase_handlers[Phase.ROUTE].execute(task, Phase.ROUTE)

    assert "agent_spec_key" not in result.artifacts
    assert "agent_spec_key" not in result.evidence
    assert result.artifacts["harness_config"].get("agent_spec_key") is None
