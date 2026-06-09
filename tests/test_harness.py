"""Tests for HarnessConfig, HarnessOutcome, and related types."""
import json
import pytest
from src.task_class import TaskClass
from src.harness import (
    AgentBinding,
    SkillBinding,
    QualitySignalDef,
    HarnessConfig,
    HarnessOutcome,
)


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
