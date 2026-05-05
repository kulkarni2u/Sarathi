from src.runtime import PreflightPolicy


def test_preflight_policy_blocks_on_todo_by_default():
    policy = PreflightPolicy()
    assert policy.should_block(todo_count=1, drift_count=0) is True
    assert policy.should_block(todo_count=0, drift_count=1) is False


def test_preflight_policy_can_block_on_drift_when_enabled():
    policy = PreflightPolicy(block_on_todo=True, block_on_drift=True)
    assert policy.should_block(todo_count=0, drift_count=1) is True
    assert policy.warning_count(drift_count=2) == 2
