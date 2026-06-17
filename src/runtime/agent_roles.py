"""Sanskrit-inspired role names for Sarathi-created agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class AgentRole:
    """Human-readable role identity for a Sarathi worker or subagent."""

    key: str
    name: str
    purpose: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def to_artifact(self) -> dict[str, str | list[str]]:
        """Return a stable artifact payload for phase logs and CLI output."""

        return {
            "key": self.key,
            "name": self.name,
            "purpose": self.purpose,
            "description": self.description,
            "aliases": list(self.aliases),
        }


DEFAULT_AGENT_ROLES: tuple[AgentRole, ...] = (
    AgentRole(
        key="sarathi",
        name="Sarathi",
        purpose="orchestrator",
        description="Overall workflow orchestrator for policy-backed Sarathi runs.",
        aliases=("orchestrator",),
    ),
    AgentRole(
        key="disha",
        name="Disha",
        purpose="planner",
        description="Planning role that shapes checkpoints, dependencies, and next steps.",
        aliases=("planner", "planning"),
    ),
    AgentRole(
        key="vichara",
        name="Vichara",
        purpose="researcher",
        description="Research role for gathering context, evidence, and alternatives.",
        aliases=("researcher", "research"),
    ),
    AgentRole(
        key="prajna",
        name="Prajna",
        purpose="reasoner",
        description="Reasoning role for synthesis, tradeoff analysis, and judgment.",
        aliases=("reasoner", "reasoning"),
    ),
    AgentRole(
        key="pravaha",
        name="Pravaha",
        purpose="executor",
        description="Execution role for carrying implementation work through the flow.",
        aliases=("executor", "execute"),
    ),
    AgentRole(
        key="nirnaya",
        name="Nirnaya",
        purpose="reviewer/validator",
        description="Decision role for review, validation, and acceptance checks.",
        aliases=("reviewer", "validator", "review", "validation"),
    ),
    AgentRole(
        key="samanvaya",
        name="Samanvaya",
        purpose="coordinator",
        description="Coordination role for aligning workers, ownership, and handoffs.",
        aliases=("coordinator", "coordination"),
    ),
    AgentRole(
        key="sahayaka",
        name="Sahayaka",
        purpose="support",
        description="Support role for assistance, unblockers, and companion tasks.",
        aliases=("support", "assistant", "helper"),
    ),
    AgentRole(
        key="marga",
        name="Marga",
        purpose="routing",
        description="Routing role for directing tasks to the right path or worker.",
        aliases=("routing", "router", "route"),
    ),
    AgentRole(
        key="sutra",
        name="Sutra",
        purpose="workflow spine/message bus",
        description="Workflow-spine role for message flow, sequencing, and shared context.",
        aliases=("workflow spine", "message bus", "bus"),
    ),
)

PHASE_AGENT_ROLE_KEYS: dict[str, str] = {
    "Route": "marga",
    "Brainstorm": "vichara",
    "PlanningAdvisor": "disha",
    "Plan": "disha",
    "Build": "pravaha",
    "Verify": "nirnaya",
    "Review": "nirnaya",
    "TaskTracking": "samanvaya",
    "RiskCheck": "prajna",
    "Elegance": "sahayaka",
    "PhaseLog": "sutra",
    "Learn": "prajna",
}


def list_agent_roles(roles: Iterable[AgentRole] = DEFAULT_AGENT_ROLES) -> tuple[AgentRole, ...]:
    """Return a stable, immutable snapshot of known Sarathi role names."""

    return tuple(list(roles))


def get_agent_role(
    role: str,
    *,
    default: AgentRole | None = None,
    roles: Iterable[AgentRole] = DEFAULT_AGENT_ROLES,
) -> AgentRole:
    """Look up a Sarathi role by key, display name, purpose, or alias."""

    lookup = _role_lookup(roles)
    normalized = _normalize(role)
    if normalized in lookup:
        return lookup[normalized]
    if normalized in _REGISTERED_AGENT_ROLES:
        return _REGISTERED_AGENT_ROLES[normalized]
    if default is not None:
        return default
    raise KeyError(f"Unknown Sarathi agent role: {role}")


def get_phase_agent_role(
    phase: str,
    *,
    default: AgentRole | None = None,
    roles: Iterable[AgentRole] = DEFAULT_AGENT_ROLES,
) -> AgentRole:
    """Return the default Sarathi agent identity for a lifecycle phase."""

    role_key = PHASE_AGENT_ROLE_KEYS.get(phase)
    if role_key is not None:
        return get_agent_role(role_key, roles=roles)
    if default is not None:
        return default
    raise KeyError(f"Unknown Sarathi lifecycle phase: {phase}")


def phase_agent_role_artifact(phase: str) -> dict[str, str | list[str]]:
    """Return a serializable agent-role artifact for a lifecycle phase."""

    role = get_phase_agent_role(phase)
    artifact = role.to_artifact()
    artifact["phase"] = phase
    return artifact


def list_phase_agent_roles() -> tuple[dict[str, str | list[str]], ...]:
    """Return phase-to-agent-role mappings in lifecycle order."""

    return tuple(phase_agent_role_artifact(phase) for phase in PHASE_AGENT_ROLE_KEYS)


def _role_lookup(roles: Iterable[AgentRole]) -> dict[str, AgentRole]:
    lookup: dict[str, AgentRole] = {}
    for agent_role in roles:
        for value in (
            agent_role.key,
            agent_role.name,
            agent_role.purpose,
            *agent_role.aliases,
        ):
            lookup[_normalize(value)] = agent_role
    return lookup


def _normalize(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


# ---------------------------------------------------------------------------
# Registry of user-declared (non-default) agent roles.
#
# Declarative agent specs (see runtime.agent_spec) register their AgentRole
# here so get_agent_role(...) can find them by key/name/alias alongside the
# fixed DEFAULT_AGENT_ROLES. This registry is intentionally mutable — callers
# (e.g. the CLI, or tests) register/clear roles at runtime.
# ---------------------------------------------------------------------------

_REGISTERED_AGENT_ROLES: dict[str, AgentRole] = {}


def register_agent_role(role: AgentRole) -> None:
    """Register a user-declared AgentRole for lookup via get_agent_role()."""

    for value in (role.key, role.name, role.purpose, *role.aliases):
        _REGISTERED_AGENT_ROLES[_normalize(value)] = role


def registered_agent_roles() -> tuple[AgentRole, ...]:
    """Return distinct registered AgentRole objects, in insertion order."""

    seen: dict[str, AgentRole] = {}
    for agent_role in _REGISTERED_AGENT_ROLES.values():
        seen.setdefault(agent_role.key, agent_role)
    return tuple(seen.values())


def clear_registered_agent_roles() -> None:
    """Remove all user-declared agent roles (used for test isolation)."""

    _REGISTERED_AGENT_ROLES.clear()
