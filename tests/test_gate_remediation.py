"""Tests for confidence gate epsilon fix, remediation, retry, and advisory behaviour."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.engine import (
    Complexity,
    Engine,
    Phase,
    PhaseResult,
    PolicyPack,
    TaskContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    engine.persistence = engine.persistence.__class__(str(tmp_path / "tasks"))
    return engine


# ---------------------------------------------------------------------------
# 1. Epsilon fix: 3-of-4 Brainstorm evidence should PASS (score == 0.80)
# ---------------------------------------------------------------------------

def test_check_gate_brainstorm_exact_threshold_passes():
    engine = Engine(ncp_enabled=False)
    evidence = {
        "alternative_approaches_considered": True,
        "risks_identified": True,
        "success_criteria_defined": True,
        "reversibility_assessed": False,  # 0.3+0.3+0.2 = 0.7999...
    }
    passed, score = engine.check_gate(Phase.BRAINSTORM, evidence)
    assert abs(score - 0.8) < 1e-6
    assert passed, f"Expected gate to pass with score={score} at threshold=0.80"


def test_check_gate_brainstorm_all_four_passes():
    engine = Engine(ncp_enabled=False)
    evidence = {
        "alternative_approaches_considered": True,
        "risks_identified": True,
        "success_criteria_defined": True,
        "reversibility_assessed": True,
    }
    passed, score = engine.check_gate(Phase.BRAINSTORM, evidence)
    assert passed
    assert abs(score - 1.0) < 1e-9


def test_check_gate_brainstorm_two_of_four_fails():
    engine = Engine(ncp_enabled=False)
    evidence = {
        "alternative_approaches_considered": True,
        "risks_identified": True,
        "success_criteria_defined": False,
        "reversibility_assessed": False,  # 0.6 < 0.80
    }
    passed, score = engine.check_gate(Phase.BRAINSTORM, evidence)
    assert not passed
    assert abs(score - 0.6) < 1e-9


def test_check_gate_plan_all_three_passes():
    engine = Engine(ncp_enabled=False)
    evidence = {
        "checkpoint_list": True,
        "dependency_map": True,
        "rollback_plan": True,
    }
    passed, score = engine.check_gate(Phase.PLAN, evidence)
    assert passed
    assert abs(score - 1.0) < 1e-9


def test_check_gate_plan_missing_one_fails():
    engine = Engine(ncp_enabled=False)
    # 0.4+0.3 = 0.7 < 0.90
    evidence = {
        "checkpoint_list": True,
        "dependency_map": True,
        "rollback_plan": False,
    }
    passed, score = engine.check_gate(Phase.PLAN, evidence)
    assert not passed


# ---------------------------------------------------------------------------
# 2. Gate failure produces remediation entries for each missing key
# ---------------------------------------------------------------------------

def test_attach_gate_result_remediation_on_failure():
    engine = Engine(ncp_enabled=False)
    result = PhaseResult(
        phase=Phase.BRAINSTORM,
        outcome="pass",
        evidence={
            "alternative_approaches_considered": True,
            "risks_identified": False,
            "success_criteria_defined": False,
            "reversibility_assessed": False,
        },
    )
    engine._attach_gate_result(result)
    gate = result.artifacts["gate_result"]
    assert gate["passed"] is False
    remediation = gate["remediation"]
    assert "risks_identified" in remediation
    assert "success_criteria_defined" in remediation
    assert "reversibility_assessed" in remediation
    # Key that is True should NOT appear in remediation
    assert "alternative_approaches_considered" not in remediation
    # Each message should be a non-empty string
    for msg in remediation.values():
        assert isinstance(msg, str) and msg


def test_attach_gate_result_no_remediation_on_pass():
    engine = Engine(ncp_enabled=False)
    result = PhaseResult(
        phase=Phase.BRAINSTORM,
        outcome="pass",
        evidence={
            "alternative_approaches_considered": True,
            "risks_identified": True,
            "success_criteria_defined": True,
            "reversibility_assessed": True,
        },
    )
    engine._attach_gate_result(result)
    gate = result.artifacts["gate_result"]
    assert gate["passed"] is True
    assert gate["remediation"] == {}


def test_attach_gate_result_plan_missing_keys():
    engine = Engine(ncp_enabled=False)
    result = PhaseResult(
        phase=Phase.PLAN,
        outcome="pass",
        evidence={
            "checkpoint_list": True,
            "dependency_map": False,
            "rollback_plan": False,
        },
    )
    engine._attach_gate_result(result)
    gate = result.artifacts["gate_result"]
    assert gate["passed"] is False
    assert "dependency_map" in gate["remediation"]
    assert "rollback_plan" in gate["remediation"]
    assert "checkpoint_list" not in gate["remediation"]


# ---------------------------------------------------------------------------
# 3. run_task with a Plan handler that fails first, passes on retry
# ---------------------------------------------------------------------------

class _PlanGateFailThenPass:
    """Stub Plan handler: first call fails the gate, second passes."""

    def __init__(self):
        self._calls = 0

    def execute(self, task: TaskContext, phase: Phase) -> PhaseResult:
        from src.engine import PhaseResult
        self._calls += 1
        if self._calls == 1:
            # First call: checkpoint_list only → score 0.4 < 0.90
            evidence = {
                "implementation_plan_created": True,
                "effort_estimated": True,
                "dependencies_identified": False,
                "timeline_defined": False,
                "checkpoint_list": True,
                "dependency_map": False,
                "rollback_plan": False,
            }
        else:
            # Second call (retry): all gate keys present
            evidence = {
                "implementation_plan_created": True,
                "effort_estimated": True,
                "dependencies_identified": True,
                "timeline_defined": True,
                "checkpoint_list": True,
                "dependency_map": True,
                "rollback_plan": True,
            }

        try:
            from src.task_graph import graph_from_plan
        except ImportError:
            from task_graph import graph_from_plan

        plan = {
            "objective": task.description,
            "steps": ["step-1"],
            "dependencies": ["dep-1"] if self._calls > 1 else [],
            "timeline": "1w",
        }
        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts={"task_graph": graph_from_plan(plan).to_artifact()},
        )


def test_run_task_plan_gate_retry_triggers_exactly_once(tmp_path: Path):
    engine = _engine(tmp_path)
    stub = _PlanGateFailThenPass()
    engine.phase_handlers[Phase.PLAN] = stub

    task = TaskContext(
        task_id="gate-retry-plan",
        description="add feature",
        complexity=Complexity.LOW,
    )
    result = engine.run_task(task)

    # Handler should have been called exactly twice (first + one retry).
    assert stub._calls == 2

    plan_results = [pr for pr in result.phase_results if pr.phase == Phase.PLAN]
    assert len(plan_results) == 1
    plan_result = plan_results[0]

    gate_retry = plan_result.artifacts.get("gate_retry")
    assert gate_retry is not None, "gate_retry artifact should be set"
    assert gate_retry["attempted"] is True
    assert gate_retry["kept"] == "retry"
    assert gate_retry["retry_score"] > gate_retry["first_score"]


def test_run_task_plan_gate_retry_completes_task(tmp_path: Path):
    engine = _engine(tmp_path)
    stub = _PlanGateFailThenPass()
    engine.phase_handlers[Phase.PLAN] = stub

    task = TaskContext(
        task_id="gate-retry-complete",
        description="add feature",
        complexity=Complexity.LOW,
    )
    result = engine.run_task(task)

    assert Phase.LEARN in result.get_completed_phases()
    assert result.current_phase is None


# ---------------------------------------------------------------------------
# 4. Double gate failure stays advisory — task still completes
# ---------------------------------------------------------------------------

class _PlanGateAlwaysFails:
    """Stub Plan handler: gate always fails (checkpoint_list only)."""

    def __init__(self):
        self.calls = 0

    def execute(self, task: TaskContext, phase: Phase) -> PhaseResult:
        from src.engine import PhaseResult
        self.calls += 1
        try:
            from src.task_graph import graph_from_plan
        except ImportError:
            from task_graph import graph_from_plan

        plan = {"objective": task.description, "steps": ["s1"], "dependencies": [], "timeline": "1w"}
        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence={
                "implementation_plan_created": True,
                "effort_estimated": True,
                "dependencies_identified": False,
                "timeline_defined": False,
                "checkpoint_list": True,
                "dependency_map": False,
                "rollback_plan": False,
            },
            artifacts={"task_graph": graph_from_plan(plan).to_artifact()},
        )


def test_run_task_double_gate_failure_is_advisory(tmp_path: Path):
    engine = _engine(tmp_path)
    stub = _PlanGateAlwaysFails()
    engine.phase_handlers[Phase.PLAN] = stub

    task = TaskContext(
        task_id="gate-advisory",
        description="add feature",
        complexity=Complexity.LOW,
    )
    result = engine.run_task(task)

    # Task must still complete — gates are advisory.
    assert Phase.LEARN in result.get_completed_phases()
    assert result.current_phase is None

    plan_results = [pr for pr in result.phase_results if pr.phase == Phase.PLAN]
    assert len(plan_results) == 1
    plan_result = plan_results[0]

    gate = plan_result.artifacts.get("gate_result", {})
    assert gate.get("passed") is False

    gate_retry = plan_result.artifacts.get("gate_retry", {})
    assert gate_retry.get("attempted") is True
    # Both attempts failed, so "kept" is whichever had higher score (both equal here).
    assert gate_retry["first_score"] == gate_retry["retry_score"]
    # Handler called exactly twice (first + one retry).
    assert stub.calls == 2


# ---------------------------------------------------------------------------
# 5. No extra retry for phases outside _GATE_RETRY_PHASES
# ---------------------------------------------------------------------------

class _RouteCallCounter:
    """Counts execute() calls on the ROUTE phase."""

    def __init__(self, real_handler):
        self._real = real_handler
        self.calls = 0

    def execute(self, task: TaskContext, phase: Phase) -> PhaseResult:
        self.calls += 1
        return self._real.execute(task, phase)


def test_route_phase_not_retried(tmp_path: Path):
    engine = _engine(tmp_path)
    counter = _RouteCallCounter(engine.phase_handlers[Phase.ROUTE])
    engine.phase_handlers[Phase.ROUTE] = counter

    task = TaskContext(
        task_id="no-retry-route",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine.run_task(task)

    assert counter.calls == 1, "ROUTE should not be retried by gate logic"
