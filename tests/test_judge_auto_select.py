"""Tests for JUDGE's deterministic lone-survivor auto-select.

Opt-in via judge_scoring.auto_select_lone_survivor: when local verification
already leaves exactly one candidate passing and every other candidate
explicitly failing, the JUDGE dispatch is skipped and that candidate is
declared the winner deterministically -- see lone_verified_survivor() in
src/runtime/judge_scoring.py.
"""
from __future__ import annotations

from pathlib import Path

from src.runtime import TaskGraphExecutor
from src.runtime.contracts import DispatchResponse
from src.runtime.judge_scoring import JudgeScoringPolicy, lone_verified_survivor
from src.task_graph import graph_from_workflow


def _bakeoff_workflow() -> dict:
    return {
        "nodes": [
            {
                "id": "fan",
                "title": "Implement across providers",
                "node_type": "fanout",
                "pattern_config": {"count": 2, "providers": ["provider-a", "provider-b"]},
            },
            {
                "id": "judge",
                "title": "Judge",
                "node_type": "judge",
                "depends_on": ["fan-synthesize"],
            },
        ]
    }


class _VerifiedBranchDispatcher:
    """Branch dispatches carry an explicit pass/fail verification_summary."""

    def __init__(self, pass_map: dict[str, bool | None]):
        self.pass_map = pass_map
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        task_id = request.task_id
        if task_id in self.pass_map:
            passed = self.pass_map[task_id]
            evidence: dict = {"workspace_delta": {"measured": True, "change_count": 1}}
            if passed is not None:
                evidence["verification_summary"] = {"command_succeeded": passed}
            return DispatchResponse(
                success=True,
                outputs={"work_unit_result": "done"},
                evidence=evidence,
                artifacts={"provider": f"provider-{task_id[-1]}"},
            )
        if task_id == "judge":
            return DispatchResponse(success=True, outputs={"winner": "fan-branch-1"})
        return DispatchResponse(success=True, outputs={})


def _auto_select_policy(*, enabled: bool = True) -> JudgeScoringPolicy:
    return JudgeScoringPolicy(
        weights={"test_pass_rate": 1.0},
        prefer={"test_pass_rate": "high"},
        auto_select_lone_survivor=enabled,
    )


def test_auto_selects_lone_survivor_without_dispatching_judge(tmp_path: Path):
    dispatcher = _VerifiedBranchDispatcher({"fan-branch-1": True, "fan-branch-2": False})
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_auto_select_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    result = executor.execute_all(graph).to_artifact()

    assert not any(r.task_id == "judge" for r in dispatcher.requests)

    judge_node = next(n for n in result["graph_state"]["nodes"] if n["id"] == "judge")
    assert judge_node["status"] == "completed"
    assert judge_node["last_provider_result"]["outputs"]["winner"] == "fan-branch-1"
    assert judge_node["last_provider_result"]["evidence"]["auto_selected"] is True

    winner_node = next(n for n in result["graph_state"]["nodes"] if n["id"] == "judge-winner")
    assert winner_node["pattern_config"]["judge_output"]["winner"] == "fan-branch-1"


def test_auto_select_still_records_bakeoff_history(tmp_path: Path):
    dispatcher = _VerifiedBranchDispatcher({"fan-branch-1": True, "fan-branch-2": False})
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_auto_select_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    history_path = tmp_path / ".sarathi" / "bakeoff_history.json"
    assert history_path.exists()
    import json
    history = json.loads(history_path.read_text())
    assert history[-1]["winner_branch"] == "fan-branch-1"


def test_dispatches_judge_when_both_candidates_pass(tmp_path: Path):
    """Ambiguous: two candidates both pass -- a real judgment call remains."""
    dispatcher = _VerifiedBranchDispatcher({"fan-branch-1": True, "fan-branch-2": True})
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_auto_select_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    assert any(r.task_id == "judge" for r in dispatcher.requests)


def test_dispatches_judge_when_both_candidates_fail(tmp_path: Path):
    dispatcher = _VerifiedBranchDispatcher({"fan-branch-1": False, "fan-branch-2": False})
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_auto_select_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    assert any(r.task_id == "judge" for r in dispatcher.requests)


def test_dispatches_judge_when_a_candidate_has_no_verification_signal(tmp_path: Path):
    """An unmeasured candidate is never assumed to have failed."""
    dispatcher = _VerifiedBranchDispatcher({"fan-branch-1": True, "fan-branch-2": None})
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_auto_select_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    assert any(r.task_id == "judge" for r in dispatcher.requests)


def test_dispatches_judge_when_auto_select_not_enabled(tmp_path: Path):
    """Opt-in only: a lone survivor doesn't skip dispatch unless the policy asks for it."""
    dispatcher = _VerifiedBranchDispatcher({"fan-branch-1": True, "fan-branch-2": False})
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_auto_select_policy(enabled=False),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    assert any(r.task_id == "judge" for r in dispatcher.requests)


# ── lone_verified_survivor() unit tests ─────────────────────────────────

def test_lone_verified_survivor_returns_the_sole_passer():
    scorecard = [
        {"branch": "a", "test_pass_rate": 1.0},
        {"branch": "b", "test_pass_rate": 0.0},
        {"branch": "c", "test_pass_rate": 0.0},
    ]
    assert lone_verified_survivor(scorecard) == "a"


def test_lone_verified_survivor_none_on_tie():
    scorecard = [{"branch": "a", "test_pass_rate": 1.0}, {"branch": "b", "test_pass_rate": 1.0}]
    assert lone_verified_survivor(scorecard) is None


def test_lone_verified_survivor_none_when_all_fail():
    scorecard = [{"branch": "a", "test_pass_rate": 0.0}, {"branch": "b", "test_pass_rate": 0.0}]
    assert lone_verified_survivor(scorecard) is None


def test_lone_verified_survivor_none_on_missing_signal():
    scorecard = [{"branch": "a", "test_pass_rate": 1.0}, {"branch": "b", "test_pass_rate": None}]
    assert lone_verified_survivor(scorecard) is None


def test_lone_verified_survivor_none_on_partial_pass_rate():
    """A fractional rate (partial test pass) is neither a clean win nor loss."""
    scorecard = [{"branch": "a", "test_pass_rate": 1.0}, {"branch": "b", "test_pass_rate": 0.5}]
    assert lone_verified_survivor(scorecard) is None


def test_lone_verified_survivor_empty_scorecard():
    assert lone_verified_survivor([]) is None
