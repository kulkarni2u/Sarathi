from src.runtime import GraphExecutionPolicy, validate_graph_execution_config


def test_graph_execution_policy_defaults():
    policy = GraphExecutionPolicy()

    assert policy.step_limit is None
    assert policy.max_retries == 2
    assert policy.auto_retry_failed_nodes is True
    assert policy.auto_schedule_ready_nodes is False
    assert policy.pause_on_incomplete_graph is True
    assert policy.pause_on_failed_node is True
    assert policy.require_human_after_retries is True


def test_graph_execution_policy_prefers_task_tracking_over_escalation():
    policy = GraphExecutionPolicy.from_policy_sections(
        task_tracking={
            "graph_execution": {
                "step_limit": 1,
                "max_retries": 4,
                "auto_retry_failed_nodes": False,
                "auto_schedule_ready_nodes": True,
            }
        },
        escalation={
            "graph_execution": {
                "step_limit": 3,
                "max_retries": 2,
                "pause_on_failed_node": False,
            }
        },
        use_env_overrides=False,
    )

    assert policy.step_limit == 1
    assert policy.max_retries == 4
    assert policy.auto_retry_failed_nodes is False
    assert policy.auto_schedule_ready_nodes is True
    assert policy.pause_on_failed_node is False


def test_graph_execution_policy_applies_env_overrides(monkeypatch):
    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "3")
    monkeypatch.setenv("SARATHI_GRAPH_MAX_RETRIES", "5")

    policy = GraphExecutionPolicy.from_policy_sections(
        task_tracking={"graph_execution": {"step_limit": 1, "max_retries": 2}},
    )

    assert policy.step_limit == 3
    assert policy.max_retries == 5


def test_graph_execution_config_validation():
    issues = validate_graph_execution_config(
        {
            "step_limit": "one",
            "max_retries": -1,
            "auto_retry_failed_nodes": "yes",
            "auto_schedule_ready_nodes": "sometimes",
        }
    )

    assert "graph_execution.step_limit must be a non-negative integer" in issues
    assert "graph_execution.max_retries must be a non-negative integer" in issues
    assert "graph_execution.auto_retry_failed_nodes must be a boolean" in issues
    assert "graph_execution.auto_schedule_ready_nodes must be a boolean" in issues
