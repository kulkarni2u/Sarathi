"""Per-branch provider FANOUT + measured judged result (T5.3).

Verifies that a FANOUT node's ``pattern_config.providers`` round-robins distinct
providers onto its branches, that ``_dispatch_node`` threads each branch's
provider into the dispatch constraints, and that the shipped orchestrator recipe
fans out across >=2 providers and produces a judged, merged, measured result.
"""
from __future__ import annotations

from pathlib import Path

from src.runtime import TaskGraphExecutor
from src.runtime.contracts import DispatchResponse, UsageRecord
from src.runtime.recipes import load_recipe
from src.task_graph import graph_from_workflow

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = REPO_ROOT / "policy-pack" / "RECIPES"


class RecordingDispatcher:
    """Captures every request and echoes the routed provider back in outputs."""

    def __init__(self):
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        provider = request.constraints.get("provider")
        return DispatchResponse(
            success=True,
            outputs={
                "provider": provider,
                "work_unit_result": "done",
                "winner": "candidate-1",
            },
            usage=UsageRecord(
                provider_id=provider or "local",
                provider_family="gateway",
                dispatch_id=str(request.task_id),
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                estimated=False,
            ),
        )

    def provider_for(self, node_id: str) -> str | None:
        for req in self.requests:
            if req.task_id == node_id:
                return req.constraints.get("provider")
        return None


def test_fanout_assigns_distinct_providers_per_branch():
    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "fan",
                    "title": "F",
                    "node_type": "fanout",
                    "pattern_config": {"count": 2, "providers": ["provider-a", "provider-b"]},
                }
            ]
        }
    ).to_artifact()
    dispatcher = RecordingDispatcher()

    result = TaskGraphExecutor(dispatcher=dispatcher).execute_all(graph).to_artifact()
    state = result["graph_state"]

    assert dispatcher.provider_for("fan-branch-1") == "provider-a"
    assert dispatcher.provider_for("fan-branch-2") == "provider-b"

    used = {req.constraints.get("provider") for req in dispatcher.requests if req.constraints.get("provider")}
    assert used == {"provider-a", "provider-b"}

    assert "fan-synthesize" in state["completed_nodes"]


def test_fanout_without_providers_carries_no_provider_constraint():
    graph = graph_from_workflow(
        {"nodes": [{"id": "fan", "title": "F", "node_type": "fanout", "pattern_config": {"count": 2}}]}
    ).to_artifact()
    dispatcher = RecordingDispatcher()

    TaskGraphExecutor(dispatcher=dispatcher).execute_all(graph)

    branch_reqs = [r for r in dispatcher.requests if "-branch-" in str(r.task_id)]
    assert branch_reqs
    for req in branch_reqs:
        assert "provider" not in req.constraints
        assert req.constraints["purpose"] == "child_task_execution"


def test_fanout_providers_round_robin_when_count_exceeds_providers():
    graph = graph_from_workflow(
        {
            "nodes": [
                {
                    "id": "fan",
                    "title": "F",
                    "node_type": "fanout",
                    "pattern_config": {"count": 3, "providers": ["p1", "p2"]},
                }
            ]
        }
    ).to_artifact()
    dispatcher = RecordingDispatcher()

    TaskGraphExecutor(dispatcher=dispatcher).execute_all(graph)

    assert dispatcher.provider_for("fan-branch-1") == "p1"
    assert dispatcher.provider_for("fan-branch-2") == "p2"
    assert dispatcher.provider_for("fan-branch-3") == "p1"


def test_orchestrator_recipe_fans_out_judged_merged_measured():
    """T5.3 acceptance: fan out across >=2 providers, judged + merged + measured."""
    recipe = load_recipe(RECIPES_DIR / "orchestrator")
    graph = recipe.build_graph().to_artifact()
    dispatcher = RecordingDispatcher()

    result = TaskGraphExecutor(dispatcher=dispatcher).execute_all(graph).to_artifact()
    state = result["graph_state"]

    # (a) fans out across >=2 distinct providers
    providers_used = {
        req.constraints.get("provider")
        for req in dispatcher.requests
        if req.constraints.get("provider")
    }
    assert len(providers_used) >= 2

    # (b) judged + merged: synthesize fan-in and judge winner both completed
    assert "fanout-synthesize" in state["completed_nodes"]
    assert "judge" in state["completed_nodes"]
    assert "judge-winner" in state["completed_nodes"]

    # (c) measured: real token cost summed from per-dispatch usage
    total_tokens = sum(
        int((event.get("provider_result") or {}).get("usage", {}).get("total_tokens", 0) or 0)
        for event in result["events"]
    )
    assert total_tokens > 0
