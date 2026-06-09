"""HarnessConfig — the compiled artifact emitted by the ROUTE phase."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

try:
    from .task_class import TaskClass, AssemblyDefaults, TASK_CLASS_DEFAULTS
except ImportError:
    from task_class import TaskClass, AssemblyDefaults, TASK_CLASS_DEFAULTS


@dataclass
class AgentBinding:
    agent_id: str
    model: str | None = None
    skill_config: str | None = None
    health_score: float = 1.0


@dataclass
class SkillBinding:
    skill_name: str
    skill_path: str
    loaded_eagerly: bool = True


@dataclass
class QualitySignalDef:
    name: str
    weight: float = 1.0
    target: float | None = None


@dataclass
class HarnessConfig:
    # Identity
    harness_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_id: str = ""
    task_class: TaskClass = TaskClass.ANALYSIS
    assembled_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    assembler_version: str = "sarathi-0.2.0"

    # Execution plan
    primary_agent: AgentBinding = field(default_factory=lambda: AgentBinding("local"))
    fallback_agents: list[AgentBinding] = field(default_factory=list)

    # Skill manifest
    eager_skills: list[SkillBinding] = field(default_factory=list)
    lazy_skills: list[str] = field(default_factory=list)

    # Context contract (NCP)
    context_scope: str = "domain_relevant"
    ncp_enabled: bool = False
    stale_keys: list[str] = field(default_factory=list)
    trust_gate_result: str = "PASS"  # PASS | WARN | BLOCK

    # Permission surface
    permission_scope: str = "read_only"
    requires_human_approval: bool = False
    side_effect_class: str = "READ_ONLY"

    # Observability
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    quality_signals: list[QualitySignalDef] = field(default_factory=list)

    # Assembly defaults snapshot
    defaults: AssemblyDefaults | None = None

    def to_json(self) -> str:
        """Serialize to JSON for storage, diffing, and replay."""
        d = asdict(self)
        d["task_class"] = self.task_class.value
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, data: str) -> HarnessConfig:
        """Reconstruct from JSON produced by to_json()."""
        d = json.loads(data)
        d["task_class"] = TaskClass(d["task_class"])

        if d.get("primary_agent"):
            d["primary_agent"] = AgentBinding(**d["primary_agent"])
        if d.get("fallback_agents"):
            d["fallback_agents"] = [AgentBinding(**f) for f in d["fallback_agents"]]
        if d.get("eager_skills"):
            d["eager_skills"] = [SkillBinding(**s) for s in d["eager_skills"]]
        if d.get("quality_signals"):
            d["quality_signals"] = [QualitySignalDef(**s) for s in d["quality_signals"]]
        if d.get("defaults") is not None:
            d["defaults"] = AssemblyDefaults(**d["defaults"])

        return cls(**d)

    def diff(self, other: HarnessConfig) -> dict[str, Any]:
        """Return fields that differ between two configs."""
        a = json.loads(self.to_json())
        b = json.loads(other.to_json())
        return {k: {"from": a[k], "to": b[k]} for k in a if a[k] != b.get(k)}

    @classmethod
    def from_task_class(
        cls,
        task_class: TaskClass,
        task_id: str,
        ncp_enabled: bool = False,
    ) -> HarnessConfig:
        """Build a HarnessConfig from TaskClass defaults."""
        defaults = TASK_CLASS_DEFAULTS[task_class]
        signals = [QualitySignalDef(name=name) for name in defaults.quality_signals]
        return cls(
            task_id=task_id,
            task_class=task_class,
            context_scope=defaults.context_scope,
            permission_scope=defaults.permission_scope,
            requires_human_approval=defaults.human_in_loop,
            ncp_enabled=ncp_enabled,
            quality_signals=signals,
            defaults=defaults,
        )


@dataclass
class HarnessOutcome:
    """Measured execution result — feeds the Evolution layer."""
    harness_id: str
    task_id: str
    task_class: TaskClass
    quality_signals: dict[str, float]   # {"test_pass_rate": 0.95, "token_cost": 1240}
    token_cost_actual: int
    latency_ms: int
    human_interventions: int
    rollback_triggered: bool
    trust_gate_result: str
    agent_used: str
    assembler_version: str = "sarathi-0.2.0"
