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

try:
    from .permissions import PermissionMode
except ImportError:
    from permissions import PermissionMode

try:
    from .runtime.agent_spec import AgentSpec
except ImportError:
    try:
        from runtime.agent_spec import AgentSpec
    except ImportError:
        AgentSpec = Any  # type: ignore[assignment,misc]


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
    isolation_mode: str = "none"  # none | worktree | container
    isolation_cleanup: str = "auto"  # auto | manual

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

    # Declarative user-agent bindings (T5.2)
    tool_bindings: list[dict[str, Any]] = field(default_factory=list)
    agent_spec_key: str | None = None

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
        d.setdefault("tool_bindings", [])
        d.setdefault("agent_spec_key", None)
        d.setdefault("isolation_mode", "none")
        d.setdefault("isolation_cleanup", "auto")

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
        available_providers: list[str] | None = None,
        health_scores: dict[str, float] | None = None,
    ) -> HarnessConfig:
        """Build a HarnessConfig from TaskClass defaults."""
        defaults = TASK_CLASS_DEFAULTS[task_class]
        signals = [QualitySignalDef(name=name) for name in defaults.quality_signals]
        primary_agent = resolve_agent_binding(
            defaults.agent_preference,
            available_providers=available_providers,
            health_scores=health_scores,
        )
        fallback_agents = _build_fallback_agents(
            primary_agent.agent_id,
            available_providers=available_providers,
            health_scores=health_scores,
        )
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
            fallback_agents=fallback_agents,
        )

    @classmethod
    def from_agent_spec(
        cls,
        spec: "AgentSpec",
        task_id: str,
        ncp_enabled: bool = False,
        available_providers: list[str] | None = None,
        health_scores: dict[str, float] | None = None,
    ) -> HarnessConfig:
        """Build a HarnessConfig from a declarative AgentSpec."""
        defaults = TASK_CLASS_DEFAULTS[spec.task_class]
        signals = [QualitySignalDef(name=name) for name in defaults.quality_signals]
        if spec.provider:
            primary_agent = AgentBinding(agent_id=spec.provider, model=spec.model)
            if health_scores and spec.provider in health_scores:
                primary_agent.health_score = health_scores[spec.provider]
        else:
            primary_agent = resolve_agent_binding(
                defaults.agent_preference,
                available_providers=available_providers,
                health_scores=health_scores,
            )
            if spec.model:
                primary_agent.model = spec.model
        fallback_agents = _build_fallback_agents(
            primary_agent.agent_id,
            available_providers=available_providers,
            health_scores=health_scores,
        )
        return cls(
            task_id=task_id,
            task_class=spec.task_class,
            context_scope=defaults.context_scope,
            permission_scope=defaults.permission_scope,
            requires_human_approval=defaults.human_in_loop,
            ncp_enabled=ncp_enabled,
            quality_signals=signals,
            defaults=defaults,
            primary_agent=primary_agent,
            fallback_agents=fallback_agents,
            tool_bindings=[tool.to_artifact() for tool in spec.tools],
            agent_spec_key=spec.key,
        )


_PREFERENCE_TO_PROVIDER: dict[str, str] = {
    "fastest":            "local",
    "balanced":           "local",
    "highest_capability": "claude",
    "sarathi_native":     "local",
}

# Static preference order for fallback candidates when a primary agent fails.
_FALLBACK_PROVIDER_ORDER: list[str] = ["claude", "codex", "opencode"]


_PERMISSION_MODE_BY_SCOPE: dict[str, PermissionMode] = {
    "read_only": PermissionMode.READ_ONLY,
    "read_plus_idempotent": PermissionMode.READ_ONLY,
    "repo_write": PermissionMode.READ_WRITE,
    "repo_write_scoped": PermissionMode.READ_WRITE,
    "config_write_declared": PermissionMode.READ_WRITE,
    "infra_write_declared": PermissionMode.FULL,
    "data_write_declared": PermissionMode.FULL,
    "child_scope_union": PermissionMode.FULL,
    "harness_engine_write": PermissionMode.FULL,
    "ncp_store_write": PermissionMode.FULL,
}


def derive_permission_mode(permission_scope: str | PermissionMode | None) -> PermissionMode:
    """Collapse detailed Sarathi permission scopes into provider-native modes."""
    if isinstance(permission_scope, PermissionMode):
        return permission_scope
    if not isinstance(permission_scope, str):
        return PermissionMode.READ_ONLY
    return _PERMISSION_MODE_BY_SCOPE.get(permission_scope.strip(), PermissionMode.READ_ONLY)


def resolve_agent_binding(
    agent_preference: str,
    available_providers: list[str] | None = None,
    health_scores: dict[str, float] | None = None,
) -> AgentBinding:
    """Map an AssemblyDefaults.agent_preference string to a concrete AgentBinding."""
    provider_id = _PREFERENCE_TO_PROVIDER.get(agent_preference, "local")
    if available_providers and provider_id not in available_providers:
        provider_id = available_providers[0] if available_providers else "local"
    binding = AgentBinding(agent_id=provider_id)
    if health_scores and provider_id in health_scores:
        binding.health_score = health_scores[provider_id]
    return binding


def _build_fallback_agents(
    primary_provider_id: str,
    available_providers: list[str] | None = None,
    health_scores: dict[str, float] | None = None,
) -> list[AgentBinding]:
    """Build the ordered fallback agent list for a resolved primary agent.

    Fallbacks are the OTHER distinct providers from ``_FALLBACK_PROVIDER_ORDER``,
    minus the primary, filtered to ``available_providers``. When
    ``available_providers`` is None we don't fabricate availability — the
    fallback list stays empty.

    The candidate set itself is still ``_FALLBACK_PROVIDER_ORDER`` (primary
    selection semantics are untouched) but the final ordering is health-aware:
    once every candidate's ``health_score`` is known, the list is sorted by
    descending score so a fallback that's been failing a lot sinks below one
    that's been healthy, even if the static order says otherwise. The sort is
    stable, so candidates with equal (e.g. default 1.0, or entirely unknown)
    scores keep their original ``_FALLBACK_PROVIDER_ORDER`` relative order.
    """
    if not available_providers:
        return []
    fallbacks: list[AgentBinding] = []
    for provider_id in _FALLBACK_PROVIDER_ORDER:
        if provider_id == primary_provider_id:
            continue
        if provider_id not in available_providers:
            continue
        binding = AgentBinding(agent_id=provider_id)
        if health_scores and provider_id in health_scores:
            binding.health_score = health_scores[provider_id]
        fallbacks.append(binding)
    fallbacks.sort(key=lambda binding: -binding.health_score)
    return fallbacks


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
    # Per declared signal: "measured" (real data), "derived" (computed from
    # other real phase data), or "missing" (no data source — not fabricated).
    signal_provenance: dict[str, str] = field(default_factory=dict)


def measure_outcome(task: Any, harness_config: HarnessConfig) -> HarnessOutcome:
    """
    Extract real quality signals from a completed task's phase_results.

    Sources:
      test_pass_rate  — VERIFY command_succeeded (absent when no command ran)
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
    # A declared signal with no real data source stays absent from the dict
    # (provenance "missing") rather than being filled with a flattering or
    # punishing default — fabricated values would poison the learning loop.
    signals: dict[str, float] = {}
    provenance: dict[str, str] = {}

    if "test_pass_rate" in declared:
        cmd_ok = verify_summary.get("command_succeeded")
        if cmd_ok is True:
            signals["test_pass_rate"] = 1.0
            provenance["test_pass_rate"] = "measured"
        elif cmd_ok is False:
            signals["test_pass_rate"] = 0.0
            provenance["test_pass_rate"] = "measured"
        else:
            provenance["test_pass_rate"] = "missing"

    review_seen = review_score is not None or any(
        getattr(getattr(pr, "phase", None), "value", "") == "Review" for pr in phase_results
    )

    if "blast_radius" in declared:
        if review_score is not None:
            signals["blast_radius"] = round(max(0.0, 1.0 - review_score), 2)
            provenance["blast_radius"] = "measured"
        elif review_seen:
            signals["blast_radius"] = 0.1 if review_outcome == "pass" else 0.5
            provenance["blast_radius"] = "derived"
        else:
            provenance["blast_radius"] = "missing"

    for sig in ("accuracy", "relevance"):
        if sig in declared:
            if review_score is not None:
                signals[sig] = float(review_score)
                provenance[sig] = "measured"
            elif review_seen:
                signals[sig] = 1.0 if review_outcome == "pass" else 0.5
                provenance[sig] = "derived"
            else:
                provenance[sig] = "missing"

    if "trust_utilization" in declared or "token_efficiency" in declared:
        passed = sum(1 for pr in phase_results if getattr(pr, "outcome", "") == "pass")
        rate = passed / max(len(phase_results), 1)
        if "trust_utilization" in declared:
            signals["trust_utilization"] = rate
            provenance["trust_utilization"] = "derived"
        if "token_efficiency" in declared:
            signals["token_efficiency"] = rate
            provenance["token_efficiency"] = "derived"

    for sig in ("success_rate", "pipeline_success", "delegation_success"):
        if sig in declared:
            any_fail = any(getattr(pr, "outcome", "") == "fail" for pr in phase_results)
            signals[sig] = 0.0 if any_fail else 1.0
            provenance[sig] = "derived"

    if "rollback_triggered" in declared:
        signals["rollback_triggered"] = 1.0 if rollback else 0.0
        provenance["rollback_triggered"] = "measured"

    if "token_cost" in declared:
        signals["token_cost"] = float(token_cost)
        provenance["token_cost"] = "measured"

    if "latency" in declared:
        signals["latency"] = float(latency_ms)
        provenance["latency"] = "measured"

    for name in declared:
        provenance.setdefault(name, "missing")

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
        signal_provenance=provenance,
    )
