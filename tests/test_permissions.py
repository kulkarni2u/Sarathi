"""Tests for PermissionScope, SideEffectClass, EscalationPolicy."""
import pytest
from src.task_class import TaskClass
from src.permissions import (
    SideEffectClass,
    EscalationAction,
    ExpansionRule,
    EscalationPolicy,
    InvokePermission,
    PermissionScope,
    build_permission_scope,
)


def test_irreversible_invoke_always_requires_confirmation():
    perm = InvokePermission("aws_lambda_deploy", SideEffectClass.IRREVERSIBLE)
    assert perm.requires_confirmation is True


def test_read_only_invoke_does_not_require_confirmation_by_default():
    perm = InvokePermission("s3_list", SideEffectClass.READ_ONLY)
    assert perm.requires_confirmation is False


def test_reversible_invoke_confirmation_can_be_set():
    perm = InvokePermission("db_write", SideEffectClass.REVERSIBLE, requires_confirmation=True)
    assert perm.requires_confirmation is True


def test_mutation_infra_requires_human_approval():
    scope = PermissionScope(TaskClass.MUTATION_INFRA)
    assert scope.requires_human_approval is True


def test_mutation_config_requires_human_approval():
    scope = PermissionScope(TaskClass.MUTATION_CONFIG)
    assert scope.requires_human_approval is True


def test_evolution_harness_requires_human_approval():
    scope = PermissionScope(TaskClass.EVOLUTION_HARNESS)
    assert scope.requires_human_approval is True


def test_query_does_not_require_human_approval():
    scope = PermissionScope(TaskClass.QUERY)
    assert scope.requires_human_approval is False


def test_codegen_does_not_require_human_approval():
    scope = PermissionScope(TaskClass.CODEGEN_PATCH)
    assert scope.requires_human_approval is False


def test_max_side_effect_empty_returns_read_only():
    scope = PermissionScope(TaskClass.QUERY)
    assert scope.max_side_effect == SideEffectClass.READ_ONLY


def test_max_side_effect_with_irreversible():
    scope = PermissionScope(TaskClass.MUTATION_INFRA, invoke_permissions=[
        InvokePermission("lambda_deploy", SideEffectClass.IRREVERSIBLE),
        InvokePermission("cloudwatch_read", SideEffectClass.READ_ONLY),
    ])
    assert scope.max_side_effect == SideEffectClass.IRREVERSIBLE


def test_build_permission_scope_query():
    scope = build_permission_scope(TaskClass.QUERY)
    assert scope.task_class == TaskClass.QUERY
    assert scope.escalation_policy.on_scope_exceed == EscalationAction.BLOCK


def test_build_permission_scope_mutation():
    scope = build_permission_scope(TaskClass.MUTATION_INFRA)
    assert scope.requires_human_approval is True
    assert scope.escalation_policy.on_scope_exceed == EscalationAction.PAUSE_AND_NOTIFY


def test_build_permission_scope_codegen():
    scope = build_permission_scope(TaskClass.CODEGEN_PATCH)
    assert scope.escalation_policy.on_scope_exceed == EscalationAction.AUTO_EXPAND_IF_SAFE


def test_expansion_rule_defaults_audit_log():
    rule = ExpansionRule("side_effect == READ_ONLY", EscalationAction.AUTO_EXPAND_IF_SAFE)
    assert rule.audit_log is True


def test_escalation_policy_default_channel():
    policy = EscalationPolicy()
    assert policy.notify_channel == "sarathi-alerts"
