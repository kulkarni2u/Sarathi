"""PermissionScope schema — typed permission surface declared at assembly time."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

try:
    from .task_class import TaskClass
except ImportError:
    from task_class import TaskClass


class SideEffectClass(Enum):
    READ_ONLY    = "read_only"
    IDEMPOTENT   = "idempotent"
    REVERSIBLE   = "reversible"
    IRREVERSIBLE = "irreversible"


class EscalationAction(Enum):
    BLOCK               = "block"
    PAUSE_AND_NOTIFY    = "pause_and_notify"
    AUTO_EXPAND_IF_SAFE = "auto_expand_if_safe"
    ABORT               = "abort"


@dataclass
class ExpansionRule:
    condition: str        # DSL predicate, e.g. "side_effect == READ_ONLY and cost < 0.01"
    action: EscalationAction
    audit_log: bool = True


@dataclass
class EscalationPolicy:
    on_scope_exceed: EscalationAction = EscalationAction.PAUSE_AND_NOTIFY
    notify_channel: str = "sarathi-alerts"
    expand_rules: list[ExpansionRule] = field(default_factory=list)


@dataclass
class InvokePermission:
    target_ref: str
    side_effect_class: SideEffectClass = SideEffectClass.READ_ONLY
    max_invocations: int | None = None
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        # IRREVERSIBLE always requires confirmation — no exceptions
        if self.side_effect_class == SideEffectClass.IRREVERSIBLE:
            self.requires_confirmation = True


@dataclass
class PermissionScope:
    task_class: TaskClass
    invoke_permissions: list[InvokePermission] = field(default_factory=list)
    escalation_policy: EscalationPolicy = field(default_factory=EscalationPolicy)
    requires_human_approval: bool = False

    def __post_init__(self) -> None:
        val = self.task_class.value
        # MUTATION and EVOLUTION classes always require human approval
        if val.startswith("mutation") or val.startswith("evolution"):
            self.requires_human_approval = True

    @property
    def max_side_effect(self) -> SideEffectClass:
        """Derive the highest side-effect class declared in invoke permissions."""
        order = [
            SideEffectClass.READ_ONLY,
            SideEffectClass.IDEMPOTENT,
            SideEffectClass.REVERSIBLE,
            SideEffectClass.IRREVERSIBLE,
        ]
        if not self.invoke_permissions:
            return SideEffectClass.READ_ONLY
        return max(
            (p.side_effect_class for p in self.invoke_permissions),
            key=lambda s: order.index(s),
        )


# Default escalation policies per task class family
_ESCALATION_BY_FAMILY: dict[str, EscalationPolicy] = {
    "query":         EscalationPolicy(on_scope_exceed=EscalationAction.BLOCK),
    "analysis":      EscalationPolicy(on_scope_exceed=EscalationAction.PAUSE_AND_NOTIFY),
    "codegen":       EscalationPolicy(on_scope_exceed=EscalationAction.AUTO_EXPAND_IF_SAFE),
    "mutation":      EscalationPolicy(on_scope_exceed=EscalationAction.PAUSE_AND_NOTIFY),
    "orchestration": EscalationPolicy(on_scope_exceed=EscalationAction.ABORT),
    "evolution":     EscalationPolicy(on_scope_exceed=EscalationAction.AUTO_EXPAND_IF_SAFE),
}


def build_permission_scope(task_class: TaskClass) -> PermissionScope:
    """Construct a PermissionScope from a TaskClass with sensible defaults."""
    family = task_class.value.split("/")[0]
    escalation = _ESCALATION_BY_FAMILY.get(family, EscalationPolicy())
    return PermissionScope(task_class=task_class, escalation_policy=escalation)
