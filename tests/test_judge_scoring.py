"""Measured JUDGE scoring + bake-off routing feedback (Implementation Plan 2.3).

Covers:
  - JudgeScoringPolicy.from_review parsing + weight-sum validation.
  - Scorecard assembly from fake branch evidence: deterministic scores,
    prefer-direction handling, missing signals handled gracefully.
  - Absent scoring policy -> no scorecard, byte-for-byte prior behavior.
  - The judge dispatch's context/inputs actually carry the scorecard.
  - Winner recording into `.sarathi/bakeoff_history.json` (atomic, appends).
  - Evolver.propose_from_bakeoff_history firing at the win/win-rate threshold
    and not below it, targeting model-routing.md with evidence in rationale.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.evolve import EvolutionPolicy, Evolver
from src.runtime import TaskGraphExecutor
from src.runtime.contracts import DispatchResponse, UsageRecord
from src.runtime.judge_scoring import (
    BakeoffHistoryStore,
    JudgeScoringPolicy,
    assemble_judge_scorecard,
    build_scorecard,
    collect_branch_node_ids,
    format_scorecard_for_prompt,
)
from src.task_graph import graph_from_workflow


# ---------------------------------------------------------------------------
# JudgeScoringPolicy.from_review
# ---------------------------------------------------------------------------


def test_from_review_returns_none_when_block_absent():
    assert JudgeScoringPolicy.from_review({}) is None
    assert JudgeScoringPolicy.from_review(None) is None
    assert JudgeScoringPolicy.from_review({"max_rounds": 3}) is None


def test_from_review_returns_none_when_weights_missing_or_unusable():
    assert JudgeScoringPolicy.from_review({"judge_scoring": {}}) is None
    assert JudgeScoringPolicy.from_review({"judge_scoring": {"weights": "nope"}}) is None
    assert JudgeScoringPolicy.from_review({"judge_scoring": {"weights": {"cost_usd": "not-a-number"}}}) is None


def test_from_review_parses_weights_and_prefer():
    policy = JudgeScoringPolicy.from_review(
        {
            "judge_scoring": {
                "weights": {
                    "test_pass_rate": 0.4,
                    "blast_radius": 0.2,
                    "cost_usd": 0.2,
                    "latency_ms": 0.2,
                },
                "prefer": {
                    "test_pass_rate": "high",
                    "blast_radius": "low",
                    "cost_usd": "low",
                    "latency_ms": "low",
                },
            }
        }
    )
    assert policy is not None
    assert policy.weights == {
        "test_pass_rate": 0.4,
        "blast_radius": 0.2,
        "cost_usd": 0.2,
        "latency_ms": 0.2,
    }
    assert policy.prefer == {
        "test_pass_rate": "high",
        "blast_radius": "low",
        "cost_usd": "low",
        "latency_ms": "low",
    }
    assert policy.validation_issue is None


def test_from_review_defaults_missing_prefer_to_high_and_rejects_bad_direction():
    policy = JudgeScoringPolicy.from_review(
        {
            "judge_scoring": {
                "weights": {"cost_usd": 0.5, "test_pass_rate": 0.5},
                "prefer": {"cost_usd": "sideways"},
            }
        }
    )
    assert policy is not None
    # "sideways" isn't a valid direction -> falls back to the "high" default.
    assert policy.prefer["cost_usd"] == "high"
    # test_pass_rate wasn't in `prefer` at all -> also defaults to "high".
    assert policy.prefer["test_pass_rate"] == "high"


def test_from_review_flags_weights_not_summing_to_one():
    policy = JudgeScoringPolicy.from_review(
        {"judge_scoring": {"weights": {"cost_usd": 0.9, "latency_ms": 0.9}}}
    )
    assert policy is not None
    assert policy.validation_issue is not None
    assert "1.0" in policy.validation_issue or "1" in policy.validation_issue


def test_from_review_drops_negative_and_non_numeric_weight_entries():
    policy = JudgeScoringPolicy.from_review(
        {
            "judge_scoring": {
                "weights": {
                    "cost_usd": 0.5,
                    "latency_ms": 0.5,
                    "bogus": "nan-ish",
                    "negative": -1.0,
                }
            }
        }
    )
    assert policy is not None
    assert set(policy.weights) == {"cost_usd", "latency_ms"}


# ---------------------------------------------------------------------------
# Scorecard assembly: deterministic scores, prefer handling, missing signals
# ---------------------------------------------------------------------------


def test_build_scorecard_prefers_low_and_handles_missing_signal_gracefully():
    policy = JudgeScoringPolicy(
        weights={"cost_usd": 0.5, "test_pass_rate": 0.5},
        prefer={"cost_usd": "low", "test_pass_rate": "high"},
    )
    entries = [
        {"branch": "b1", "cost_usd": 1.0, "test_pass_rate": 1.0},
        # b2 has no test_pass_rate at all -- must not be penalized/rewarded
        # for a signal it never reported; only cost_usd should count for it.
        {"branch": "b2", "cost_usd": 2.0, "test_pass_rate": None},
    ]
    scorecard = build_scorecard(policy, entries)
    by_branch = {entry["branch"]: entry for entry in scorecard}

    # b1: cheapest (norm 0, prefer low -> score 1.0) and only test_pass_rate
    # value present across branches -> tied with itself -> neutral 0.5.
    assert by_branch["b1"]["signal_scores"]["cost_usd"] == 1.0
    assert by_branch["b1"]["signal_scores"]["test_pass_rate"] == 0.5
    assert by_branch["b1"]["weighted_score"] == 0.75

    # b2: most expensive (norm 1, prefer low -> score 0.0); test_pass_rate
    # excluded entirely from its weighted average (renormalized denominator).
    assert by_branch["b2"]["signal_scores"]["cost_usd"] == 0.0
    assert "test_pass_rate" not in by_branch["b2"]["signal_scores"]
    assert by_branch["b2"]["weighted_score"] == 0.0

    # Deterministic: recomputing from the same inputs gives the same result.
    assert build_scorecard(policy, entries) == scorecard


def test_build_scorecard_ties_score_neutral_when_all_branches_equal():
    policy = JudgeScoringPolicy(weights={"cost_usd": 1.0}, prefer={"cost_usd": "low"})
    entries = [{"branch": "b1", "cost_usd": 3.0}, {"branch": "b2", "cost_usd": 3.0}]
    scorecard = build_scorecard(policy, entries)
    assert all(entry["weighted_score"] == 0.5 for entry in scorecard)


def test_build_scorecard_branch_with_no_signals_gets_no_weighted_score():
    policy = JudgeScoringPolicy(weights={"cost_usd": 1.0}, prefer={"cost_usd": "low"})
    entries = [{"branch": "b1", "cost_usd": 3.0}, {"branch": "b2"}]
    scorecard = build_scorecard(policy, entries)
    by_branch = {entry["branch"]: entry for entry in scorecard}
    assert by_branch["b2"]["weighted_score"] is None
    assert by_branch["b2"]["signal_scores"] == {}


def _branch_node(node_id: str, *, provider: str, cost_usd, latency_ms, change_count, test_pass_rate=None):
    outputs = {"work_unit_result": "done"}
    if test_pass_rate is not None:
        outputs["test_pass_rate"] = test_pass_rate
    return {
        "id": node_id,
        "node_type": "execute",
        "pattern_config": {"provider": provider},
        "last_provider_result": {
            "outputs": outputs,
            "evidence": {"workspace_delta": {"measured": True, "change_count": change_count}},
            "artifacts": {"provider": provider, "provider_duration_ms": latency_ms},
            "usage": {"cost_usd": cost_usd},
        },
    }


def test_assemble_judge_scorecard_walks_synthesize_source_ids():
    graph = {
        "nodes": [
            _branch_node("fan-branch-1", provider="provider-a", cost_usd=0.10, latency_ms=1000, change_count=2),
            _branch_node("fan-branch-2", provider="provider-b", cost_usd=0.50, latency_ms=4000, change_count=8),
            {
                "id": "fan-synthesize",
                "node_type": "synthesize",
                "pattern_config": {"source_ids": ["fan-branch-1", "fan-branch-2"]},
            },
            {
                "id": "judge",
                "node_type": "judge",
                "depends_on": ["fan-synthesize"],
                "pattern_config": {},
            },
        ]
    }
    policy = JudgeScoringPolicy(
        weights={"blast_radius": 0.5, "cost_usd": 0.3, "latency_ms": 0.2},
        prefer={"blast_radius": "low", "cost_usd": "low", "latency_ms": "low"},
    )
    judge_node = next(n for n in graph["nodes"] if n["id"] == "judge")

    branch_ids = collect_branch_node_ids(judge_node, graph)
    assert branch_ids == ["fan-branch-1", "fan-branch-2"]

    scorecard = assemble_judge_scorecard(policy, judge_node, graph)
    assert {entry["branch"] for entry in scorecard} == {"fan-branch-1", "fan-branch-2"}
    by_branch = {entry["branch"]: entry for entry in scorecard}
    # branch-1 wins on every present signal -> strictly higher weighted score.
    assert by_branch["fan-branch-1"]["weighted_score"] > by_branch["fan-branch-2"]["weighted_score"]
    assert by_branch["fan-branch-1"]["provider"] == "provider-a"
    assert by_branch["fan-branch-2"]["provider"] == "provider-b"

    lines = format_scorecard_for_prompt(scorecard)
    assert any("fan-branch-1" in line and "provider-a" in line for line in lines)


def test_assemble_judge_scorecard_honors_explicit_competitor_ids():
    graph = {
        "nodes": [
            _branch_node("a", provider="p1", cost_usd=1.0, latency_ms=100, change_count=1),
            _branch_node("b", provider="p2", cost_usd=2.0, latency_ms=200, change_count=2),
        ]
    }
    judge_node = {"id": "jdg", "node_type": "judge", "pattern_config": {"competitor_ids": ["a", "b"]}}
    policy = JudgeScoringPolicy(weights={"cost_usd": 1.0}, prefer={"cost_usd": "low"})
    scorecard = assemble_judge_scorecard(policy, judge_node, graph)
    assert {entry["branch"] for entry in scorecard} == {"a", "b"}


def test_assemble_judge_scorecard_empty_without_policy_or_branches():
    assert assemble_judge_scorecard(None, {"id": "jdg"}, {"nodes": []}) == []
    policy = JudgeScoringPolicy(weights={"cost_usd": 1.0}, prefer={"cost_usd": "low"})
    assert assemble_judge_scorecard(policy, {"id": "jdg", "depends_on": []}, {"nodes": []}) == []


# ---------------------------------------------------------------------------
# TaskGraphExecutor integration: FANOUT -> SYNTHESIZE -> JUDGE
# ---------------------------------------------------------------------------


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


class _ScoringDispatcher:
    """Fake dispatcher wired so each branch carries distinct measured signals."""

    def __init__(self):
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        task_id = request.task_id
        if task_id == "fan-branch-1":
            return DispatchResponse(
                success=True,
                outputs={"work_unit_result": "done"},
                evidence={"workspace_delta": {"measured": True, "change_count": 2}},
                artifacts={"provider": "provider-a", "provider_duration_ms": 1000},
                usage=UsageRecord(
                    provider_id="provider-a",
                    provider_family="cli",
                    dispatch_id=task_id,
                    estimated=False,
                    cost_usd=0.10,
                ),
            )
        if task_id == "fan-branch-2":
            return DispatchResponse(
                success=True,
                outputs={"work_unit_result": "done"},
                evidence={"workspace_delta": {"measured": True, "change_count": 8}},
                artifacts={"provider": "provider-b", "provider_duration_ms": 4000},
                usage=UsageRecord(
                    provider_id="provider-b",
                    provider_family="cli",
                    dispatch_id=task_id,
                    estimated=False,
                    cost_usd=0.50,
                ),
            )
        if task_id == "judge":
            return DispatchResponse(success=True, outputs={"winner": "fan-branch-1"})
        return DispatchResponse(success=True, outputs={})


def _scoring_policy() -> JudgeScoringPolicy:
    return JudgeScoringPolicy(
        weights={"blast_radius": 0.4, "cost_usd": 0.3, "latency_ms": 0.3},
        prefer={"blast_radius": "low", "cost_usd": "low", "latency_ms": "low"},
    )


def test_judge_dispatch_context_carries_scorecard(tmp_path: Path):
    dispatcher = _ScoringDispatcher()
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_scoring_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    judge_request = next(r for r in dispatcher.requests if r.task_id == "judge")
    scorecard = judge_request.inputs.get("judge_scorecard")
    assert scorecard, "judge dispatch inputs must carry the assembled scorecard"
    assert {entry["branch"] for entry in scorecard} == {"fan-branch-1", "fan-branch-2"}

    prior_findings = judge_request.context_pack.get("agent_input", {}).get("prior_findings", [])
    assert any("Judge scorecard" in line for line in prior_findings)


def test_judge_scorecard_recorded_on_node_artifacts(tmp_path: Path):
    dispatcher = _ScoringDispatcher()
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_scoring_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    result = executor.execute_all(graph).to_artifact()

    judge_node = next(n for n in result["graph_state"]["nodes"] if n["id"] == "judge")
    scorecard = judge_node["last_provider_result"]["artifacts"]["judge_scorecard"]
    assert {entry["branch"] for entry in scorecard} == {"fan-branch-1", "fan-branch-2"}


def test_absent_scoring_policy_produces_no_scorecard_and_prior_behavior_intact(tmp_path: Path):
    """No judge_scoring_policy -> byte-for-byte today's JUDGE behavior."""
    dispatcher = _ScoringDispatcher()
    executor = TaskGraphExecutor(dispatcher=dispatcher, isolation_repo_root=tmp_path)
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    result = executor.execute_all(graph).to_artifact()

    judge_request = next(r for r in dispatcher.requests if r.task_id == "judge")
    assert "judge_scorecard" not in judge_request.inputs

    judge_node = next(n for n in result["graph_state"]["nodes"] if n["id"] == "judge")
    assert "judge_scorecard" not in judge_node["last_provider_result"]["artifacts"]

    # No scoring policy -> no bake-off history should ever be written.
    assert not (tmp_path / ".sarathi" / "bakeoff_history.json").exists()

    # The winner-propagation node still gets injected as before.
    assert "judge-winner" in result["graph_state"]["completed_nodes"]


# ---------------------------------------------------------------------------
# Winner recording into .sarathi/bakeoff_history.json
# ---------------------------------------------------------------------------


def test_winner_recorded_into_bakeoff_history_atomically(tmp_path: Path):
    from src.harness import HarnessConfig
    from src.task_class import TaskClass

    harness_config = HarnessConfig(task_id="t1", task_class=TaskClass.MUTATION_CONFIG)
    dispatcher = _ScoringDispatcher()
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        judge_scoring_policy=_scoring_policy(),
        isolation_repo_root=tmp_path,
        harness_config=harness_config,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)

    history_path = tmp_path / ".sarathi" / "bakeoff_history.json"
    assert history_path.exists()
    assert not history_path.with_suffix(".json.tmp").exists()

    history = json.loads(history_path.read_text())
    assert len(history) == 1
    record = history[0]
    assert record["task_class"] == "mutation/config"
    assert record["winner_branch"] == "fan-branch-1"
    assert record["provider"] == "provider-a"
    assert isinstance(record["weighted_score"], float)
    assert record["scorecard"]

    # Running a second judged bake-off appends rather than overwriting.
    dispatcher2 = _ScoringDispatcher()
    executor2 = TaskGraphExecutor(
        dispatcher=dispatcher2,
        judge_scoring_policy=_scoring_policy(),
        isolation_repo_root=tmp_path,
        harness_config=harness_config,
    )
    graph2 = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor2.execute_all(graph2)
    history_after = json.loads(history_path.read_text())
    assert len(history_after) == 2


def test_no_winner_recorded_when_output_winner_does_not_match_a_branch(tmp_path: Path):
    class _NoMatchDispatcher(_ScoringDispatcher):
        def dispatch(self, request):
            if request.task_id == "judge":
                self.requests.append(request)
                return DispatchResponse(success=True, outputs={"winner": "not-a-real-branch"})
            return super().dispatch(request)

    executor = TaskGraphExecutor(
        dispatcher=_NoMatchDispatcher(),
        judge_scoring_policy=_scoring_policy(),
        isolation_repo_root=tmp_path,
    )
    graph = graph_from_workflow(_bakeoff_workflow()).to_artifact()
    executor.execute_all(graph)
    assert not (tmp_path / ".sarathi" / "bakeoff_history.json").exists()


def test_bakeoff_history_store_load_tolerates_missing_and_corrupt_file(tmp_path: Path):
    store = BakeoffHistoryStore(tmp_path)
    assert store.load() == []

    (tmp_path / "bakeoff_history.json").write_text("not json")
    assert store.load() == []


# ---------------------------------------------------------------------------
# Evolver.propose_from_bakeoff_history: routing-feedback proposal threshold
# ---------------------------------------------------------------------------


def _history(task_class: str, provider: str, wins: int, losses: int, other_provider: str = "other") -> list[dict]:
    records = [
        {"task_class": task_class, "provider": provider, "weighted_score": 0.9}
        for _ in range(wins)
    ]
    records.extend(
        {"task_class": task_class, "provider": other_provider, "weighted_score": 0.4}
        for _ in range(losses)
    )
    return records


def test_propose_from_bakeoff_history_empty_or_none_yields_no_proposals():
    evolver = Evolver()
    assert evolver.propose_from_bakeoff_history(None) == []
    assert evolver.propose_from_bakeoff_history([]) == []


def test_propose_from_bakeoff_history_below_win_threshold_does_not_fire():
    evolver = Evolver()
    # 4 wins, 0 losses: 100% win rate but below the default min_wins=5.
    history = _history("mutation/config", "codex", wins=4, losses=0)
    assert evolver.propose_from_bakeoff_history(history) == []


def test_propose_from_bakeoff_history_below_win_rate_does_not_fire():
    evolver = Evolver()
    # 5 wins, 5 losses: meets min_wins but only 50% win rate (< 0.7 default).
    history = _history("mutation/config", "codex", wins=5, losses=5)
    assert evolver.propose_from_bakeoff_history(history) == []


def test_propose_from_bakeoff_history_fires_at_threshold():
    evolver = Evolver()
    # 5 wins, 1 loss: meets min_wins=5 and win_rate ~= 0.833 >= 0.7.
    history = _history("mutation/config", "codex", wins=5, losses=1)
    proposals = evolver.propose_from_bakeoff_history(history)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.policy_file == "model-routing.md"
    assert "codex" in proposal.title
    assert "mutation/config" in proposal.title
    assert "5 of 6" in proposal.rationale
    assert "codex" in proposal.rationale
    assert proposal.routing_hint["preferred_provider"] == "codex"
    assert proposal.routing_hint["task_class"] == "mutation/config"
    assert proposal.source == "bakeoff_history"


def test_propose_from_bakeoff_history_respects_custom_thresholds():
    evolver = Evolver()
    history = _history("codegen/patch", "opencode", wins=3, losses=1)
    assert evolver.propose_from_bakeoff_history(history) == []
    proposals = evolver.propose_from_bakeoff_history(history, min_wins=3, min_win_rate=0.5)
    assert len(proposals) == 1
    assert proposals[0].routing_hint["preferred_provider"] == "opencode"


def test_propose_from_bakeoff_history_configurable_via_evolution_policy():
    policy = EvolutionPolicy.from_escalation(
        {"learn_evolve": {"bakeoff_min_wins": 2, "bakeoff_min_win_rate": 0.5}}
    )
    assert policy.bakeoff_min_wins == 2
    assert policy.bakeoff_min_win_rate == 0.5
    evolver = Evolver(policy)
    history = _history("analysis", "gateway-a", wins=2, losses=1)
    proposals = evolver.propose_from_bakeoff_history(history)
    assert len(proposals) == 1
    assert proposals[0].routing_hint["preferred_provider"] == "gateway-a"


def test_generate_policy_proposals_wires_bakeoff_history_additively():
    evolver = Evolver()
    history = _history("mutation/config", "codex", wins=5, losses=1)
    without_history = evolver.generate_policy_proposals()
    with_history = evolver.generate_policy_proposals(bakeoff_history=history)
    assert without_history == []
    assert len(with_history) == 1
    assert with_history[0].policy_file == "model-routing.md"


# ---------------------------------------------------------------------------
# LearnHandler wiring: workspace_root -> bake-off history -> proposals
# ---------------------------------------------------------------------------


def test_learn_handler_loads_bakeoff_history_when_workspace_root_given(tmp_path: Path):
    from src.phases.learn import LearnHandler

    store = BakeoffHistoryStore(tmp_path / ".sarathi")
    for _ in range(6):
        store.record(
            task_class="mutation/config",
            judge_node_id="judge",
            winner_branch="fan-branch-1",
            provider="codex",
            weighted_score=0.9,
            scorecard=[],
        )

    class _StubPolicyPack:
        escalation: dict = {}

    handler = LearnHandler(_StubPolicyPack(), workspace_root=tmp_path)
    history = handler._load_bakeoff_history()
    assert history is not None
    assert len(history) == 6


def test_learn_handler_without_workspace_root_skips_bakeoff_history():
    from src.phases.learn import LearnHandler

    class _StubPolicyPack:
        escalation: dict = {}

    handler = LearnHandler(_StubPolicyPack())
    assert handler._load_bakeoff_history() is None
