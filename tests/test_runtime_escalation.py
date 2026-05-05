from src.runtime import EscalationBundle, EscalationBundleBuilder


def test_escalation_bundle_serializes_case_file():
    bundle = EscalationBundle(
        task_id="task-1",
        phase="Build",
        reason="step-1 failed",
        recommended_action="Fix step-1 and resume",
        graph_node={"id": "step-1", "title": "Build", "status": "failed"},
        verification_summary={"command_succeeded": False},
        review_summary={"outcome": "escalate"},
        artifact_refs=["artifact.json"],
        generated_at="2026-04-23T10:00:00Z",
    )

    artifact = bundle.to_artifact()

    assert artifact["task_id"] == "task-1"
    assert artifact["reason"] == "step-1 failed"
    assert artifact["graph_node"]["id"] == "step-1"
    assert artifact["artifact_refs"] == ["artifact.json"]


def test_escalation_builder_uses_task_history():
    class Result:
        artifact_refs = ["verify.json"]
        artifacts = {
            "verification_summary": {"command_succeeded": False},
            "review_summary": {"outcome": "fail"},
        }

    class Task:
        task_id = "task-2"
        phase_results = [Result()]

    bundle = EscalationBundleBuilder().build_for_phase(
        task=Task(),
        phase="Build",
        reason="blocked",
        graph_node={"id": "step-2", "title": "Implement", "status": "waiting_human"},
    )

    artifact = bundle.to_artifact()

    assert artifact["verification_summary"]["command_succeeded"] is False
    assert artifact["review_summary"]["outcome"] == "fail"
    assert artifact["artifact_refs"] == ["verify.json"]
    assert "resume" in artifact["recommended_action"].lower()
