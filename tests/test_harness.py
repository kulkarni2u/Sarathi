"""Tests for HarnessConfig, HarnessOutcome, and related types."""
import json
import pytest
from src.task_class import TaskClass, TASK_CLASS_DEFAULTS
from src.harness import (
    AgentBinding,
    SkillBinding,
    QualitySignalDef,
    HarnessConfig,
    HarnessOutcome,
    derive_permission_mode,
    resolve_agent_binding,
)
from src.permissions import PermissionMode
from src.runtime.agent_spec import AgentSpec, ToolSpec


def test_harness_config_defaults():
    hc = HarnessConfig()
    assert hc.task_class == TaskClass.ANALYSIS
    assert hc.trust_gate_result == "PASS"
    assert hc.primary_agent.agent_id == "local"
    assert hc.requires_human_approval is False


def test_from_task_class_query():
    hc = HarnessConfig.from_task_class(TaskClass.QUERY, "task-001")
    assert hc.task_id == "task-001"
    assert hc.task_class == TaskClass.QUERY
    assert hc.context_scope == "minimal"
    assert hc.permission_scope == "read_only"
    assert hc.requires_human_approval is False
    signal_names = [s.name for s in hc.quality_signals]
    assert "relevance" in signal_names
    assert "latency" in signal_names


def test_from_task_class_mutation_infra_sets_human_approval():
    hc = HarnessConfig.from_task_class(TaskClass.MUTATION_INFRA, "task-002")
    assert hc.requires_human_approval is True
    assert hc.context_scope == "full_domain"


def test_derive_permission_mode_collapses_harness_scopes():
    assert derive_permission_mode("read_only") == PermissionMode.READ_ONLY
    assert derive_permission_mode("read_plus_idempotent") == PermissionMode.READ_ONLY
    assert derive_permission_mode("repo_write") == PermissionMode.READ_WRITE
    assert derive_permission_mode("repo_write_scoped") == PermissionMode.READ_WRITE
    assert derive_permission_mode("config_write_declared") == PermissionMode.READ_WRITE
    assert derive_permission_mode("infra_write_declared") == PermissionMode.FULL
    assert derive_permission_mode("data_write_declared") == PermissionMode.FULL
    assert derive_permission_mode("child_scope_union") == PermissionMode.FULL
    assert derive_permission_mode("harness_engine_write") == PermissionMode.FULL
    assert derive_permission_mode("ncp_store_write") == PermissionMode.FULL


def test_to_json_roundtrip():
    hc = HarnessConfig.from_task_class(TaskClass.CODEGEN_PATCH, "task-003")
    serialized = hc.to_json()
    parsed = json.loads(serialized)
    assert parsed["task_class"] == "codegen/patch"
    assert parsed["task_id"] == "task-003"
    restored = HarnessConfig.from_json(serialized)
    assert restored.task_class == TaskClass.CODEGEN_PATCH
    assert restored.task_id == "task-003"
    assert len(restored.quality_signals) == len(hc.quality_signals)


def test_from_json_reconstructs_nested_objects():
    hc = HarnessConfig.from_task_class(TaskClass.ANALYSIS, "task-004")
    hc.primary_agent = AgentBinding("claude", model="claude-sonnet-4-6", health_score=0.95)
    hc.fallback_agents = [AgentBinding("local")]
    hc.eager_skills = [SkillBinding("deploy", "/skill/deploy.md")]
    restored = HarnessConfig.from_json(hc.to_json())
    assert restored.primary_agent.agent_id == "claude"
    assert restored.primary_agent.model == "claude-sonnet-4-6"
    assert restored.primary_agent.health_score == 0.95
    assert restored.fallback_agents[0].agent_id == "local"
    assert restored.eager_skills[0].skill_name == "deploy"


def test_diff_detects_changes():
    hc1 = HarnessConfig.from_task_class(TaskClass.QUERY, "task-005")
    hc2 = HarnessConfig.from_task_class(TaskClass.ANALYSIS, "task-005")
    delta = hc1.diff(hc2)
    assert "task_class" in delta
    assert delta["task_class"]["from"] == "query"
    assert delta["task_class"]["to"] == "analysis"


def test_diff_identical_configs_is_empty():
    hc = HarnessConfig.from_task_class(TaskClass.QUERY, "task-006")
    # diff against a deep copy reconstructed via JSON
    hc2 = HarnessConfig.from_json(hc.to_json())
    # harness_id and trace_id differ, but task_class/task_id should match
    delta = hc.diff(hc2)
    assert "task_class" not in delta
    assert "task_id" not in delta


def test_harness_id_is_short():
    hc = HarnessConfig()
    assert len(hc.harness_id) == 8


def test_trace_id_is_uuid():
    import re
    hc = HarnessConfig()
    assert re.match(r"[0-9a-f-]{36}", hc.trace_id)


def test_harness_outcome_fields():
    outcome = HarnessOutcome(
        harness_id="abc12345",
        task_id="task-007",
        task_class=TaskClass.CODEGEN_PATCH,
        quality_signals={"test_pass_rate": 0.92, "blast_radius": 0.1},
        token_cost_actual=512,
        latency_ms=1200,
        human_interventions=0,
        rollback_triggered=False,
        trust_gate_result="PASS",
        agent_used="claude",
    )
    assert outcome.harness_id == "abc12345"
    assert outcome.quality_signals["test_pass_rate"] == 0.92
    assert outcome.assembler_version == "sarathi-0.2.0"


def test_ncp_enabled_propagated():
    hc = HarnessConfig.from_task_class(TaskClass.ANALYSIS, "task-008", ncp_enabled=True)
    assert hc.ncp_enabled is True
    restored = HarnessConfig.from_json(hc.to_json())
    assert restored.ncp_enabled is True


# ---------------------------------------------------------------------------
# HarnessConfig.from_agent_spec (T5.2)
# ---------------------------------------------------------------------------

def _minimal_agent_spec(**overrides) -> AgentSpec:
    defaults = dict(
        key="my-agent",
        name="My Agent",
        prompt="You are a helpful agent.",
        task_class=TaskClass.CODEGEN_PATCH,
        tools=[
            ToolSpec(
                name="read_file",
                description="Read a file",
                callable_path="os.path:basename",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            )
        ],
    )
    defaults.update(overrides)
    return AgentSpec(**defaults)


def test_from_agent_spec_without_provider_uses_task_class_defaults():
    spec = _minimal_agent_spec()
    hc = HarnessConfig.from_agent_spec(spec, "task-100")

    assert hc.task_id == "task-100"
    assert hc.task_class == TaskClass.CODEGEN_PATCH

    defaults = TASK_CLASS_DEFAULTS[TaskClass.CODEGEN_PATCH]
    expected_primary = resolve_agent_binding(defaults.agent_preference)
    assert hc.primary_agent == expected_primary

    assert hc.tool_bindings == [tool.to_artifact() for tool in spec.tools]
    assert hc.agent_spec_key == spec.key

    assert hc.context_scope == defaults.context_scope
    assert hc.permission_scope == defaults.permission_scope
    assert [s.name for s in hc.quality_signals] == defaults.quality_signals


def test_from_agent_spec_with_explicit_provider_and_model():
    spec = _minimal_agent_spec(provider="acme", model="acme-large")
    hc = HarnessConfig.from_agent_spec(spec, "task-101")

    assert hc.primary_agent == AgentBinding(agent_id="acme", model="acme-large")
    assert hc.primary_agent.health_score == 1.0


def test_from_agent_spec_to_json_roundtrip_preserves_tool_bindings_and_key():
    spec = _minimal_agent_spec()
    hc = HarnessConfig.from_agent_spec(spec, "task-102")

    restored = HarnessConfig.from_json(hc.to_json())

    assert restored.tool_bindings == hc.tool_bindings
    assert restored.agent_spec_key == hc.agent_spec_key == spec.key


def test_from_json_handles_old_format_without_new_fields():
    hc = HarnessConfig.from_task_class(TaskClass.CODEGEN_PATCH, "task-103")
    d = json.loads(hc.to_json())
    d.pop("tool_bindings", None)
    d.pop("agent_spec_key", None)

    restored = HarnessConfig.from_json(json.dumps(d))

    assert restored.tool_bindings == []
    assert restored.agent_spec_key is None
