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


# ── _HarnessAwareDispatcher: harness_id propagation ("declare before dispatch") ──

def test_harness_aware_dispatcher_backfills_harness_id():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.harness_id = "h-123"

    d.dispatch(_make_request())
    assert cap.last_request.harness_id == "h-123"


def test_harness_aware_dispatcher_does_not_override_explicit_harness_id():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.harness_id = "h-parent"

    d.dispatch(_make_request(harness_id="h-explicit"))
    assert cap.last_request.harness_id == "h-explicit"


def test_harness_aware_dispatcher_raises_for_child_task_dispatch_without_harness():
    """Structural enforcement: graph-node ('child_task_execution') dispatch with
    no harness_id declared anywhere must be rejected, not silently allowed."""
    from src.engine import _HarnessAwareDispatcher
    from src.dispatch import MissingHarnessError
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    # No harness_id ever assigned to the wrapper or the request.

    with pytest.raises(MissingHarnessError):
        d.dispatch(_make_request(constraints={"purpose": "child_task_execution"}))
    assert cap.last_request is None  # never reached the base dispatcher


def test_harness_aware_dispatcher_allows_child_task_dispatch_with_harness():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.harness_id = "h-graph"

    d.dispatch(_make_request(constraints={"purpose": "child_task_execution"}))
    assert cap.last_request.harness_id == "h-graph"


def test_harness_aware_dispatcher_leaves_non_child_task_dispatch_unaffected():
    """Single-task phase dispatch (no child_task_execution purpose) is never
    rejected for a missing harness_id — only graph-node dispatch is."""
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)

    d.dispatch(_make_request())  # no harness_id anywhere, no purpose tag
    assert cap.last_request is not None
    assert cap.last_request.harness_id is None


def test_engine_updates_dispatcher_harness_id_after_route():
    """After ROUTE, engine.dispatcher.harness_id matches the compiled HarnessConfig,
    so every later dispatch for this task (including graph-node dispatch in BUILD)
    can be traced back to a declared harness."""
    from src.engine import Engine, TaskContext, Complexity, _HarnessAwareDispatcher

    engine = Engine(ncp_enabled=False)
    assert isinstance(engine.dispatcher, _HarnessAwareDispatcher)
    assert engine.dispatcher.harness_id is None

    task = TaskContext(
        task_id="test-harness-id",
        description="deploy infrastructure to production",
        complexity=Complexity.MEDIUM,
    )
    engine.run_task(task)

    assert task.harness_config is not None
    assert engine.dispatcher.harness_id == task.harness_config.harness_id

    route = next(result for result in task.phase_results if result.phase.value == "Route")
    assert route.artifacts["permission_scope"] == "infra_write_declared"
    assert route.artifacts["permission_mode"] == "full"


# ── _HarnessAwareDispatcher: multi-provider session continuity ──────────────
#
# Session resume (--resume/--session/etc.) lets a provider CLI keep its own
# working context across phases instead of replaying the full context pack
# from scratch every dispatch. Originally tracked for Claude only; these
# tests cover the generalization to any provider with a registered
# session_constraint_key (codex, opencode), since BUILD's graph-node
# dispatches default to opencode, not claude.

class _SessionRespondingDispatcher:
    """Records the last request and returns canned session-id artifacts."""
    def __init__(self, session_artifacts: dict[str, str] | None = None):
        self.last_request: DispatchRequest | None = None
        self._session_artifacts = session_artifacts or {}

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.last_request = request
        return DispatchResponse(success=True, artifacts=dict(self._session_artifacts))


def test_harness_aware_dispatcher_tracks_opencode_session_id():
    from src.engine import _HarnessAwareDispatcher
    cap = _SessionRespondingDispatcher({"opencode_session_id": "oc-sess-1"})
    d = _HarnessAwareDispatcher(cap)

    d.dispatch(_make_request(constraints={"provider": "opencode"}))

    assert d.session_ids.get("opencode") == "oc-sess-1"


def test_harness_aware_dispatcher_resumes_tracked_session_for_same_provider():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.session_ids["opencode"] = "oc-sess-1"

    d.dispatch(_make_request(constraints={"provider": "opencode"}))

    assert cap.last_request.constraints["opencode_session_id"] == "oc-sess-1"


def test_harness_aware_dispatcher_does_not_leak_session_across_providers():
    """A session tracked for opencode must never be injected into a claude dispatch."""
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.session_ids["opencode"] = "oc-sess-1"

    d.dispatch(_make_request(constraints={"provider": "claude"}))

    assert "opencode_session_id" not in cap.last_request.constraints
    assert "claude_session_id" not in cap.last_request.constraints


def test_harness_aware_dispatcher_does_not_override_explicit_session_id():
    from src.engine import _HarnessAwareDispatcher
    cap = _CapturingDispatcher()
    d = _HarnessAwareDispatcher(cap)
    d.session_ids["claude"] = "tracked-sess"

    d.dispatch(_make_request(constraints={"provider": "claude", "claude_session_id": "explicit-sess"}))

    assert cap.last_request.constraints["claude_session_id"] == "explicit-sess"


def test_harness_aware_dispatcher_tracks_multiple_providers_independently():
    from src.engine import _HarnessAwareDispatcher

    d = _HarnessAwareDispatcher(_SessionRespondingDispatcher({"codex_session_id": "cx-1"}))
    d.dispatch(_make_request(constraints={"provider": "codex"}))
    assert d.session_ids == {"codex": "cx-1"}

    d._base = _SessionRespondingDispatcher({"opencode_session_id": "oc-1"})
    d.dispatch(_make_request(constraints={"provider": "opencode"}))
    assert d.session_ids == {"codex": "cx-1", "opencode": "oc-1"}


def test_harness_aware_dispatcher_reset_clears_all_session_ids():
    from src.engine import _HarnessAwareDispatcher
    d = _HarnessAwareDispatcher(_SessionRespondingDispatcher({"claude_session_id": "sess-1"}))
    d.dispatch(_make_request(constraints={"provider": "claude"}))
    assert d.session_ids

    d.reset_task_state()

    assert d.session_ids == {}
