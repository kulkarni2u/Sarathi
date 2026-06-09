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
    assembly_mode: str = "STANDARD"  # FAST | STANDARD | DEEP

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
        d.setdefault("assembly_mode", "STANDARD")

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
        primary_agent = resolve_agent_binding(defaults.agent_preference)
        return cls(
            task_id=task_id,
            task_class=task_class,
            context_scope=defaults.context_scope,
            permission_scope=defaults.permission_scope,
            requires_human_approval=defaults.human_in_loop,
            ncp_enabled=ncp_enabled,
            quality_signals=signals,
            defaults=defaults,
            primary_agent=primary_agent,
        )


_PREFERENCE_TO_PROVIDER: dict[str, str] = {
    "fastest":            "local",
    "balanced":           "local",
    "highest_capability": "claude",
    "sarathi_native":     "local",
}


def resolve_agent_binding(
    agent_preference: str,
    available_providers: list[str] | None = None,
) -> AgentBinding:
    """Map an AssemblyDefaults.agent_preference string to a concrete AgentBinding."""
    provider_id = _PREFERENCE_TO_PROVIDER.get(agent_preference, "local")
    if available_providers and provider_id not in available_providers:
        provider_id = available_providers[0] if available_providers else "local"
    return AgentBinding(agent_id=provider_id)


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


def measure_outcome(task: Any, harness_config: HarnessConfig) -> HarnessOutcome:
    """
    Extract real quality signals from a completed task's phase_results.

    Sources:
      test_pass_rate  — VERIFY command_succeeded (or coverage proxy)
      blast_radius    — 1.0 − REVIEW score
      accuracy/relevance — REVIEW score
      token_cost      — sum of dispatch_usage.total_tokens across all phases
      latency_ms      — harness assembled_at → now
      rollback_triggered — any phase recorded recovery_actions or rollback artifact
    """
    phase_results = getattr(task, "phase_results", []) or []
    declared = {sig.name for sig in harness_config.quality_signals}

    # ── Collect per-phase data ────────────────────────────────────────────
    verify_summary: dict[str, Any] = {}
    review_score: float | None = None
    review_outcome: str = "pass"
    token_cost = 0
    rollback = False
    human_interventions = 0

    for pr in phase_results:
        phase_val = getattr(getattr(pr, "phase", None), "value", str(getattr(pr, "phase", "")))
        artifacts: dict[str, Any] = getattr(pr, "artifacts", {}) or {}

        if phase_val == "Verify":
            verify_summary = (
                artifacts.get("verification_summary")
                or (artifacts.get("verification_results") or {}).get("summary", {})
                or {}
            )

        if phase_val == "Review":
            verdict = artifacts.get("review_verdict") or {}
            raw = verdict.get("score", artifacts.get("review_score"))
            if raw is not None:
                review_score = float(raw)
            review_outcome = verdict.get("outcome", getattr(pr, "outcome", "pass"))

        usage = artifacts.get("dispatch_usage")
        if isinstance(usage, dict):
            token_cost += int(usage.get("total_tokens", 0) or 0)

        if artifacts.get("rollback_triggered") or (
            isinstance(artifacts.get("recovery_actions"), list)
            and artifacts["recovery_actions"]
        ):
            rollback = True

        if artifacts.get("human_approved") or artifacts.get("pause_execution"):
            human_interventions += 1

    # ── Latency: assembled_at → now ───────────────────────────────────────
    try:
        assembled = datetime.fromisoformat(harness_config.assembled_at)
        now = datetime.utcnow()
        if assembled.tzinfo is not None:
            assembled = assembled.replace(tzinfo=None)
        latency_ms = max(0, int((now - assembled).total_seconds() * 1000))
    except Exception:
        latency_ms = 0

    # ── Signal extraction ─────────────────────────────────────────────────
    signals: dict[str, float] = {}

    if "test_pass_rate" in declared:
        cmd_ok = verify_summary.get("command_succeeded")
        coverage = float(verify_summary.get("coverage") or 85.0)
        if cmd_ok is True:
            signals["test_pass_rate"] = 1.0
        elif cmd_ok is False:
            signals["test_pass_rate"] = 0.0
        else:
            # No real shell command ran — use coverage as a proxy
            signals["test_pass_rate"] = min(1.0, coverage / 100.0)

    if "blast_radius" in declared:
        if review_score is not None:
            signals["blast_radius"] = round(max(0.0, 1.0 - review_score), 2)
        else:
            signals["blast_radius"] = 0.1 if review_outcome == "pass" else 0.5

    for sig in ("accuracy", "relevance"):
        if sig in declared:
            signals[sig] = float(review_score) if review_score is not None else (
                1.0 if review_outcome == "pass" else 0.5
            )

    if "trust_utilization" in declared or "token_efficiency" in declared:
        passed = sum(1 for pr in phase_results if getattr(pr, "outcome", "") == "pass")
        rate = passed / max(len(phase_results), 1)
        if "trust_utilization" in declared:
            signals["trust_utilization"] = rate
        if "token_efficiency" in declared:
            signals["token_efficiency"] = rate

    for sig in ("success_rate", "pipeline_success", "delegation_success"):
        if sig in declared:
            any_fail = any(getattr(pr, "outcome", "") == "fail" for pr in phase_results)
            signals[sig] = 0.0 if any_fail else 1.0

    if "rollback_triggered" in declared:
        signals["rollback_triggered"] = 1.0 if rollback else 0.0

    if "token_cost" in declared:
        signals["token_cost"] = float(token_cost)

    if "latency" in declared:
        signals["latency"] = float(latency_ms)

    # Zeros for signals with no data source yet
    for name in declared:
        if name not in signals:
            signals[name] = 0.0

    # ── Agent used: prefer actual BUILD dispatch provider ─────────────────
    agent_used = harness_config.primary_agent.agent_id
    for pr in reversed(phase_results):
        if getattr(getattr(pr, "phase", None), "value", "") == "Build":
            usage = (getattr(pr, "artifacts", {}) or {}).get("dispatch_usage") or {}
            if isinstance(usage, dict) and usage.get("provider_id"):
                agent_used = usage["provider_id"]
                break

    return HarnessOutcome(
        harness_id=harness_config.harness_id,
        task_id=str(getattr(task, "task_id", "")),
        task_class=harness_config.task_class,
        quality_signals=signals,
        token_cost_actual=token_cost,
        latency_ms=latency_ms,
        human_interventions=human_interventions,
        rollback_triggered=rollback,
        trust_gate_result=harness_config.trust_gate_result,
        agent_used=agent_used,
        assembler_version=harness_config.assembler_version,
    )
