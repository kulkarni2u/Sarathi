"""Tests for TaskClass taxonomy and classify_task_class."""
import pytest
from src.task_class import (
    TaskClass,
    AssemblyDefaults,
    TASK_CLASS_DEFAULTS,
    classify_task_class,
    from_legacy_type,
)


def test_all_task_classes_have_defaults():
    for tc in TaskClass:
        assert tc in TASK_CLASS_DEFAULTS, f"{tc} missing from TASK_CLASS_DEFAULTS"


def test_assembly_defaults_fields():
    d = TASK_CLASS_DEFAULTS[TaskClass.QUERY]
    assert d.context_scope == "minimal"
    assert d.permission_scope == "read_only"
    assert d.agent_preference == "fastest"
    assert d.lazy_loading is True
    assert d.human_in_loop is False
    assert "relevance" in d.quality_signals


def test_mutation_infra_requires_human_in_loop():
    d = TASK_CLASS_DEFAULTS[TaskClass.MUTATION_INFRA]
    assert d.human_in_loop is True


def test_evolution_classes_require_human_in_loop():
    for tc in (TaskClass.EVOLUTION_HARNESS, TaskClass.EVOLUTION_CONTEXT):
        assert TASK_CLASS_DEFAULTS[tc].human_in_loop is True


def test_query_lazy_loading():
    assert TASK_CLASS_DEFAULTS[TaskClass.QUERY].lazy_loading is True


def test_mutation_infra_no_lazy_loading():
    assert TASK_CLASS_DEFAULTS[TaskClass.MUTATION_INFRA].lazy_loading is False


def test_classify_task_class_bug():
    tc = classify_task_class("Fix null pointer in user service")
    assert tc == TaskClass.CODEGEN_PATCH


def test_classify_task_class_deploy():
    tc = classify_task_class("deploy the service to production")
    assert tc == TaskClass.MUTATION_INFRA


def test_classify_task_class_refactor():
    tc = classify_task_class("Refactor auth module for clarity")
    assert tc == TaskClass.CODEGEN_REFACTOR


def test_classify_task_class_query():
    tc = classify_task_class("What does this function do?")
    assert tc == TaskClass.QUERY


def test_classify_task_class_analysis():
    tc = classify_task_class("Analyze performance bottlenecks in the pipeline")
    assert tc == TaskClass.ANALYSIS


def test_classify_task_class_default_falls_back_to_analysis():
    tc = classify_task_class("zxyzxyzxyz totally unknown")
    assert tc == TaskClass.ANALYSIS


def test_from_legacy_type_bug():
    assert from_legacy_type("bug") == TaskClass.CODEGEN_PATCH


def test_from_legacy_type_deploy():
    assert from_legacy_type("deploy") == TaskClass.MUTATION_INFRA


def test_from_legacy_type_unknown_falls_back():
    assert from_legacy_type("unknown_type") == TaskClass.ANALYSIS


def test_task_class_values_are_strings():
    for tc in TaskClass:
        assert isinstance(tc.value, str)


def test_task_class_roundtrip():
    for tc in TaskClass:
        assert TaskClass(tc.value) == tc
