import json

from src.runtime.autoresearch import AutoresearchStore, EvidenceTier


def test_autoresearch_registers_hypothesis_and_records_verdict(tmp_path):
    store = AutoresearchStore(tmp_path)

    experiment = store.register(
        hypothesis="A terse reviewer contract reduces output tokens",
        prediction="Reviewer output drops by at least 20% with verdicts intact",
        tier=EvidenceTier.MICRO,
        method="5 reps against a no-guidance control",
        quality_gate="Manual inspection confirms verdict fidelity",
        created_by="vichara",
    )
    evidence = store.append_evidence(
        experiment.experiment_id,
        summary="Output tokens dropped 41%; 5/5 verdicts intact",
        uri="sarathi://runs/reviewer-economy",
        metrics={"output_reduction": 0.41, "verdicts_intact": 5},
        recorded_by="nirnaya",
    )
    verdict = store.record_verdict(
        experiment.experiment_id,
        verdict="confirmed",
        summary="Adopt terse reviewer contract",
        evidence_refs=[evidence.evidence_id],
        cost_usd=1.25,
        recorded_by="sarathi",
    )

    reloaded = AutoresearchStore(tmp_path)
    loaded = reloaded.get(experiment.experiment_id)

    assert loaded is not None
    assert loaded.status == "confirmed"
    assert loaded.verdict == verdict
    assert loaded.evidence_refs == [evidence.evidence_id]
    assert loaded.to_artifact()["tier"] == "MICRO"

    events = [json.loads(line) for line in (tmp_path / "autoresearch.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["registered", "evidence", "verdict"]


def test_autoresearch_lists_negative_results_as_first_class_records(tmp_path):
    store = AutoresearchStore(tmp_path)
    experiment = store.register(
        hypothesis="Capping controller thinking saves money",
        prediction="Cost drops without more turns",
        tier="FULL",
        method="Two full eval runs",
        quality_gate="No quality regression",
    )

    store.record_verdict(
        experiment.experiment_id,
        verdict="refuted",
        summary="Thinking cap increased turns and output tokens",
        evidence_refs=["run-a", "run-b"],
    )

    records = store.list(status="refuted")

    assert len(records) == 1
    assert records[0].hypothesis == "Capping controller thinking saves money"
    assert records[0].evidence_refs == ["run-a", "run-b"]


def test_autoresearch_verdict_defaults_to_attached_evidence_refs(tmp_path):
    store = AutoresearchStore(tmp_path)
    experiment = store.register(
        hypothesis="Review packets improve reviewer throughput",
        prediction="Average review duration drops by 25%",
        tier="MICRO",
        method="Compare five paired reviews",
        quality_gate="No increase in missed findings",
    )
    evidence = store.append_evidence(
        experiment.experiment_id,
        summary="Average duration dropped by 32%",
    )

    store.record_verdict(
        experiment.experiment_id,
        verdict="confirmed",
        summary="Adopt review packets",
    )

    reloaded = AutoresearchStore(tmp_path)
    loaded = reloaded.get(experiment.experiment_id)

    assert loaded is not None
    assert loaded.evidence_refs == [evidence.evidence_id]
