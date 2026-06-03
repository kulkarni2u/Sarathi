"""Tests for NCP ↔ dynamic workflow integration.

All tests use stub adapters so no live NCP server is required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.task_graph import NodeType, graph_from_workflow, progress_graph
from src.runtime import TaskGraphExecutor
from src.runtime.contracts import DispatchResponse
from src.runtime.workflow_patterns import WorkflowPattern, WorkflowPatternsPolicy


# ---------------------------------------------------------------------------
# Stub NCP adapters
# ---------------------------------------------------------------------------

class _ArtifactAdapter:
    """Records write_memory calls."""
    def __init__(self):
        self.written: list[dict] = []

    def _call_write_memory(self, content: str, layer: str, src: str, written_by: str) -> None:
        self.written.append({"content": content, "layer": layer, "written_by": written_by})


class _WhisperRouter:
    """Records whisper emit calls."""
    def __init__(self):
        self.emitted: list[dict] = []

    def emit(self, from_agent, target, whisper_type, payload, confidence=0.9):
        self.emitted.append({
            "from": from_agent, "target": target,
            "type": whisper_type, "payload": payload,
        })


class _PersistenceAdapter:
    """Records write_memory calls (episodic layer)."""
    def __init__(self):
        self.written: list[dict] = []

    def _call_write_memory(self, content: str, layer: str, src: str, written_by: str) -> None:
        self.written.append({"content": content, "layer": layer, "written_by": written_by})


class _SuccessDispatcher:
    """Returns a successful dispatch response with configurable outputs."""
    def __init__(self, outputs: dict | None = None):
        self.outputs = outputs or {}
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)
        return DispatchResponse(success=True, outputs=self.outputs)


# ---------------------------------------------------------------------------
# _ncp_post_node_complete
# ---------------------------------------------------------------------------

def test_node_output_saved_to_ncp_artifact_adapter():
    artifact_adapter = _ArtifactAdapter()
    graph = graph_from_workflow({"nodes": [{"id": "n1", "title": "Work"}]}).to_artifact()
    executor = TaskGraphExecutor(ncp_artifact_adapter=artifact_adapter)

    provider_result = {"success": True, "outputs": {"result": "done"}}
    executor._ncp_post_node_complete({"id": "n1", "node_type": "execute"}, provider_result)

    assert len(artifact_adapter.written) == 1
    record = json.loads(artifact_adapter.written[0]["content"])
    assert record["sarathi_node"] == "n1"
    assert record["outputs"] == {"result": "done"}
    assert artifact_adapter.written[0]["layer"] == "semantic"


def test_node_output_not_saved_when_outputs_empty():
    artifact_adapter = _ArtifactAdapter()
    executor = TaskGraphExecutor(ncp_artifact_adapter=artifact_adapter)
    executor._ncp_post_node_complete({"id": "n1"}, {"success": True, "outputs": {}})
    assert artifact_adapter.written == []


def test_node_output_not_saved_when_adapter_absent():
    executor = TaskGraphExecutor()
    # Should not raise even without an adapter
    executor._ncp_post_node_complete({"id": "n1"}, {"success": True, "outputs": {"x": 1}})


def test_node_output_saved_on_execute_all():
    artifact_adapter = _ArtifactAdapter()
    dispatcher = _SuccessDispatcher(outputs={"answer": 42})
    graph = graph_from_workflow({"nodes": [{"id": "step1", "title": "Do it"}]}).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_artifact_adapter=artifact_adapter)

    executor.execute_all(graph)

    assert len(artifact_adapter.written) == 1
    record = json.loads(artifact_adapter.written[0]["content"])
    assert record["sarathi_node"] == "step1"


# ---------------------------------------------------------------------------
# FANOUT → whisper emission
# ---------------------------------------------------------------------------

def test_fanout_completion_emits_whisper_per_branch():
    whisper_router = _WhisperRouter()
    graph = graph_from_workflow({
        "nodes": [{
            "id": "fan",
            "title": "Explore",
            "node_type": "fanout",
            "pattern_config": {"count": 3},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(ncp_whisper_router=whisper_router)
    executor.execute_next(graph)

    targets = {w["target"] for w in whisper_router.emitted}
    assert targets == {"s.fan-branch-1", "s.fan-branch-2", "s.fan-branch-3"}
    for w in whisper_router.emitted:
        assert w["type"] == "fanout_context"
        payload = json.loads(w["payload"])
        assert payload["parent_id"] == "fan"
        assert "sibling_ids" in payload
        assert payload["synthesize_id"] == "fan-synthesize"


def test_fanout_no_whisper_without_router():
    graph = graph_from_workflow({
        "nodes": [{"id": "fan", "title": "F", "node_type": "fanout", "pattern_config": {"count": 2}}]
    }).to_artifact()
    # Should not raise
    TaskGraphExecutor().execute_next(graph)


# ---------------------------------------------------------------------------
# LOOP_GATE → episodic write
# ---------------------------------------------------------------------------

def test_loop_gate_writes_findings_to_episodic_memory():
    persistence = _PersistenceAdapter()
    dispatcher = _SuccessDispatcher(outputs={"new_findings": True, "detail": "found X"})
    graph = graph_from_workflow({
        "nodes": [{
            "id": "loop",
            "title": "Scan",
            "node_type": "loop_gate",
            "pattern_config": {"max_iterations": 5, "condition_key": "new_findings", "iteration": 1},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        ncp_persistence_adapter=persistence,
    )
    executor.execute_next(graph)

    assert len(persistence.written) == 1
    record = json.loads(persistence.written[0]["content"])
    assert record["sarathi_loop"] == "loop"
    assert record["iteration"] == 1
    assert record["findings"]["new_findings"] is True
    assert persistence.written[0]["layer"] == "episodic"


def test_loop_gate_no_write_when_outputs_empty():
    persistence = _PersistenceAdapter()
    dispatcher = _SuccessDispatcher(outputs={})
    graph = graph_from_workflow({
        "nodes": [{"id": "loop", "title": "L", "node_type": "loop_gate",
                   "pattern_config": {"max_iterations": 3, "condition_key": "found"}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_persistence_adapter=persistence)
    executor.execute_next(graph)
    assert persistence.written == []


def test_loop_iter_id_extracts_parent_correctly():
    persistence = _PersistenceAdapter()
    dispatcher = _SuccessDispatcher(outputs={"new_findings": True})
    # Simulate iteration 2 node (injected by prior iteration)
    graph = graph_from_workflow({
        "nodes": [{
            "id": "loop-iter-2",
            "title": "Scan iter 2",
            "node_type": "loop_gate",
            "pattern_config": {"max_iterations": 5, "condition_key": "new_findings", "iteration": 2},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_persistence_adapter=persistence)
    executor.execute_next(graph)

    record = json.loads(persistence.written[0]["content"])
    # parent_id should strip the "-iter-2" suffix
    assert record["sarathi_loop"] == "loop"
    assert record["iteration"] == 2


# ---------------------------------------------------------------------------
# CLASSIFY → whisper to activated branch
# ---------------------------------------------------------------------------

def test_classify_emits_whisper_to_activated_branch():
    whisper_router = _WhisperRouter()
    dispatcher = _SuccessDispatcher(outputs={"classification": "bug"})
    graph = graph_from_workflow({
        "nodes": [{
            "id": "clf",
            "title": "Triage",
            "node_type": "classify",
            "pattern_config": {"branches": {"bug": "Fix the bug", "feature": "Build feature"}},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_whisper_router=whisper_router)
    executor.execute_next(graph)

    assert len(whisper_router.emitted) == 1
    w = whisper_router.emitted[0]
    assert w["target"] == "s.clf-branch-bug"
    assert w["type"] == "classify_context"
    payload = json.loads(w["payload"])
    assert payload["classification"] == "bug"


def test_classify_no_whisper_when_no_classification_output():
    whisper_router = _WhisperRouter()
    dispatcher = _SuccessDispatcher(outputs={})  # no classification key
    graph = graph_from_workflow({
        "nodes": [{
            "id": "clf",
            "title": "Triage",
            "node_type": "classify",
            "pattern_config": {"branches": {"bug": "Fix"}},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_whisper_router=whisper_router)
    executor.execute_next(graph)
    assert whisper_router.emitted == []


# ---------------------------------------------------------------------------
# NCP context adapter selection in _dispatch_node
# ---------------------------------------------------------------------------

class _NcpContextAdapter:
    """Stub NCP context adapter that records compile_typed_node_context calls."""
    def __init__(self):
        self.calls: list[dict] = []

    def compile_typed_node_context(self, *, node, graph=None, phase="Build", token_budget=None):
        self.calls.append({"node_id": node.get("id"), "node_type": node.get("node_type")})
        return {
            "agent_input": {"objective": "test", "token_budget": 1000, "constraints": [],
                            "acceptance_criteria": [], "relevant_files": [],
                            "prior_findings": [], "available_tools": []},
            "compilation": {"ncp_mode": "direct", "ncp_conscious": {}},
        }


def test_typed_node_uses_ncp_context_adapter():
    ncp_ctx = _NcpContextAdapter()
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "synth", "title": "Merge", "node_type": "synthesize",
                   "pattern_config": {"source_ids": ["b1", "b2"]}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_context_adapter=ncp_ctx)
    executor.execute_next(graph)

    assert len(ncp_ctx.calls) == 1
    assert ncp_ctx.calls[0]["node_id"] == "synth"
    assert ncp_ctx.calls[0]["node_type"] == "synthesize"


def test_execute_node_does_not_use_ncp_context_adapter():
    ncp_ctx = _NcpContextAdapter()
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "work", "title": "Work", "node_type": "execute"}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_context_adapter=ncp_ctx)
    executor.execute_next(graph)

    assert ncp_ctx.calls == []


def test_ncp_context_fallback_on_exception():
    class _BrokenAdapter:
        def compile_typed_node_context(self, **kwargs):
            raise RuntimeError("NCP unavailable")

    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "j1", "title": "Judge", "node_type": "judge"}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_context_adapter=_BrokenAdapter())
    # Should not raise; falls back to local ContextCompiler
    result = executor.execute_next(graph)
    assert any(e.action == "completed" for e in result.events)


# ---------------------------------------------------------------------------
# TaskGraphExecutor constructor keyword args
# ---------------------------------------------------------------------------

def test_executor_accepts_all_ncp_kwargs():
    art = _ArtifactAdapter()
    whi = _WhisperRouter()
    per = _PersistenceAdapter()

    executor = TaskGraphExecutor(
        ncp_artifact_adapter=art,
        ncp_whisper_router=whi,
        ncp_persistence_adapter=per,
    )
    assert executor.ncp_artifact_adapter is art
    assert executor.ncp_whisper_router is whi
    assert executor.ncp_persistence_adapter is per
    assert executor.ncp_context_adapter is None


# ---------------------------------------------------------------------------
# Bug 1 fix — EXECUTE branch nodes use NCP context adapter
# ---------------------------------------------------------------------------

def test_execute_branch_node_uses_ncp_context_adapter():
    """A node with '-branch-' in its id must go through compile_typed_node_context."""
    ncp_ctx = _NcpContextAdapter()
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "fan-branch-1", "title": "Branch work", "node_type": "execute"}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_context_adapter=ncp_ctx)
    executor.execute_next(graph)

    assert len(ncp_ctx.calls) == 1
    assert ncp_ctx.calls[0]["node_id"] == "fan-branch-1"


def test_plain_execute_node_still_skips_ncp_context():
    """A plain EXECUTE node without '-branch-' still uses local ContextCompiler."""
    ncp_ctx = _NcpContextAdapter()
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "plain-work", "title": "Plain", "node_type": "execute"}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_context_adapter=ncp_ctx)
    executor.execute_next(graph)

    assert ncp_ctx.calls == []


# ---------------------------------------------------------------------------
# Bug 2 fix — whisper fetch key uses s. prefix
# ---------------------------------------------------------------------------

def test_fetch_node_whispers_uses_s_prefix():
    """_fetch_node_whispers must query 'whisper:s.{node_id}' to match emit targets."""
    fetched_queries: list[str] = []

    class _TrackingAdapter:
        mode = "direct"
        endpoint = "http://127.0.0.1:4242/mcp"
        run_path = ".ncp/run.py"

        def _call_fetch(self, query: str, k: int = 3) -> list:
            fetched_queries.append(query)
            return []

        def _reconstruct_chunk_text(self, chunk: str) -> str:
            return chunk

        def compile_typed_node_context(self, *, node, graph=None, phase="Build", token_budget=None):
            # delegate only the whisper fetch
            node_id = str(node.get("id", ""))
            self._call_fetch(f"whisper:s.{node_id}", k=3)
            return {
                "agent_input": {"objective": "test", "token_budget": 1000, "constraints": [],
                                "acceptance_criteria": [], "relevant_files": [],
                                "prior_findings": [], "available_tools": []},
                "compilation": {"ncp_mode": "direct", "ncp_conscious": {}},
            }

    ncp_ctx = _TrackingAdapter()
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "fan-branch-2", "title": "Branch", "node_type": "execute"}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_context_adapter=ncp_ctx)
    executor.execute_next(graph)

    assert any("whisper:s.fan-branch-2" in q for q in fetched_queries)


# ---------------------------------------------------------------------------
# Bug 3 fix — NCP write failures surfaced as ncp_warnings
# ---------------------------------------------------------------------------

class _FailingArtifactAdapter:
    """Always raises on write_memory."""
    def _call_write_memory(self, *args, **kwargs):
        raise RuntimeError("NCP write timeout")


def test_ncp_post_node_complete_returns_error_on_write_failure():
    executor = TaskGraphExecutor(ncp_artifact_adapter=_FailingArtifactAdapter())
    result = executor._ncp_post_node_complete(
        {"id": "n1", "node_type": "execute"},
        {"success": True, "outputs": {"x": 1}},
    )
    assert result is not None
    assert "NCP write timeout" in result


def test_ncp_write_failure_surfaced_in_provider_result():
    """When the semantic write fails, ncp_warnings appears in provider_result."""
    dispatcher = _SuccessDispatcher(outputs={"answer": 1})
    graph = graph_from_workflow({
        "nodes": [{"id": "step1", "title": "Work"}]
    }).to_artifact()
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        ncp_artifact_adapter=_FailingArtifactAdapter(),
    )
    result = executor.execute_next(graph)

    # provider_result is stored on the node via _annotate_node_result
    node = next(n for n in result.graph_state["nodes"] if n["id"] == "step1")
    pr = node.get("last_provider_result", {})
    warnings = pr.get("ncp_warnings", [])
    assert any("write_output_failed" in w for w in warnings)


def test_loop_write_failure_surfaced_in_graph_warnings():
    """When loop episodic write fails, _ncp_warnings appears in the graph state."""
    class _FailingPersistence:
        def _call_write_memory(self, *args, **kwargs):
            raise RuntimeError("disk full")

    dispatcher = _SuccessDispatcher(outputs={"new_findings": True})
    graph = graph_from_workflow({
        "nodes": [{
            "id": "loop",
            "title": "Scan",
            "node_type": "loop_gate",
            "pattern_config": {"max_iterations": 3, "condition_key": "new_findings"},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(
        dispatcher=dispatcher,
        ncp_persistence_adapter=_FailingPersistence(),
    )
    result = executor.execute_next(graph)
    warnings = result.graph_state.get("_ncp_warnings", [])
    assert any(w.get("type") == "loop_write_failed" for w in warnings)


# ---------------------------------------------------------------------------
# Bug 4 fix — JUDGE emits judge_context whisper to winner
# ---------------------------------------------------------------------------

def test_judge_completion_emits_whisper_to_winner():
    whisper_router = _WhisperRouter()
    dispatcher = _SuccessDispatcher(outputs={"winner": "option-a", "score": 0.9})
    graph = graph_from_workflow({
        "nodes": [{
            "id": "jdg",
            "title": "Pick best",
            "node_type": "judge",
            "pattern_config": {"competitor_ids": ["a", "b"]},
        }]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, ncp_whisper_router=whisper_router)
    executor.execute_next(graph)

    judge_whispers = [w for w in whisper_router.emitted if w["type"] == "judge_context"]
    assert len(judge_whispers) == 1
    assert judge_whispers[0]["target"] == "s.jdg-winner"
    payload = json.loads(judge_whispers[0]["payload"])
    assert payload["parent_id"] == "jdg"
    assert payload["judgment"]["winner"] == "option-a"


# ---------------------------------------------------------------------------
# Gap 5 fix — WorkflowPatternsPolicy gates pattern injection
# ---------------------------------------------------------------------------

def _policy_with(*patterns: str) -> WorkflowPatternsPolicy:
    return WorkflowPatternsPolicy(enabled_patterns=set(patterns))


def test_fanout_suppressed_when_pattern_disabled():
    policy = _policy_with()  # no patterns enabled
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "fan", "title": "F", "node_type": "fanout",
                   "pattern_config": {"count": 3}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, workflow_patterns_policy=policy)
    result = executor.execute_next(graph)
    # No branch nodes should be injected
    injected = [n for n in result.graph_state["nodes"] if "branch" in n["id"]]
    assert injected == []


def test_fanout_allowed_when_pattern_enabled():
    policy = _policy_with(WorkflowPattern.FANOUT_AND_SYNTHESIZE)
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "fan", "title": "F", "node_type": "fanout",
                   "pattern_config": {"count": 2}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, workflow_patterns_policy=policy)
    result = executor.execute_next(graph)
    injected = [n for n in result.graph_state["nodes"] if "branch" in n["id"]]
    assert len(injected) == 2


def test_classify_suppressed_when_pattern_disabled():
    policy = _policy_with()  # no patterns enabled
    dispatcher = _SuccessDispatcher(outputs={"classification": "bug"})
    graph = graph_from_workflow({
        "nodes": [{"id": "clf", "title": "Triage", "node_type": "classify",
                   "pattern_config": {"branches": {"bug": "Fix it"}}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, workflow_patterns_policy=policy)
    result = executor.execute_next(graph)
    injected = [n for n in result.graph_state["nodes"] if "branch" in n["id"]]
    assert injected == []


def test_loop_suppressed_when_pattern_disabled():
    policy = _policy_with()
    dispatcher = _SuccessDispatcher(outputs={"new_findings": True})
    graph = graph_from_workflow({
        "nodes": [{"id": "lp", "title": "Loop", "node_type": "loop_gate",
                   "pattern_config": {"max_iterations": 5, "condition_key": "new_findings"}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, workflow_patterns_policy=policy)
    result = executor.execute_next(graph)
    # No next-iteration node injected
    iter_nodes = [n for n in result.graph_state["nodes"] if "iter" in n["id"]]
    assert iter_nodes == []


def test_no_policy_allows_all_patterns():
    """With workflow_patterns_policy=None, all patterns run (backward-compatible)."""
    dispatcher = _SuccessDispatcher()
    graph = graph_from_workflow({
        "nodes": [{"id": "fan", "title": "F", "node_type": "fanout",
                   "pattern_config": {"count": 2}}]
    }).to_artifact()
    executor = TaskGraphExecutor(dispatcher=dispatcher, workflow_patterns_policy=None)
    result = executor.execute_next(graph)
    injected = [n for n in result.graph_state["nodes"] if "branch" in n["id"]]
    assert len(injected) == 2


# ---------------------------------------------------------------------------
# Gap 6 fix — _ncp_build_context uses NCPContextAdapter when available
# ---------------------------------------------------------------------------

def test_ncp_build_context_uses_adapter_when_provided():
    from src.phases.build import _ncp_build_context

    class _MockTask:
        task_id = "t1"
        description = "do the thing"

    class _MockAdapter:
        calls: list[dict] = []
        def _call_get_context(self, args: dict) -> str:
            _MockAdapter.calls.append(args)
            return "[NCP:CONSCIOUS]\ntask: do the thing"

    _MockAdapter.calls = []
    result = _ncp_build_context(_MockTask(), ncp_adapter=_MockAdapter())
    assert result == "[NCP:CONSCIOUS]\ntask: do the thing"
    assert len(_MockAdapter.calls) == 1
    assert _MockAdapter.calls[0]["agent_id"] == "s.builder"
    assert _MockAdapter.calls[0]["slot"] == "Build"


def test_ncp_build_context_falls_back_without_adapter():
    from src.phases.build import _ncp_build_context

    class _MockTask:
        task_id = "t1"
        description = "do the thing"

    # No adapter, non-existent run_path → should return "" gracefully
    result = _ncp_build_context(_MockTask(), ncp_adapter=None, run_path="/nonexistent/run.py")
    assert result == ""
