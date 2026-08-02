"""Tests for LOW-complexity BRAINSTORM/PLAN skipping the model dispatch.

Both handlers already had a deterministic local fallback (used previously
only when a dispatch failed); LOW-complexity tasks now go straight to that
fallback instead of spending a model call to reach a fixed template.
"""
from __future__ import annotations

from src.engine import Complexity, Phase
from src.phases.brainstorm import BrainstormHandler
from src.phases.plan import PlanHandler
from src.runtime.contracts import DispatchRequest, DispatchResponse


class _CapturingDispatcher:
    def __init__(self, response: DispatchResponse | None = None):
        self.last_request: DispatchRequest | None = None
        self.calls = 0
        self._response = response or DispatchResponse(success=True, outputs={}, evidence={})

    def dispatch(self, request: DispatchRequest) -> DispatchResponse:
        self.calls += 1
        self.last_request = request
        return self._response


def _task(complexity: Complexity, *, phase_results=None):
    return type(
        "Task",
        (),
        {
            "task_id": "task-1",
            "description": "Fix the typo in the README",
            "complexity": complexity,
            "phase_results": phase_results or [],
            "gate_retry_hint": None,
        },
    )()


# ── BrainstormHandler ────────────────────────────────────────────────────

def test_brainstorm_skips_dispatch_for_low_complexity():
    dispatcher = _CapturingDispatcher()
    handler = BrainstormHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.LOW), Phase.BRAINSTORM)

    assert dispatcher.calls == 0
    assert result.evidence["dispatch_skipped_reason"] == "low_complexity"
    assert len(result.artifacts["approaches"]) >= 3
    assert result.outcome == "pass"


def test_brainstorm_dispatches_for_medium_complexity():
    dispatcher = _CapturingDispatcher(
        DispatchResponse(
            success=True,
            outputs={"approaches": ["a"], "risks": ["r"], "success_criteria": ["s"]},
            evidence={},
        )
    )
    handler = BrainstormHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.MEDIUM), Phase.BRAINSTORM)

    assert dispatcher.calls == 1
    assert result.evidence["dispatch_skipped_reason"] is None


def test_brainstorm_dispatches_for_high_complexity():
    dispatcher = _CapturingDispatcher(
        DispatchResponse(
            success=True,
            outputs={"approaches": ["a"], "risks": ["r"], "success_criteria": ["s"]},
            evidence={},
        )
    )
    handler = BrainstormHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.HIGH), Phase.BRAINSTORM)

    assert dispatcher.calls == 1
    assert result.evidence["dispatch_skipped_reason"] is None


def test_brainstorm_low_complexity_fallback_still_produces_valid_evidence():
    dispatcher = _CapturingDispatcher()
    handler = BrainstormHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.LOW), Phase.BRAINSTORM)

    assert result.evidence["alternative_approaches_considered"] is True
    assert result.evidence["risks_identified"] is True
    assert result.evidence["success_criteria_defined"] is True


# ── PlanHandler ──────────────────────────────────────────────────────────

def test_plan_skips_dispatch_for_low_complexity():
    dispatcher = _CapturingDispatcher()
    handler = PlanHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.LOW), Phase.PLAN)

    assert dispatcher.calls == 0
    assert result.evidence["dispatch_skipped_reason"] == "low_complexity"
    assert len(result.artifacts["implementation_plan"]["steps"]) > 0


def test_plan_dispatches_for_medium_complexity():
    dispatcher = _CapturingDispatcher(
        DispatchResponse(
            success=True,
            outputs={
                "implementation_plan": {"steps": ["s1"], "dependencies": []},
                "workflow_graph": {},
                "effort_estimate": 2,
            },
            evidence={},
        )
    )
    handler = PlanHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.MEDIUM), Phase.PLAN)

    assert dispatcher.calls == 1
    assert result.evidence["dispatch_skipped_reason"] is None


def test_plan_low_complexity_fallback_still_produces_valid_plan():
    dispatcher = _CapturingDispatcher()
    handler = PlanHandler(policy_pack=None, dispatcher=dispatcher)

    result = handler.execute(_task(Complexity.LOW), Phase.PLAN)

    plan = result.artifacts["implementation_plan"]
    assert plan["objective"] == "Fix the typo in the README"
    assert result.artifacts["effort_estimate"] > 0
