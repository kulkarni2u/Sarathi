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
