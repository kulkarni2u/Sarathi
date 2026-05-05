from src.engine import Phase, PolicyPack
from src.phases.review import ReviewHandler
from src.runtime import ReviewFinding, ReviewRunner, ReviewVerdict


def test_review_runner_emits_structured_verdict():
    verdict = ReviewRunner().review()
    artifact = verdict.to_artifact()

    assert artifact["outcome"] == "pass"
    assert artifact["score"] == 10.0
    assert artifact["findings"]
    assert artifact["generated_at"]
    assert artifact["severity_counts"] == {
        "info": 5,
        "minor": 0,
        "major": 0,
        "critical": 0,
    }
    assert artifact["totals"] == {"checks": 5, "passed": 5, "failed": 0}
    assert artifact["summary"]["outcome"] == "pass"
    assert artifact["summary"]["checks"] == 5


def test_review_verdict_escalates_for_partial_failure():
    verdict = ReviewRunner().review(
        {
            "spec_compliance": True,
            "code_quality": True,
            "security": True,
            "performance": False,
            "documentation": False,
        }
    )

    assert verdict.outcome == "escalate"
    assert verdict.score == 6.0
    assert verdict.severity_counts == {
        "info": 3,
        "minor": 0,
        "major": 2,
        "critical": 0,
    }
    assert verdict.totals == {"checks": 5, "passed": 3, "failed": 2}


def test_review_verdict_fails_on_critical_finding():
    verdict = ReviewVerdict(
        findings=[
            ReviewFinding("security", passed=False, severity="critical", message="unsafe"),
            ReviewFinding("docs", passed=True),
        ]
    )

    assert verdict.outcome == "fail"
    assert verdict.severity_counts["critical"] == 1
    assert verdict.totals == {"checks": 2, "passed": 1, "failed": 1}
    assert verdict.to_artifact()["summary"]["failed"] == 1


def test_review_runner_consumes_graph_and_verify_evidence():
    verdict = ReviewRunner().review(
        evidence={
            "task_graph_summary": {"failed": 1, "waiting_human": 0, "pending": 1},
            "verification_summary": {
                "command_succeeded": False,
                "lint_errors": 1,
                "security_vulnerabilities": 0,
            },
            "escalation_bundle": {"reason": "Graph node step-1 failed"},
        }
    )
    artifact = verdict.to_artifact()

    assert artifact["outcome"] == "fail"
    assert artifact["totals"]["failed"] >= 4
    assert any(finding["check"] == "graph_execution" for finding in artifact["findings"])
    assert any(finding["check"] == "escalation_bundle" for finding in artifact["findings"])


def test_review_runner_consumes_real_spec_and_diff_evidence():
    verdict = ReviewRunner().review(
        evidence={
            "spec_text": "Implement policy-backed proposal acceptance.",
            "acceptance_criteria": ["accepted proposals are recorded"],
            "diff_summary": {"changed_files": 2, "files": ["src/a.py", "tests/test_a.py"]},
        }
    )
    artifact = verdict.to_artifact()

    assert artifact["outcome"] == "pass"
    assert any(finding["check"] == "spec_evidence" for finding in artifact["findings"])
    assert any(finding["check"] == "diff_evidence" for finding in artifact["findings"])


def test_review_handler_surfaces_summary_and_severity_counts():
    handler = ReviewHandler(policy_pack=PolicyPack())

    result = handler.execute(task=None, phase=Phase.REVIEW)

    assert result.outcome == "pass"
    assert result.evidence["review_score_calculated"] is True
    assert result.evidence["severity_counts"]["info"] == 5
    assert result.evidence["failed_review_checks"] == 0
    assert result.artifacts["review_summary"]["checks"] == 5


def test_review_handler_uses_prior_task_artifacts():
    task = type(
        "Task",
        (),
        {
            "task_graph_state": {
                "nodes": [
                    {"id": "step-1", "title": "Build", "status": "waiting_human", "depends_on": []}
                ]
            },
            "description": "Spec text for review",
            "phase_results": [
                type(
                    "Result",
                    (),
                    {
                        "artifacts": {
                            "verification_summary": {"command_succeeded": False, "lint_errors": 0},
                            "escalation_bundle": {"reason": "step-1 needs help"},
                            "implementation_plan": {"success_criteria": ["review evidence captured"]},
                        }
                    },
                )()
            ],
        },
    )()
    handler = ReviewHandler(policy_pack=PolicyPack())

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert result.outcome == "fail"
    assert "task_graph_summary" in result.evidence["review_input_sources"]
    assert "spec_text" in result.evidence["review_input_sources"]
    assert "acceptance_criteria" in result.evidence["review_input_sources"]
    assert result.artifacts["review_inputs"]["escalation_bundle"]["reason"] == "step-1 needs help"


def test_review_handler_respects_quality_loop_policy_for_critical_findings():
    task = type(
        "Task",
        (),
        {
            "task_graph_state": {
                "nodes": [
                    {"id": "step-1", "title": "Build", "status": "waiting_human", "depends_on": []}
                ]
            },
            "phase_results": [],
        },
    )()
    policy = PolicyPack(escalation={"quality_loop": {"review_retry_budget": 2, "auto_fix_attempts": 1}})
    handler = ReviewHandler(policy_pack=policy)

    result = handler.execute(task=task, phase=Phase.REVIEW)

    assert result.outcome == "fail"
    assert result.artifacts["quality_loop_policy"]["review_retry_budget"] == 2
    assert result.artifacts["retry_recommended"] is False
    assert result.artifacts["auto_fix_allowed"] is False
