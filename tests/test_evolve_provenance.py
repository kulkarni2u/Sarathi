"""Provenance-weighted learning: ingest_harness_outcome should weight quality
signal deltas by their provenance ("measured" vs "derived") and must not
emit policy proposals from derived-only evidence.
"""
from __future__ import annotations

from src.evolve import Evolver
from src.harness import HarnessOutcome
from src.task_class import TaskClass


def _outcome(quality_signals: dict[str, float], signal_provenance: dict[str, str] | None = None, **overrides) -> HarnessOutcome:
    base = dict(
        harness_id="harness-1",
        task_id="task-1",
        task_class=TaskClass.CODEGEN_PATCH,
        quality_signals=quality_signals,
        token_cost_actual=100,
        latency_ms=1000,
        human_interventions=0,
        rollback_triggered=False,
        trust_gate_result="PASS",
        agent_used="claude",
    )
    if signal_provenance is not None:
        base["signal_provenance"] = signal_provenance
    base.update(overrides)
    return HarnessOutcome(**base)


def test_measured_signal_delta_triggers_proposal_as_before():
    evolver = Evolver()

    # First ingestion establishes the baseline (no proposal yet).
    baseline_outcome = _outcome(
        {"test_pass_rate": 0.9},
        signal_provenance={"test_pass_rate": "measured"},
        task_id="task-baseline",
    )
    proposals = evolver.ingest_harness_outcome(baseline_outcome)
    assert proposals == []

    # Second ingestion deviates by more than 0.1 -> proposal fires.
    deviated_outcome = _outcome(
        {"test_pass_rate": 0.5},
        signal_provenance={"test_pass_rate": "measured"},
        task_id="task-deviated",
    )
    proposals = evolver.ingest_harness_outcome(deviated_outcome)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert "test_pass_rate" in proposal.title
    assert "measured" in proposal.rationale
    assert any("measured" in ref for ref in proposal.evidence_refs)


def test_derived_only_deviation_never_produces_proposal():
    evolver = Evolver()

    baseline_outcome = _outcome(
        {"blast_radius": 0.1},
        signal_provenance={"blast_radius": "derived"},
        task_id="task-baseline",
    )
    proposals = evolver.ingest_harness_outcome(baseline_outcome)
    assert proposals == []

    # Deviates by 0.4 (well over 0.1), but provenance is derived (weight 0.5)
    # and there is no measured signal among the contributors -> held back.
    deviated_outcome = _outcome(
        {"blast_radius": 0.5},
        signal_provenance={"blast_radius": "derived"},
        task_id="task-deviated",
    )
    proposals = evolver.ingest_harness_outcome(deviated_outcome)

    assert proposals == []


def test_mixed_measured_and_derived_signals_produce_proposal_with_provenance():
    evolver = Evolver()

    baseline_outcome = _outcome(
        {"test_pass_rate": 0.9, "blast_radius": 0.1},
        signal_provenance={"test_pass_rate": "measured", "blast_radius": "derived"},
        task_id="task-baseline",
    )
    proposals = evolver.ingest_harness_outcome(baseline_outcome)
    assert proposals == []

    # Both signals deviate by more than 0.1. test_pass_rate is measured, so
    # the batch fires -- and the derived blast_radius deviation rides along,
    # but its provenance must be visible in the proposal payload.
    deviated_outcome = _outcome(
        {"test_pass_rate": 0.5, "blast_radius": 0.5},
        signal_provenance={"test_pass_rate": "measured", "blast_radius": "derived"},
        task_id="task-deviated",
    )
    proposals = evolver.ingest_harness_outcome(deviated_outcome)

    assert len(proposals) == 2
    by_signal = {}
    for proposal in proposals:
        for ref in proposal.evidence_refs:
            if ":quality:" in ref:
                signal_name = ref.split(":quality:")[1].split(":")[0]
                by_signal[signal_name] = proposal

    assert "test_pass_rate" in by_signal
    assert "blast_radius" in by_signal
    assert "measured" in by_signal["test_pass_rate"].rationale
    assert "derived" in by_signal["blast_radius"].rationale
    assert any("derived" in ref for ref in by_signal["blast_radius"].evidence_refs)


def test_legacy_outcome_without_signal_provenance_behaves_as_before():
    evolver = Evolver()

    # No signal_provenance attribute set explicitly -- defaults to {} via the
    # dataclass field default, simulating an old persisted outcome.
    baseline_outcome = _outcome({"test_pass_rate": 0.9}, task_id="task-baseline")
    assert baseline_outcome.signal_provenance == {}
    proposals = evolver.ingest_harness_outcome(baseline_outcome)
    assert proposals == []

    deviated_outcome = _outcome({"test_pass_rate": 0.5}, task_id="task-deviated")
    proposals = evolver.ingest_harness_outcome(deviated_outcome)

    # Absent provenance is treated as "measured" -> proposal fires as before.
    assert len(proposals) == 1
    assert "test_pass_rate" in proposals[0].title
