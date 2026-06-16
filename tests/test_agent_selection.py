"""Tests for Gap 1: agent selection via resolve_agent_binding and _HarnessAwareDispatcher."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from src.harness import AgentBinding, HarnessConfig, resolve_agent_binding
from src.task_class import TaskClass
from src.runtime.contracts import DispatchRequest, DispatchResponse


# ── resolve_agent_binding ─────────────────────────────────────────────────────

def test_fastest_resolves_to_local():
    binding = resolve_agent_binding("fastest")
    assert binding.agent_id == "local"


def test_balanced_resolves_to_local():
    binding = resolve_agent_binding("balanced")
    assert binding.agent_id == "local"


def test_highest_capability_resolves_to_claude():
    binding = resolve_agent_binding("highest_capability")
    assert binding.agent_id == "claude"


def test_sarathi_native_resolves_to_local():
    binding = resolve_agent_binding("sarathi_native")
    assert binding.agent_id == "local"


def test_unknown_preference_defaults_to_local():
    binding = resolve_agent_binding("unknown_pref")
    assert binding.agent_id == "local"


def test_available_providers_fallback_when_preferred_absent():
    # highest_capability wants "claude" but only "local" available
    binding = resolve_agent_binding("highest_capability", available_providers=["local"])
    assert binding.agent_id == "local"


def test_available_providers_satisfied_when_present():
    binding = resolve_agent_binding("highest_capability", available_providers=["local", "claude"])
    assert binding.agent_id == "claude"


def test_returns_agent_binding_instance():
    result = resolve_agent_binding("fastest")
    assert isinstance(result, AgentBinding)


# ── from_task_class sets primary_agent ────────────────────────────────────────

def test_query_task_class_gets_local_agent():
    hc = HarnessConfig.from_task_class(TaskClass.QUERY, "t1")
    assert hc.primary_agent.agent_id == "local"


def test_codegen_patch_gets_local_agent():
    hc = HarnessConfig.from_task_class(TaskClass.CODEGEN_PATCH, "t2")
    assert hc.primary_agent.agent_id == "local"


def test_mutation_infra_gets_claude_agent():
    hc = HarnessConfig.from_task_class(TaskClass.MUTATION_INFRA, "t3")
    assert hc.primary_agent.agent_id == "claude"


def test_codegen_greenfield_gets_claude_agent():
    hc = HarnessConfig.from_task_class(TaskClass.CODEGEN_GREENFIELD, "t4")
    assert hc.primary_agent.agent_id == "claude"


def test_evolution_harness_gets_claude_agent():
    hc = HarnessConfig.from_task_class(TaskClass.EVOLUTION_HARNESS, "t5")
    assert hc.primary_agent.agent_id == "claude"


def test_primary_agent_survives_json_roundtrip():
    hc = HarnessConfig.from_task_class(TaskClass.MUTATION_INFRA, "t6")
    restored = HarnessConfig.from_json(hc.to_json())
    assert restored.primary_agent.agent_id == "claude"


# ── _HarnessAwareDispatcher ───────────────────────────────────────────────────

class _CapturingDispatcher:
    """Records the last DispatchRequest it received."""
    def __init__(self):
        self.last_request: DispatchRequest | None = None

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.last_request = request
        return DispatchResponse(success=True, artifacts={"provider": "captured"})


def _make_request(**overrides) -> DispatchRequest:
    defaults = dict(mode="execute", task_id="t", phase="Build", prompt="p")
    defaults.update(overrides)
    return DispatchRequest(**defaults)


def test_harness_aware_dispatcher_injects_preferred_agent():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.preferred_agent = "claude"

    d.dispatch(_make_request())
    assert cap.last_request.constraints.get("provider") == "claude"


def test_harness_aware_dispatcher_injects_permission_mode():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.preferred_permission_mode = "read_write"

    d.dispatch(_make_request())
    assert cap.last_request.constraints.get("permission_mode") == "read_write"


def test_harness_aware_dispatcher_does_not_override_explicit_permission_mode():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.preferred_permission_mode = "read_write"

    d.dispatch(_make_request(constraints={"permission_mode": "read_only"}))
    assert cap.last_request.constraints["permission_mode"] == "read_only"


def test_harness_aware_dispatcher_does_not_override_explicit_provider():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.preferred_agent = "claude"

    d.dispatch(_make_request(constraints={"provider": "opencode"}))
    assert cap.last_request.constraints["provider"] == "opencode"


def test_harness_aware_dispatcher_passthrough_when_no_preference():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    # preferred_agent is None by default

    d.dispatch(_make_request())
    assert "provider" not in cap.last_request.constraints


def test_harness_aware_dispatcher_delegates_non_dispatch_attrs():
    from src.engine import _HarnessAwareDispatcher

    class FakeBase:
        some_attr = 42
        def dispatch(self, req):
            return DispatchResponse(success=True)

    d = _HarnessAwareDispatcher(FakeBase())
    assert d.some_attr == 42


def test_engine_updates_dispatcher_preferred_agent_after_route():
    """After ROUTE phase, engine.dispatcher.preferred_agent reflects the resolved agent."""
    from src.engine import Engine
    engine = Engine(ncp_enabled=False)
    # Verify the dispatcher is wrapped
    from src.engine import _HarnessAwareDispatcher
    assert isinstance(engine.dispatcher, _HarnessAwareDispatcher)
    assert engine.dispatcher.preferred_agent is None  # not set yet

    from src.engine import TaskContext, Complexity
    task = TaskContext(
        task_id="test-agent",
        description="deploy infrastructure to production",
        complexity=Complexity.MEDIUM,
    )
    engine.run_task(task)
    # MUTATION_INFRA → highest_capability → claude
    assert engine.dispatcher.preferred_agent == "claude"
    assert engine.dispatcher.preferred_permission_mode == "full"

    route = next(result for result in task.phase_results if result.phase.value == "Route")
    assert route.artifacts["permission_scope"] == "infra_write_declared"
    assert route.artifacts["permission_mode"] == "full"
