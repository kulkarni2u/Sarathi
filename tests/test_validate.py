from pathlib import Path

from src.policy import compile_policy_pack
from src.validate import PolicyValidator, ValidationStatus


def test_validation_pass():
    validator = PolicyValidator(engine_path="engine", policy_pack_path="policy-pack")
    result = validator.validate(
        required_list={"Route": ["complexity_triggers"]},
        policy_claims={"complexity.md": ["complexity_triggers"]},
    )
    assert len(result) == 1
    assert result[0].status == ValidationStatus.PASS


def test_validation_detects_semantic_drift(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text("# Commands\n")

    validator = PolicyValidator(engine_path="engine", policy_pack_path=str(policy_dir))
    result = validator.validate(
        required_list={"Build": ["build_commands"]},
    )

    assert len(result) == 1
    assert result[0].status == ValidationStatus.DRIFT


def test_compiled_policy_sections_keep_typed_and_legacy_access_in_sync(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "review.md").write_text(
        """# Review

```yaml
max_rounds: 2
min_coverage: 80
```
"""
    )

    compiled = compile_policy_pack(str(policy_dir))
    section = compiled.get_section("review")

    assert section is not None
    assert section.typed_data["max_rounds"] == 2
    assert section.data == {"max_rounds": 2, "min_coverage": 80}
    assert compiled.get("review") == {"max_rounds": 2, "min_coverage": 80}


def test_validation_detects_invalid_graph_execution_policy(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "task-tracking.md").write_text(
        """# Task Tracking

```yaml
task: configured
options: configured
graph_execution:
  step_limit: "one"
  max_retries: -1
  auto_retry_failed_nodes: "yes"
```
"""
    )

    validator = PolicyValidator(engine_path="engine", policy_pack_path=str(policy_dir))
    result = validator.validate(
        required_list={"TaskTracking": ["task_manifest_format"]},
    )

    assert len(result) == 1
    assert result[0].status == ValidationStatus.DRIFT
    assert "graph_execution.step_limit" in result[0].issue


def test_validation_detects_invalid_quality_loop_policy(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "escalation.md").write_text(
        """# Escalation

```yaml
auto_fix: configured
review: configured
quality_loop:
  verify_retry_budget: -1
  hard_stop_on_critical: "yes"
```
"""
    )

    validator = PolicyValidator(engine_path="engine", policy_pack_path=str(policy_dir))
    result = validator.validate(
        required_list={"Verify": ["retry_budgets"]},
    )

    assert len(result) == 1
    assert result[0].status == ValidationStatus.DRIFT
    assert "quality_loop.verify_retry_budget" in result[0].issue


def test_validation_detects_invalid_provider_routing_policy(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "model-routing.md").write_text(
        """# Model Routing

```yaml
provider:
  - not-a-string
providers:
  cmd:
    type: command
```
"""
    )

    validator = PolicyValidator(engine_path="engine", policy_pack_path=str(policy_dir))
    result = validator.validate(required_list={"Route": ["provider_routing"]})

    assert any(item.status == ValidationStatus.DRIFT for item in result)
    assert any("model_routing.provider" in item.issue for item in result)
