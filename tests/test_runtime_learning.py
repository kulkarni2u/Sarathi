from src.engine import Complexity, Phase, PhaseResult, TaskContext
from src.phases.learn import LearnHandler
from src.runtime.learning import LearningRecord, LearningStore


def test_learning_record_to_artifact_shape():
    record = LearningRecord(
        task_id="task-1",
        complexity="high",
        generated_at="2026-04-23T10:00:00",
        summary="Repeated failure pattern detected in Verify (2 occurrence(s)).",
        lessons=["Investigate Verify failures"],
        repeated_failures=[{"phase": "Verify", "count": 2}],
        escalations=[],
        iteration_hotspots=[{"phase": "Build", "iterations": 3}],
        phase_outcomes=[{"phase": "Build", "outcome": "pass", "iterations": 3, "error": None}],
    )

    artifact = record.to_artifact()

    assert artifact["task_id"] == "task-1"
    assert artifact["summary"].startswith("Repeated failure pattern")
    assert artifact["repeated_failures"] == [{"phase": "Verify", "count": 2}]
    assert artifact["provider_failures"] == []
    assert artifact["iteration_hotspots"] == [{"phase": "Build", "iterations": 3}]


def test_learning_store_builds_history_and_pattern_summary():
    store = LearningStore()
    prior_record = LearningRecord(
        task_id="task-42",
        complexity="medium",
        generated_at="2026-04-22T10:00:00",
        summary="Earlier learn run.",
        lessons=["Earlier lesson"],
    )
    task = TaskContext(
        task_id="task-42",
        description="Investigate flaky verify flow",
        complexity=Complexity.HIGH,
        phase_results=[
            PhaseResult(
                phase=Phase.LEARN,
                outcome="pass",
                artifacts={"learning_record": prior_record.to_artifact()},
            ),
            PhaseResult(phase=Phase.BUILD, outcome="pass", iterations=3),
            PhaseResult(phase=Phase.VERIFY, outcome="fail"),
            PhaseResult(phase=Phase.VERIFY, outcome="fail"),
            PhaseResult(phase=Phase.REVIEW, outcome="escalate"),
        ],
    )

    artifacts = store.build_artifacts(task)

    assert artifacts["patterns_updated"] is True
    assert artifacts["learning_record"]["complexity"] == "high"
    assert artifacts["learning_record"]["repeated_failures"] == [{"phase": "Verify", "count": 2}]
    assert artifacts["learning_record"]["escalations"] == [{"phase": "Review", "count": 1}]
    assert artifacts["learning_record"]["iteration_hotspots"] == [{"phase": "Build", "iterations": 3}]
    assert len(artifacts["learning_history"]) == 2
    assert artifacts["learning_history"][0]["summary"] == "Earlier learn run."
    assert any(
        lesson.startswith("Phase Verify failed 2 time(s)")
        for lesson in artifacts["lessons_learned"]
    )


def test_learning_store_tracks_provider_failure_signals():
    store = LearningStore()
    task = TaskContext(
        task_id="task-provider-learning",
        description="Recover provider routing",
        complexity=Complexity.HIGH,
        phase_results=[
            PhaseResult(
                phase=Phase.VERIFY,
                outcome="fail",
                artifacts={"dispatch_artifacts": {"provider": "codex"}},
            ),
            PhaseResult(
                phase=Phase.VERIFY,
                outcome="fail",
                artifacts={"dispatch_artifacts": {"provider": "codex"}},
            ),
        ],
    )

    artifacts = store.build_artifacts(task)

    assert artifacts["learning_record"]["provider_failures"] == [
        {"phase": "Verify", "provider": "codex", "count": 2}
    ]
    assert any(
        lesson.startswith("Provider codex failed 2 time(s) in Verify")
        for lesson in artifacts["lessons_learned"]
    )


def test_learn_handler_emits_structured_and_compatibility_artifacts():
    handler = LearnHandler(policy_pack=None)
    task = TaskContext(
        task_id="task-99",
        description="Ship learn persistence",
        complexity=Complexity.MEDIUM,
        phase_results=[
            PhaseResult(phase=Phase.BUILD, outcome="pass", iterations=2),
            PhaseResult(phase=Phase.REVIEW, outcome="escalate"),
        ],
    )

    result = handler.execute(task, Phase.LEARN)

    assert result.outcome == "pass"
    assert result.evidence["execution_analyzed"] is True
    assert result.evidence["lessons_extracted"] is True
    assert result.artifacts["patterns_updated"] is True
    assert result.artifacts["learning_record"]["summary"].startswith("Escalation pattern")
    assert result.artifacts["learning_history"][-1] == result.artifacts["learning_record"]
    assert result.artifacts["lessons_learned"] == result.artifacts["learning_record"]["lessons"]


def test_learn_handler_emits_policy_proposals_from_learning_signals():
    handler = LearnHandler(policy_pack=None)
    task = TaskContext(
        task_id="task-proposals",
        description="Recover verify loop",
        complexity=Complexity.HIGH,
        phase_results=[
            PhaseResult(phase=Phase.VERIFY, outcome="fail"),
            PhaseResult(phase=Phase.VERIFY, outcome="fail"),
        ],
    )

    result = handler.execute(task, Phase.LEARN)

    assert result.evidence["policy_proposals_generated"] == 1
    assert result.artifacts["proposal_count"] == 1
    assert result.artifacts["policy_proposals"][0]["policy_file"] == "commands.md"


def test_learn_handler_emits_routing_proposals_from_provider_failure_signals():
    handler = LearnHandler(policy_pack=None)
    task = TaskContext(
        task_id="task-routing-proposals",
        description="Stabilize provider routing",
        complexity=Complexity.HIGH,
        phase_results=[
            PhaseResult(
                phase=Phase.VERIFY,
                outcome="fail",
                artifacts={"dispatch_artifacts": {"provider": "codex"}},
            ),
            PhaseResult(
                phase=Phase.VERIFY,
                outcome="fail",
                artifacts={"dispatch_artifacts": {"provider": "codex"}},
            ),
        ],
    )

    result = handler.execute(task, Phase.LEARN)
    proposals = {
        proposal["source"]: proposal for proposal in result.artifacts["policy_proposals"]
    }

    assert "provider_failures" in proposals
    assert proposals["provider_failures"]["policy_file"] == "model-routing.md"
    assert proposals["provider_failures"]["routing_hint"]["phase"] == "Verify"
    assert proposals["provider_failures"]["routing_hint"]["preferred_provider"] == "local"
