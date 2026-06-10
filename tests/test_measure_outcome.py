"""Tests for harness.measure_outcome — quality signal extraction from phase_results."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from src.task_class import TaskClass
from src.harness import (
    AgentBinding,
    HarnessConfig,
    HarnessOutcome,
    QualitySignalDef,
    measure_outcome,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _phase(name: str, outcome: str = "pass", artifacts: dict | None = None, evidence: dict | None = None):
    """Build a minimal PhaseResult-like object."""
    return SimpleNamespace(
        phase=SimpleNamespace(value=name),
        outcome=outcome,
        iterations=0,
        artifacts=artifacts or {},
        evidence=evidence or {},
    )


def _task(phase_results: list, task_id: str = "task-test") -> SimpleNamespace:
    return SimpleNamespace(task_id=task_id, phase_results=phase_results)


def _harness(task_class: TaskClass = TaskClass.CODEGEN_PATCH) -> HarnessConfig:
    return HarnessConfig.from_task_class(task_class, "task-test")


def _with_usage(total_tokens: int) -> dict[str, Any]:
    return {"dispatch_usage": {"total_tokens": total_tokens, "provider_id": "local"}}


# ── test_pass_rate ────────────────────────────────────────────────────────────

def test_test_pass_rate_from_command_succeeded_true():
    verify = _phase("Verify", artifacts={
        "verification_summary": {"command_succeeded": True, "coverage": 50.0},
    })
    outcome = measure_outcome(_task([verify]), _harness(TaskClass.CODEGEN_PATCH))
    assert outcome.quality_signals["test_pass_rate"] == 1.0


def test_test_pass_rate_from_command_succeeded_false():
    verify = _phase("Verify", artifacts={
        "verification_summary": {"command_succeeded": False, "coverage": 30.0},
    })
    outcome = measure_outcome(_task([verify]), _harness(TaskClass.CODEGEN_PATCH))
    assert outcome.quality_signals["test_pass_rate"] == 0.0


def test_test_pass_rate_absent_when_no_command_ran():
    # Coverage alone is not evidence that tests ran — no proxy, no fabrication.
    verify = _phase("Verify", artifacts={
        "verification_summary": {"coverage": 92.0},
    })
    outcome = measure_outcome(_task([verify]), _harness(TaskClass.CODEGEN_PATCH))
    assert "test_pass_rate" not in outcome.quality_signals
    assert outcome.signal_provenance["test_pass_rate"] == "missing"


def test_test_pass_rate_absent_when_verify_never_ran():
    outcome = measure_outcome(_task([]), _harness(TaskClass.CODEGEN_PATCH))
    assert "test_pass_rate" not in outcome.quality_signals
    assert outcome.signal_provenance["test_pass_rate"] == "missing"


def test_measured_signals_marked_in_provenance():
    verify = _phase("Verify", artifacts={
        "verification_summary": {"command_succeeded": True},
    })
    outcome = measure_outcome(_task([verify]), _harness(TaskClass.CODEGEN_PATCH))
    assert outcome.quality_signals["test_pass_rate"] == 1.0
    assert outcome.signal_provenance["test_pass_rate"] == "measured"


def test_verify_summary_also_readable_from_nested_results():
    verify = _phase("Verify", artifacts={
        "verification_results": {
            "summary": {"command_succeeded": True, "coverage": 80.0},
        },
    })
    outcome = measure_outcome(_task([verify]), _harness(TaskClass.CODEGEN_PATCH))
    assert outcome.quality_signals["test_pass_rate"] == 1.0


# ── blast_radius ─────────────────────────────────────────────────────────────

def test_blast_radius_from_review_score():
    review = _phase("Review", artifacts={
        "review_verdict": {"score": 0.9, "outcome": "pass"},
    })
    outcome = measure_outcome(_task([review]), _harness(TaskClass.CODEGEN_PATCH))
    assert abs(outcome.quality_signals["blast_radius"] - 0.1) < 0.01


def test_blast_radius_high_when_review_score_low():
    review = _phase("Review", artifacts={
        "review_verdict": {"score": 0.3, "outcome": "escalate"},
    })
    outcome = measure_outcome(_task([review]), _harness(TaskClass.CODEGEN_PATCH))
    assert outcome.quality_signals["blast_radius"] == pytest.approx(0.7, abs=0.01)


def test_blast_radius_derived_from_review_outcome_without_score():
    review = _phase("Review", artifacts={"review_verdict": {"outcome": "pass"}})
    outcome = measure_outcome(_task([review]), _harness(TaskClass.CODEGEN_PATCH))
    assert outcome.quality_signals["blast_radius"] == 0.1
    assert outcome.signal_provenance["blast_radius"] == "derived"


def test_blast_radius_absent_when_review_never_ran():
    outcome = measure_outcome(_task([]), _harness(TaskClass.CODEGEN_PATCH))
    assert "blast_radius" not in outcome.quality_signals
    assert outcome.signal_provenance["blast_radius"] == "missing"


# ── accuracy / relevance ─────────────────────────────────────────────────────

def test_accuracy_from_review_score():
    review = _phase("Review", artifacts={
        "review_verdict": {"score": 0.85, "outcome": "pass"},
    })
    hc = _harness(TaskClass.ANALYSIS)
    outcome = measure_outcome(_task([review]), hc)
    assert outcome.quality_signals["accuracy"] == pytest.approx(0.85)


def test_relevance_from_review_score():
    review = _phase("Review", artifacts={
        "review_verdict": {"score": 0.75, "outcome": "pass"},
    })
    hc = _harness(TaskClass.QUERY)
    outcome = measure_outcome(_task([review]), hc)
    assert outcome.quality_signals["relevance"] == pytest.approx(0.75)


# ── token_cost_actual ─────────────────────────────────────────────────────────

def test_token_cost_sums_across_phases():
    phases = [
        _phase("Brainstorm", artifacts=_with_usage(300)),
        _phase("Plan",       artifacts=_with_usage(150)),
        _phase("Build",      artifacts=_with_usage(800)),
    ]
    outcome = measure_outcome(_task(phases), _harness())
    assert outcome.token_cost_actual == 1250


def test_token_cost_zero_when_no_dispatch():
    outcome = measure_outcome(_task([_phase("Route")]), _harness())
    assert outcome.token_cost_actual == 0


def test_token_cost_as_quality_signal_for_greenfield():
    phases = [_phase("Build", artifacts=_with_usage(2000))]
    hc = _harness(TaskClass.CODEGEN_GREENFIELD)
    outcome = measure_outcome(_task(phases), hc)
    assert outcome.quality_signals["token_cost"] == 2000.0


# ── latency_ms ───────────────────────────────────────────────────────────────

def test_latency_ms_is_positive():
    outcome = measure_outcome(_task([]), _harness())
    assert outcome.latency_ms >= 0


def test_latency_ms_increases_with_time():
    from datetime import datetime, timedelta
    hc = _harness()
    # Backdate assembled_at by 2 seconds
    hc.assembled_at = (datetime.utcnow() - timedelta(seconds=2)).isoformat()
    outcome = measure_outcome(_task([]), hc)
    assert outcome.latency_ms >= 1500  # at least 1.5s


# ── rollback_triggered ───────────────────────────────────────────────────────

def test_rollback_triggered_from_artifact():
    phases = [_phase("Build", artifacts={"rollback_triggered": True})]
    hc = _harness(TaskClass.MUTATION_INFRA)
    outcome = measure_outcome(_task(phases), hc)
    assert outcome.rollback_triggered is True
    assert outcome.quality_signals["rollback_triggered"] == 1.0


def test_rollback_triggered_from_recovery_actions():
    phases = [_phase("Verify", artifacts={"recovery_actions": [{"type": "retry"}]})]
    hc = _harness(TaskClass.MUTATION_INFRA)
    outcome = measure_outcome(_task(phases), hc)
    assert outcome.rollback_triggered is True


def test_no_rollback_when_clean():
    hc = _harness(TaskClass.MUTATION_INFRA)
    outcome = measure_outcome(_task([_phase("Build")]), hc)
    assert outcome.rollback_triggered is False
    assert outcome.quality_signals["rollback_triggered"] == 0.0


# ── success_rate ─────────────────────────────────────────────────────────────

def test_success_rate_all_pass():
    phases = [_phase("Build"), _phase("Verify"), _phase("Review")]
    hc = _harness(TaskClass.MUTATION_INFRA)
    outcome = measure_outcome(_task(phases), hc)
    assert outcome.quality_signals["success_rate"] == 1.0


def test_success_rate_with_failure():
    phases = [_phase("Build"), _phase("Verify", outcome="fail")]
    hc = _harness(TaskClass.MUTATION_INFRA)
    outcome = measure_outcome(_task(phases), hc)
    assert outcome.quality_signals["success_rate"] == 0.0


# ── agent_used ───────────────────────────────────────────────────────────────

def test_agent_used_from_build_dispatch():
    build = _phase("Build", artifacts={
        "dispatch_usage": {"total_tokens": 500, "provider_id": "claude"},
    })
    hc = _harness()
    outcome = measure_outcome(_task([build]), hc)
    assert outcome.agent_used == "claude"


def test_agent_used_falls_back_to_primary_agent():
    hc = _harness()
    hc.primary_agent = AgentBinding("opencode")
    outcome = measure_outcome(_task([_phase("Build")]), hc)
    assert outcome.agent_used == "opencode"


# ── declared signals get zeros not KeyError ──────────────────────────────────

def test_signals_without_data_are_marked_missing_not_zero_filled():
    # Fabricated zeros would poison the learning loop; absent signals must be
    # absent from quality_signals but accounted for in provenance.
    hc = _harness(TaskClass.EVOLUTION_HARNESS)
    outcome = measure_outcome(_task([]), hc)
    for sig in hc.quality_signals:
        assert sig.name in outcome.signal_provenance
        if outcome.signal_provenance[sig.name] == "missing":
            assert sig.name not in outcome.quality_signals


# ── human_interventions ───────────────────────────────────────────────────────

def test_human_interventions_counted():
    phases = [
        _phase("Build",  artifacts={"human_approved": True}),
        _phase("Verify", artifacts={"human_approved": False}),
        _phase("Review", artifacts={"pause_execution": True}),
    ]
    outcome = measure_outcome(_task(phases), _harness())
    assert outcome.human_interventions == 2
