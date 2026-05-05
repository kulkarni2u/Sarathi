from src.runtime import QualityLoopPolicy, validate_quality_loop_config


def test_quality_loop_policy_defaults_and_escalation_config():
    default_policy = QualityLoopPolicy.from_escalation({})
    configured = QualityLoopPolicy.from_escalation(
        {
            "quality_loop": {
                "verify_retry_budget": 2,
                "review_retry_budget": 3,
                "auto_fix_attempts": 1,
                "hard_stop_on_critical": False,
            }
        }
    )

    assert default_policy.verify_retry_budget == 1
    assert configured.review_retry_budget == 3
    assert configured.auto_fix_attempts == 1
    assert configured.hard_stop_on_critical is False


def test_quality_loop_config_validation():
    issues = validate_quality_loop_config(
        {
            "verify_retry_budget": -1,
            "review_retry_budget": "two",
            "auto_fix_attempts": True,
            "hard_stop_on_critical": "yes",
        }
    )

    assert "quality_loop.verify_retry_budget must be a non-negative integer" in issues
    assert "quality_loop.review_retry_budget must be a non-negative integer" in issues
    assert "quality_loop.auto_fix_attempts must be a non-negative integer" in issues
    assert "quality_loop.hard_stop_on_critical must be a boolean" in issues


def test_quality_loop_policy_uses_accepted_learning_feedback():
    policy = QualityLoopPolicy.from_escalation(
        {"quality_loop": {"verify_retry_budget": 1, "review_retry_budget": 1, "auto_fix_attempts": 0}},
        learning_feedback={
            "accepted_proposals": [
                {
                    "title": "Add Verify failure recovery guidance",
                    "source": "repeated_failures",
                },
                {
                    "title": "Tighten Review escalation criteria",
                    "source": "escalations",
                },
            ]
        },
    )

    assert policy.verify_retry_budget == 2
    assert policy.review_retry_budget == 2
    assert policy.auto_fix_attempts == 1
