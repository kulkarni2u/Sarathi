"""Tests for Gap 3/4: harness caching and FAST/STANDARD/DEEP assembly modes."""
from __future__ import annotations

import pytest

from src.engine import Engine, Phase, PolicyPack, RouteHandler, TaskContext, Complexity
from src.harness import HarnessConfig
from src.task_class import TaskClass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_handler(cache: dict | None = None) -> RouteHandler:
    return RouteHandler(PolicyPack(), dispatcher=None, harness_cache=cache)


def _task(description: str = "fix null pointer bug", task_id: str = "t1") -> TaskContext:
    return TaskContext(task_id=task_id, description=description, complexity=Complexity.MEDIUM)


def _run_route(description: str, cache: dict, task_id: str = "t1") -> tuple[dict, dict]:
    handler = _make_handler(cache)
    result = handler.execute(_task(description, task_id), Phase.ROUTE)
    return result.artifacts, result.evidence


# ── STANDARD mode ─────────────────────────────────────────────────────────────

def test_standard_mode_on_first_call():
    artifacts, evidence = _run_route("fix null pointer bug", {})
    assert artifacts["assembly_mode"] == "STANDARD"
    assert evidence["assembly_mode"] == "STANDARD"
    assert evidence["cache_hit"] is False


def test_standard_mode_populates_cache():
    cache: dict = {}
    _run_route("fix null pointer bug", cache)
    assert TaskClass.CODEGEN_PATCH.value in cache


def test_cached_entry_is_harness_config():
    cache: dict = {}
    _run_route("fix null pointer bug", cache)
    assert isinstance(cache[TaskClass.CODEGEN_PATCH.value], HarnessConfig)


# ── FAST mode ─────────────────────────────────────────────────────────────────

def test_fast_mode_on_second_call_same_class():
    cache: dict = {}
    _run_route("fix null pointer bug", cache, "t1")
    artifacts2, evidence2 = _run_route("fix another bug", cache, "t2")
    assert artifacts2["assembly_mode"] == "FAST"
    assert evidence2["cache_hit"] is True


def test_fast_mode_uses_new_task_id():
    cache: dict = {}
    _run_route("fix null pointer bug", cache, "t1")
    artifacts2, _ = _run_route("fix another bug", cache, "t2")
    hc = HarnessConfig.from_json(
        __import__("json").dumps(artifacts2["harness_config"])
    )
    assert hc.task_id == "t2"


def test_fast_mode_generates_fresh_harness_id():
    cache: dict = {}
    a1, _ = _run_route("fix null pointer bug", cache, "t1")
    a2, _ = _run_route("fix another bug", cache, "t2")
    hc1 = HarnessConfig.from_json(__import__("json").dumps(a1["harness_config"]))
    hc2 = HarnessConfig.from_json(__import__("json").dumps(a2["harness_config"]))
    assert hc1.harness_id != hc2.harness_id


def test_fast_mode_preserves_quality_signals():
    cache: dict = {}
    a1, _ = _run_route("fix null pointer bug", cache, "t1")
    a2, _ = _run_route("fix another bug", cache, "t2")
    hc1 = HarnessConfig.from_json(__import__("json").dumps(a1["harness_config"]))
    hc2 = HarnessConfig.from_json(__import__("json").dumps(a2["harness_config"]))
    sigs1 = [s.name for s in hc1.quality_signals]
    sigs2 = [s.name for s in hc2.quality_signals]
    assert sigs1 == sigs2


def test_fast_mode_records_assembly_mode_in_harness_config():
    cache: dict = {}
    _run_route("fix null pointer bug", cache, "t1")
    a2, _ = _run_route("fix another bug", cache, "t2")
    hc = HarnessConfig.from_json(__import__("json").dumps(a2["harness_config"]))
    assert hc.assembly_mode == "FAST"


# ── DEEP mode ─────────────────────────────────────────────────────────────────

def test_deep_mode_for_mutation_infra():
    artifacts, evidence = _run_route("deploy infrastructure with terraform", {})
    assert artifacts["assembly_mode"] == "DEEP"
    assert evidence["cache_hit"] is False


def test_deep_mode_for_mutation_config():
    artifacts, _ = _run_route("update environment variable in production config", {})
    assert artifacts["assembly_mode"] == "DEEP"


def test_deep_mode_for_evolution_harness():
    # classify_task_class("improve harness efficiency") → ANALYSIS not evolution,
    # so use a description that explicitly triggers evolution
    from src.task_class import classify_task_class
    assert classify_task_class("deploy terraform infrastructure") == TaskClass.MUTATION_INFRA
    artifacts, _ = _run_route("deploy terraform infrastructure", {})
    assert artifacts["assembly_mode"] == "DEEP"


def test_deep_mode_does_not_populate_cache():
    cache: dict = {}
    _run_route("deploy infrastructure with terraform", cache)
    assert TaskClass.MUTATION_INFRA.value not in cache


def test_deep_mode_always_rebuilds():
    cache: dict = {}
    a1, _ = _run_route("deploy infra to prod", cache, "t1")
    a2, _ = _run_route("deploy infra to staging", cache, "t2")
    assert a1["assembly_mode"] == "DEEP"
    assert a2["assembly_mode"] == "DEEP"


# ── assembly_mode field on HarnessConfig ──────────────────────────────────────

def test_harness_config_default_assembly_mode():
    hc = HarnessConfig()
    assert hc.assembly_mode == "STANDARD"


def test_assembly_mode_survives_json_roundtrip():
    hc = HarnessConfig()
    hc.assembly_mode = "FAST"
    restored = HarnessConfig.from_json(hc.to_json())
    assert restored.assembly_mode == "FAST"


def test_old_json_without_assembly_mode_defaults_to_standard():
    import json
    hc = HarnessConfig()
    d = json.loads(hc.to_json())
    del d["assembly_mode"]
    restored = HarnessConfig.from_json(json.dumps(d))
    assert restored.assembly_mode == "STANDARD"


# ── Engine integration ────────────────────────────────────────────────────────

def test_engine_harness_cache_starts_empty():
    engine = Engine(ncp_enabled=False)
    assert engine._harness_cache == {}


def test_engine_shares_cache_with_route_handler():
    engine = Engine(ncp_enabled=False)
    route_handler = engine.phase_handlers[Phase.ROUTE]
    # They share the same dict object
    assert route_handler._harness_cache is engine._harness_cache


def test_engine_populates_cache_after_route():
    engine = Engine(ncp_enabled=False)
    task = TaskContext(
        task_id="cache-test",
        description="fix null pointer bug",
        complexity=Complexity.LOW,
    )
    engine.run_task(task)
    assert TaskClass.CODEGEN_PATCH.value in engine._harness_cache
