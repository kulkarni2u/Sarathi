from pathlib import Path
import sys

import pytest
from src.engine import Engine, Phase, Complexity, TaskContext, PhaseResult, PersistenceManager


def test_engine_initialization():
    engine = Engine()
    assert engine is not None


def test_route_phase_sets_complexity():
    task = TaskContext(
        task_id="test-1",
        description="Test task",
        complexity=Complexity.HIGH,
    )
    engine = Engine()
    result = engine.run_task(task)
    assert result.complexity == Complexity.HIGH
    # LOW skips PLANNING_ADVISOR; HIGH runs all but may fail gates
    assert len(task.phase_results) >= 5
    assert task.phase_results[0].phase == Phase.ROUTE


def test_phase_log_format():
    task = TaskContext(
        task_id="test-2",
        description="Test task",
        complexity=Complexity.LOW,
    )
    engine = Engine()
    engine.run_task(task)
    # Low complexity skips PLANNING_ADVISOR - runs fewer phases than full 12
    assert len(task.phase_results) >= 5
    skipped = [pr for pr in task.phase_results if pr.outcome == "skip"]
    assert len(skipped) == 1
    assert skipped[0].phase == Phase.PLANNING_ADVISOR
    for pr in task.phase_results:
        assert pr.phase in Phase
        assert pr.outcome in {"pass", "skip", "fail", "escalate", "unverified"}


def test_engine_preflight_records_summary_without_blocking(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text("# Commands\n")

    task = TaskContext(
        task_id="preflight-recorded",
        description="Test task",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    assert result.preflight_validation["total"] > 0
    assert "artifact_ref" in result.preflight_validation
    assert result.preflight_validation["warning_count"] >= 0
    assert len(result.phase_results) == 12


def test_engine_enforced_preflight_blocks_on_todo(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "commands.md").write_text("# Commands\n")

    task = TaskContext(
        task_id="preflight-block",
        description="Test task",
        complexity=Complexity.MEDIUM,
    )
    engine = Engine(policy_pack_path=str(policy_dir), enforce_preflight=True)
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    assert result.phase_results == []
    assert result.preflight_validation["blocking"] is True
    assert result.preflight_validation["todo"] > 0


def test_engine_persists_completed_task_graph_state(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    task = TaskContext(
        task_id="graph-complete",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    assert result.task_graph_state
    statuses = {node["status"] for node in result.task_graph_state["nodes"]}
    assert statuses == {"completed"}


def test_engine_can_persist_partial_task_graph_state(tmp_path: Path, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "1")
    task = TaskContext(
        task_id="graph-partial",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    assert result.task_graph_state
    assert result.current_phase == Phase.BUILD
    assert Phase.LEARN not in result.get_completed_phases()
    statuses = [node["status"] for node in result.task_graph_state["nodes"]]
    assert statuses.count("completed") == 1
    assert statuses.count("pending") >= 1


def test_engine_resume_advances_paused_build_task(tmp_path: Path, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "1")
    task = TaskContext(
        task_id="graph-resume",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    first_pass = engine.run_task(task)
    assert first_pass.current_phase == Phase.BUILD

    resumed = engine.resume_task(first_pass)

    assert resumed.current_phase == Phase.BUILD
    statuses = [node["status"] for node in resumed.task_graph_state["nodes"]]
    assert statuses.count("completed") == 2


def test_engine_resume_retries_failed_build_node(tmp_path: Path, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    monkeypatch.setenv("SARATHI_GRAPH_STEP_LIMIT", "1")
    monkeypatch.setenv("SARATHI_GRAPH_FAIL_NODE", "step-1")
    task = TaskContext(
        task_id="graph-fail-retry",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    first_pass = engine.run_task(task)

    assert first_pass.current_phase == Phase.BUILD
    assert first_pass.phase_results[-1].outcome == "escalate"
    assert first_pass.task_graph_state["failed_nodes"] == ["step-1"]

    monkeypatch.delenv("SARATHI_GRAPH_FAIL_NODE")
    resumed = engine.resume_task(first_pass)

    assert resumed.current_phase == Phase.BUILD
    failed_statuses = [node["status"] for node in resumed.task_graph_state["nodes"]]
    assert "failed" not in failed_statuses
    first_node = resumed.task_graph_state["nodes"][0]
    assert first_node["status"] == "completed"
    assert first_node["attempts"] == 2


def test_engine_uses_policy_graph_step_limit(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": """```yaml
task: configured
options: configured
graph_execution:
  step_limit: 1
```
""",
    }.items():
        (policy_dir / filename).write_text(content)

    task = TaskContext(
        task_id="graph-policy-step",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    assert result.current_phase == Phase.BUILD
    assert result.phase_results[-1].artifacts["graph_execution_policy"]["step_limit"] == 1
    statuses = [node["status"] for node in result.task_graph_state["nodes"]]
    assert statuses.count("completed") == 1
    assert statuses.count("pending") >= 1


def test_engine_moves_exhausted_failed_node_to_waiting_human(tmp_path: Path, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "```yaml\ntest:\n  command: \"echo test\"\n```\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": """```yaml
task: configured
options: configured
graph_execution:
  step_limit: 1
  max_retries: 1
  require_human_after_retries: true
```
""",
    }.items():
        (policy_dir / filename).write_text(content)

    monkeypatch.setenv("SARATHI_GRAPH_FAIL_NODE", "step-1")
    task = TaskContext(
        task_id="graph-waiting-human",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    assert result.current_phase == Phase.BUILD
    assert result.phase_results[-1].outcome == "escalate"
    assert result.phase_results[-1].evidence["human_attention_required"] is True
    assert result.phase_results[-1].artifacts["escalation_bundle"]["graph_node"]["status"] == "waiting_human"
    assert "retry budget" in result.phase_results[-1].artifacts["escalation_bundle"]["reason"]
    assert result.task_graph_state["nodes"][0]["status"] == "waiting_human"
    assert result.task_graph_state["ready_nodes"] == []


def test_engine_executes_bounded_verify_recovery_loop(tmp_path: Path, monkeypatch):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": f"""```yaml
test:
  command: "{sys.executable} -c 'import sys; sys.exit(7)'"
```
""",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": """```yaml
auto_fix: configured
review: configured
quality_loop:
  verify_retry_budget: 1
  auto_fix_attempts: 1
```
""",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    monkeypatch.setenv("SARATHI_EXEC_COMMANDS", "1")
    task = TaskContext(
        task_id="verify-recovery",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    verify_results = [
        phase_result for phase_result in result.phase_results
        if phase_result.phase == Phase.VERIFY
    ]
    assert len(verify_results) == 2
    recovery_action = verify_results[0].artifacts["recovery_actions"][0]
    assert recovery_action["action"] == "prepare_retry_for_verify"
    assert recovery_action["details"]["provider_recovery"]["success"] is True
    assert recovery_action["details"]["provider_recovery"]["artifacts"]["provider"] == "local"
    assert verify_results[1].iterations == 1
    assert verify_results[1].decisions == ["Retried after recovery action 1"]
    assert Phase.LEARN in result.get_completed_phases()


def test_engine_attaches_agent_roles_to_executed_and_skipped_phases(tmp_path: Path):
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "# Commands\n",
        "review.md": "max_rounds: 5\nmin_coverage: 80\n",
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)

    task = TaskContext(
        task_id="agent-roles",
        description="Fix bug",
        complexity=Complexity.LOW,
    )
    engine = Engine(policy_pack_path=str(policy_dir))
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))

    result = engine.run_task(task)

    route_result = next(phase_result for phase_result in result.phase_results if phase_result.phase == Phase.ROUTE)
    skipped_advisor = next(
        phase_result for phase_result in result.phase_results
        if phase_result.phase == Phase.PLANNING_ADVISOR
    )
    build_result = next(phase_result for phase_result in result.phase_results if phase_result.phase == Phase.BUILD)

    assert route_result.artifacts["agent_role"]["name"] == "Marga"
    assert route_result.evidence["agent_role_assigned"] is True
    assert skipped_advisor.artifacts["agent_role"]["name"] == "Disha"
    assert build_result.artifacts["agent_role"]["name"] == "Pravaha"


# ---------------------------------------------------------------------------
# GateEvidencePolicy: gate thresholds/remediation/retry-phases now come from
# the `review` policy-pack section (src/runtime/quality_policy.py) instead of
# module-level constants in src/engine.py. Defaults must reproduce the old
# hardcoded values exactly; a policy pack may override them.
# ---------------------------------------------------------------------------

from src.runtime import GateEvidencePolicy  # noqa: E402


def _policy_dir_with_review(tmp_path: Path, review_content: str) -> Path:
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    for filename, content in {
        "complexity.md": "classification_thresholds: present\nskip_rules: present\n",
        "conventions.md": "conventions: present\nbrainstorming_protocol: present\n",
        "commands.md": "# Commands\n",
        "review.md": review_content,
        "escalation.md": "auto_fix: configured\nreview: configured\n",
        "skills.md": "pattern_detection: enabled\nevolution_threshold: 0.8\n",
        "task-tracking.md": "task: configured\noptions: configured\n",
    }.items():
        (policy_dir / filename).write_text(content)
    return policy_dir


def test_gate_evidence_policy_defaults_match_former_hardcoded_values():
    """Pure-refactor guarantee: no review.md gate_* block => identical behavior."""
    policy = GateEvidencePolicy.from_review(None)
    assert policy.threshold_for("Brainstorm") == 0.80
    assert policy.threshold_for("Plan") == 0.90
    assert policy.is_retry_phase("Brainstorm")
    assert policy.is_retry_phase("Plan")
    assert not policy.is_retry_phase("Route")
    assert policy.remediation_for("risks_identified") == (
        "Brainstorm did not identify risks; ask the provider to set evidence.risks_identified "
        "after enumerating potential failure modes or concerns."
    )
    assert policy.remediation_for("rollback_plan") == (
        "Plan has no rollback plan; the provider should document a recovery procedure and set "
        "evidence.rollback_plan."
    )
    assert policy.remediation_for("not_a_real_key") is None


def test_engine_check_gate_default_thresholds_unchanged(tmp_path: Path):
    """Engine wired from a policy pack with no gate_* overrides behaves as before."""
    policy_dir = _policy_dir_with_review(tmp_path, "max_rounds: 5\nmin_coverage: 80\n")
    engine = Engine(policy_pack_path=str(policy_dir))

    # 0.6 < 0.80 default Brainstorm threshold => fails
    passed, score = engine.check_gate(
        Phase.BRAINSTORM,
        {
            "alternative_approaches_considered": True,
            "risks_identified": True,
            "success_criteria_defined": False,
            "reversibility_assessed": False,
        },
    )
    assert not passed
    assert abs(score - 0.6) < 1e-9


def test_engine_check_gate_honors_custom_review_threshold(tmp_path: Path):
    """A review.md gate_thresholds override changes actual gate pass/fail, not just the label."""
    review_content = (
        "```yaml\n"
        "max_rounds: 5\n"
        "min_coverage: 80\n"
        "gate_thresholds:\n"
        "  Brainstorm: 0.5\n"
        "```\n"
    )
    policy_dir = _policy_dir_with_review(tmp_path, review_content)
    engine = Engine(policy_pack_path=str(policy_dir))

    # Same 0.6 score that failed against the 0.80 default now passes at 0.5.
    passed, score = engine.check_gate(
        Phase.BRAINSTORM,
        {
            "alternative_approaches_considered": True,
            "risks_identified": True,
            "success_criteria_defined": False,
            "reversibility_assessed": False,
        },
    )
    assert passed
    assert abs(score - 0.6) < 1e-9

    # Plan threshold wasn't overridden, so it keeps the 0.90 default.
    assert engine._gate_evidence_policy.threshold_for("Plan") == 0.90


def test_engine_attach_gate_result_honors_custom_remediation_text(tmp_path: Path):
    """A review.md gate_remediation override changes the surfaced remediation string."""
    custom_message = "Custom remediation: please justify the missing risk assessment."
    review_content = (
        "```yaml\n"
        "max_rounds: 5\n"
        "min_coverage: 80\n"
        "gate_remediation:\n"
        f"  risks_identified: \"{custom_message}\"\n"
        "```\n"
    )
    policy_dir = _policy_dir_with_review(tmp_path, review_content)
    engine = Engine(policy_pack_path=str(policy_dir))

    result = PhaseResult(
        phase=Phase.BRAINSTORM,
        outcome="pass",
        evidence={
            "alternative_approaches_considered": True,
            "risks_identified": False,
            "success_criteria_defined": True,
            "reversibility_assessed": True,
        },
    )
    engine._attach_gate_result(result)
    remediation = result.artifacts["gate_result"]["remediation"]
    assert remediation["risks_identified"] == custom_message


def test_engine_gate_retry_phases_can_be_overridden_to_disable_gating(tmp_path: Path):
    """A review.md gate_retry_phases override can remove a phase from gating entirely."""
    review_content = (
        "```yaml\n"
        "max_rounds: 5\n"
        "min_coverage: 80\n"
        "gate_retry_phases:\n"
        "  - Plan\n"
        "```\n"
    )
    policy_dir = _policy_dir_with_review(tmp_path, review_content)
    engine = Engine(policy_pack_path=str(policy_dir))

    assert not engine._gate_evidence_policy.is_retry_phase("Brainstorm")
    assert engine._gate_evidence_policy.is_retry_phase("Plan")

    result = PhaseResult(
        phase=Phase.BRAINSTORM,
        outcome="pass",
        evidence={"risks_identified": False},
    )
    engine._attach_gate_result(result)
    # Brainstorm is no longer a gated phase, so no gate_result is attached at all.
    assert "gate_result" not in result.artifacts
