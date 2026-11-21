"""Persisted, rolling, relative quality baselines for Evolver.ingest_harness_outcome."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.evolve import EvolutionPolicy, Evolver
from src.harness import HarnessOutcome
from src.task_class import TaskClass


def _outcome(signals: dict[str, float], task_id: str = "t") -> HarnessOutcome:
    return HarnessOutcome(
        harness_id="h",
        task_id=task_id,
        task_class=TaskClass.CODEGEN_PATCH,
        quality_signals=signals,
        token_cost_actual=0,
        latency_ms=0,
        human_interventions=0,
        rollback_triggered=False,
        trust_gate_result="PASS",
        agent_used="claude",
        signal_provenance={name: "measured" for name in signals},
    )


def test_baselines_survive_a_new_process(tmp_path):
    path = tmp_path / ".sarathi" / "evolve_baselines.json"
    assert (
        Evolver(baseline_path=path).ingest_harness_outcome(
            _outcome({"test_pass_rate": 0.9})
        )
        == []
    )

    # A fresh Evolver (as in the next `sarathi run`) compares against it.
    proposals = Evolver(baseline_path=path).ingest_harness_outcome(
        _outcome({"test_pass_rate": 0.5})
    )
    assert [p.title for p in proposals] == [
        "Quality signal 'test_pass_rate' degraded for codegen/patch"
    ]
    assert json.loads(path.read_text())["codegen/patch"]["test_pass_rate"] == [0.9, 0.5]


def test_without_a_path_each_evolver_starts_empty():
    Evolver().ingest_harness_outcome(_outcome({"test_pass_rate": 0.9}))
    assert Evolver().ingest_harness_outcome(_outcome({"test_pass_rate": 0.5})) == []


def test_counts_deviate_relative_to_baseline_and_lower_is_better(tmp_path):
    evolver = Evolver(baseline_path=tmp_path / "b.json")
    evolver.ingest_harness_outcome(_outcome({"token_cost": 1000.0}))
    # +5% is within the 10% threshold (an absolute 0.1 test fired on any change).
    assert evolver.ingest_harness_outcome(_outcome({"token_cost": 1050.0})) == []
    [costlier] = evolver.ingest_harness_outcome(_outcome({"token_cost": 1400.0}))
    assert "token_cost' degraded" in costlier.title
    other = Evolver(baseline_path=tmp_path / "c.json")
    assert other.ingest_harness_outcome(_outcome({"token_cost": 1000.0})) == []
    [cheaper] = other.ingest_harness_outcome(_outcome({"token_cost": 600.0}))
    assert "token_cost' improved" in cheaper.title


def test_rolling_window_and_min_samples_come_from_policy(tmp_path):
    policy = EvolutionPolicy.from_escalation(
        {"learn_evolve": {"baseline_window": 3, "baseline_min_samples": 3}}
    )
    evolver = Evolver(policy, baseline_path=tmp_path / "b.json")
    # Too few samples: a single noisy run is not a baseline.
    for value in (0.9, 0.2):
        assert evolver.ingest_harness_outcome(_outcome({"accuracy": value})) == []
    assert evolver.ingest_harness_outcome(_outcome({"accuracy": 0.9})) == []
    # Baseline is now mean(0.9, 0.2, 0.9) = 0.667; 0.7 is within 0.1.
    assert evolver.ingest_harness_outcome(_outcome({"accuracy": 0.7})) == []
    stored = json.loads((tmp_path / "b.json").read_text())["codegen/patch"]["accuracy"]
    assert stored == [0.2, 0.9, 0.7]  # only the last baseline_window values are kept


def test_corrupt_baseline_file_starts_empty(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("{not json")
    assert (
        Evolver(baseline_path=path).ingest_harness_outcome(_outcome({"accuracy": 0.9}))
        == []
    )
    assert json.loads(path.read_text())["codegen/patch"]["accuracy"] == [0.9]


def test_failure_outcomes_policy():
    assert EvolutionPolicy().failure_outcomes == ("fail", "escalate")
    custom = EvolutionPolicy.from_escalation(
        {"learn_evolve": {"failure_outcomes": ["fail"]}}
    )
    assert custom.failure_outcomes == ("fail",)
    assert EvolutionPolicy.from_escalation(
        {"learn_evolve": {"failure_outcomes": "fail"}}
    ).failure_outcomes == ("fail", "escalate")


def test_learn_handler_persists_baselines_in_state_dir(tmp_path):
    from src.phases.learn import LearnHandler

    pack = SimpleNamespace(escalation={})
    first = LearnHandler(pack, state_dir=tmp_path)
    first.evolver.ingest_harness_outcome(_outcome({"test_pass_rate": 0.9}))
    second = LearnHandler(pack, state_dir=tmp_path)
    assert second.evolver.ingest_harness_outcome(_outcome({"test_pass_rate": 0.4}))
    assert (tmp_path / "evolve_baselines.json").exists()
