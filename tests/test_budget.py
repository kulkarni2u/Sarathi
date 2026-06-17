"""Tests for per-task token budget enforcement."""

from __future__ import annotations

from pathlib import Path

from src.engine import Complexity, Engine, PersistenceManager, Phase, TaskContext
from src.runtime.budget import TaskBudget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_policy_dir(tmp_path: Path, escalation_extra: str = "") -> Path:
    policy_dir = tmp_path / "policy-pack"
    policy_dir.mkdir()
    (policy_dir / "complexity.md").write_text("classification_thresholds: present\nskip_rules: present\n")
    (policy_dir / "conventions.md").write_text("conventions: present\nbrainstorming_protocol: present\n")
    (policy_dir / "commands.md").write_text("# Commands\n")
    (policy_dir / "review.md").write_text("max_rounds: 5\nmin_coverage: 80\n")
    (policy_dir / "escalation.md").write_text(
        "```yaml\n"
        "retry_budgets:\n"
        "  verify: 2\n"
        "  review: 1\n"
        f"{escalation_extra}"
        "```\n"
    )
    (policy_dir / "skills.md").write_text("pattern_detection: enabled\nevolution_threshold: 0.8\n")
    (policy_dir / "task-tracking.md").write_text("task: configured\noptions: configured\n")
    return policy_dir


def _engine(tmp_path: Path, escalation_extra: str = "") -> Engine:
    engine = Engine(policy_pack_path=str(_minimal_policy_dir(tmp_path, escalation_extra)), ncp_enabled=False)
    engine.persistence = PersistenceManager(str(tmp_path / "tasks"))
    return engine


# ---------------------------------------------------------------------------
# TaskBudget.from_escalation
# ---------------------------------------------------------------------------

def test_from_escalation_missing_budget_disabled():
    budget = TaskBudget.from_escalation({"retry_budgets": {"verify": 2}})
    assert budget.state() == "disabled"


def test_from_escalation_non_dict_input_disabled():
    budget = TaskBudget.from_escalation(None)
    assert budget.state() == "disabled"
    budget = TaskBudget.from_escalation("not-a-dict")
    assert budget.state() == "disabled"


def test_from_escalation_with_max_is_ok_initially():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    assert budget.state() == "ok"
    assert budget.max_total_tokens == 1000
    assert budget.warn_ratio == 0.8
    assert budget.on_exhausted == "pause"


def test_accumulation_crossing_warn_ratio():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000, "warn_ratio": 0.5}})
    budget.add_usage({"total_tokens": 400})
    assert budget.state() == "ok"
    budget.add_usage({"total_tokens": 200})
    assert budget.consumed_tokens == 600
    assert budget.state() == "warning"


def test_accumulation_crossing_max_is_exhausted():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    budget.add_usage({"total_tokens": 999})
    assert budget.state() in ("ok", "warning")
    budget.add_usage({"total_tokens": 1})
    assert budget.consumed_tokens == 1000
    assert budget.state() == "exhausted"


def test_add_usage_defensive_with_none_and_garbage():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    budget.add_usage(None)
    budget.add_usage("not-a-dict")
    budget.add_usage({})
    budget.add_usage({"total_tokens": "not-an-int"})
    budget.add_usage(123)
    budget.add_usage([1, 2, 3])
    assert budget.consumed_tokens == 0
    assert budget.state() == "ok"


def test_on_exhausted_validation_and_default():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000, "on_exhausted": "warn"}})
    assert budget.on_exhausted == "warn"

    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000, "on_exhausted": "bogus"}})
    assert budget.on_exhausted == "pause"

    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    assert budget.on_exhausted == "pause"


def test_to_artifact_shape():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000, "warn_ratio": 0.5, "on_exhausted": "warn"}})
    budget.add_usage({"total_tokens": 100})
    artifact = budget.to_artifact()
    assert artifact == {
        "enforcement": "enabled",
        "max_total_tokens": 1000,
        "warn_ratio": 0.5,
        "consumed_tokens": 100,
        "state": "ok",
        "on_exhausted": "warn",
    }


def test_to_artifact_disabled():
    budget = TaskBudget.from_escalation({})
    artifact = budget.to_artifact()
    assert artifact["enforcement"] == "disabled"
    assert artifact["state"] == "disabled"


# ---------------------------------------------------------------------------
# add_phase_result_usage
# ---------------------------------------------------------------------------

def test_add_phase_result_usage_direct_dispatch_usage():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    artifacts = {"dispatch_usage": {"total_tokens": 50, "provider_id": "p1"}}
    budget.add_phase_result_usage(artifacts)
    assert budget.consumed_tokens == 50


def test_add_phase_result_usage_nested_graph_events():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    artifacts = {
        "task_graph_execution": {
            "events": [
                {"provider_result": {"usage": {"total_tokens": 30}}},
                {"provider_result": {"usage": {"total_tokens": 20}}},
                {"provider_result": {}},
                "not-a-dict",
            ]
        }
    }
    budget.add_phase_result_usage(artifacts)
    assert budget.consumed_tokens == 50


def test_add_phase_result_usage_combines_direct_and_nested():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    artifacts = {
        "dispatch_usage": {"total_tokens": 10},
        "task_graph_execution": {
            "events": [
                {"provider_result": {"usage": {"total_tokens": 5}}},
            ]
        },
    }
    budget.add_phase_result_usage(artifacts)
    assert budget.consumed_tokens == 15


def test_add_phase_result_usage_defensive():
    budget = TaskBudget.from_escalation({"budget": {"max_total_tokens": 1000}})
    budget.add_phase_result_usage(None)
    budget.add_phase_result_usage({})
    budget.add_phase_result_usage({"task_graph_execution": "not-a-dict"})
    budget.add_phase_result_usage({"task_graph_execution": {"events": "not-a-list"}})
    assert budget.consumed_tokens == 0


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------

def test_engine_pauses_when_budget_exhausted(tmp_path: Path):
    engine = _engine(
        tmp_path,
        escalation_extra=(
            "\nbudget:\n"
            "  max_total_tokens: 1\n"
            "  on_exhausted: pause\n"
        ),
    )
    task = TaskContext(
        task_id="budget-pause",
        description="Implement a feature that does something",
        complexity=Complexity.LOW,
    )
    result = engine.run_task(task)

    # A full LOW-complexity run produces 12 phase results; the budget should
    # have stopped execution well before that.
    assert len(result.phase_results) < 12
    assert result.current_phase is not None  # resumable

    last = result.phase_results[-1]
    assert "budget_exhausted" in last.artifacts
    exhausted = last.artifacts["budget_exhausted"]
    assert exhausted["state"] == "exhausted"
    assert exhausted["enforcement"] == "enabled"

    assert result.budget_snapshot is not None
    assert result.budget_snapshot["state"] == "exhausted"

    # Learn phase must NOT have run yet.
    assert Phase.LEARN not in result.get_completed_phases()


def test_engine_resume_after_budget_pause(tmp_path: Path):
    engine = _engine(
        tmp_path,
        escalation_extra=(
            "\nbudget:\n"
            "  max_total_tokens: 1\n"
            "  on_exhausted: pause\n"
        ),
    )
    task = TaskContext(
        task_id="budget-resume",
        description="Implement a feature that does something",
        complexity=Complexity.LOW,
    )
    paused = engine.run_task(task)
    assert paused.current_phase is not None

    resumed = engine.resume_task(paused)
    assert Phase.LEARN in resumed.get_completed_phases()


def test_engine_warns_but_continues_when_on_exhausted_is_warn(tmp_path: Path):
    engine = _engine(
        tmp_path,
        escalation_extra=(
            "\nbudget:\n"
            "  max_total_tokens: 1\n"
            "  on_exhausted: warn\n"
        ),
    )
    task = TaskContext(
        task_id="budget-warn",
        description="Implement a feature that does something",
        complexity=Complexity.LOW,
    )
    result = engine.run_task(task)

    # Full phase list still runs.
    assert len(result.phase_results) == 12
    assert Phase.LEARN in result.get_completed_phases()
    assert result.current_phase is None

    # At least one phase result should carry the exhausted artifact.
    exhausted_results = [pr for pr in result.phase_results if "budget_exhausted" in pr.artifacts]
    assert exhausted_results
    assert result.budget_snapshot is not None
    assert result.budget_snapshot["state"] == "exhausted"


def test_engine_no_budget_configured_behaves_like_today(tmp_path: Path):
    engine = _engine(tmp_path)  # no budget: section
    task = TaskContext(
        task_id="budget-none",
        description="Implement a feature that does something",
        complexity=Complexity.LOW,
    )
    result = engine.run_task(task)

    assert len(result.phase_results) == 12
    assert Phase.LEARN in result.get_completed_phases()
    assert result.current_phase is None

    for pr in result.phase_results:
        assert "budget_exhausted" not in pr.artifacts

    assert result.budget_snapshot is not None
    assert result.budget_snapshot["enforcement"] == "disabled"
    assert result.budget_snapshot["state"] == "disabled"
