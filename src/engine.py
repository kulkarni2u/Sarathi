"""Core engine logic for Sarathi - Workflow orchestration framework."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger("sarathi.engine")

# Harness Engine imports
try:
    from .task_class import TaskClass, classify_task_class, from_legacy_type
    from .harness import HarnessConfig, HarnessOutcome, derive_permission_mode
    from .permissions import PermissionScope, build_permission_scope
    from .trust_gate import TrustGate, TrustGateResult, arbitrate
    from .notifications import budget_exhausted_event, build_slack_notifier, phase_event
    from .engine_mirror import EngineRunRecorder
except ImportError:
    from task_class import TaskClass, classify_task_class, from_legacy_type
    from harness import HarnessConfig, HarnessOutcome, derive_permission_mode
    from permissions import PermissionScope, build_permission_scope
    from trust_gate import TrustGate, TrustGateResult, arbitrate
    from notifications import budget_exhausted_event, build_slack_notifier, phase_event
    from engine_mirror import EngineRunRecorder

try:
    from .runtime.providers.registry import all_specs as _all_provider_specs
except ImportError:
    from runtime.providers.registry import all_specs as _all_provider_specs

try:
    from .dispatch import Dispatcher, LocalDispatcher, require_harness_id
    from .phases import (
        BrainstormHandler,
        BuildHandler,
        EleganceHandler,
        LearnHandler,
        PhaseLogHandler,
        PlanHandler,
        PlanningAdvisorHandler,
        RiskCheckHandler,
        ReviewHandler,
        TaskTrackingHandler,
        VerifyHandler,
    )
    from .policy import compile_policy_pack
    from .runtime import (
        AgentSpec,
        ArtifactStore,
        apply_learning_feedback_to_provider_routing,
        build_sandbox_executor,
        CommandRunner,
        DispatchJournal,
        DispatchRequest,
        GateEvidencePolicy,
        GateResult,
        PreflightPolicy,
        ProviderHealthStore,
        RecoveryRunner,
        RoleSubrolePolicy,
        register_agent_role,
        TaskBudget,
        phase_agent_role_artifact,
        ContextCompiler,
    )
    from .task_graph import annotate_graph_for_supervision
except ImportError:
    from dispatch import Dispatcher, LocalDispatcher, require_harness_id
    from phases import (
        BrainstormHandler,
        BuildHandler,
        EleganceHandler,
        LearnHandler,
        PhaseLogHandler,
        PlanHandler,
        PlanningAdvisorHandler,
        RiskCheckHandler,
        ReviewHandler,
        TaskTrackingHandler,
        VerifyHandler,
    )
    from policy import compile_policy_pack
    from runtime import (
        AgentSpec,
        ArtifactStore,
        apply_learning_feedback_to_provider_routing,
        build_sandbox_executor,
        CommandRunner,
        DispatchJournal,
        DispatchRequest,
        GateEvidencePolicy,
        GateResult,
        PreflightPolicy,
        ProviderHealthStore,
        RecoveryRunner,
        RoleSubrolePolicy,
        register_agent_role,
        TaskBudget,
        phase_agent_role_artifact,
        ContextCompiler,
    )
    from task_graph import annotate_graph_for_supervision

# NCP adapter imports
try:
    from .ncp_adapter import (
        NCPAdapterConfig,
        NCPNotAvailableError,
        NCPContextAdapter,
        NCPPersistenceAdapter,
        NCPArtifactAdapter,
        NCPWhisperRouter,
    )
except ImportError:
    from ncp_adapter import (
        NCPAdapterConfig,
        NCPNotAvailableError,
        NCPContextAdapter,
        NCPPersistenceAdapter,
        NCPArtifactAdapter,
        NCPWhisperRouter,
    )


class Phase(Enum):
    """The 12-phase Sarathi lifecycle."""
    ROUTE = "Route"
    BRAINSTORM = "Brainstorm"
    PLANNING_ADVISOR = "PlanningAdvisor"
    PLAN = "Plan"
    BUILD = "Build"
    VERIFY = "Verify"
    REVIEW = "Review"
    TASK_TRACKING = "TaskTracking"
    RISK_CHECK = "RiskCheck"
    ELEGANCE = "Elegance"
    PHASE_LOG = "PhaseLog"
    LEARN = "Learn"


class Complexity(Enum):
    """Task complexity classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Explicit phase transitions based on Sarathi workflow.md
PHASE_TRANSITIONS = {
    Phase.ROUTE: Phase.BRAINSTORM,
    Phase.BRAINSTORM: Phase.PLANNING_ADVISOR,  # Only for HIGH complexity
    Phase.PLANNING_ADVISOR: Phase.PLAN,
    Phase.PLAN: Phase.BUILD,
    Phase.BUILD: Phase.VERIFY,
    Phase.VERIFY: Phase.REVIEW,
    Phase.REVIEW: Phase.TASK_TRACKING,
    Phase.TASK_TRACKING: Phase.RISK_CHECK,
    Phase.RISK_CHECK: Phase.ELEGANCE,
    Phase.ELEGANCE: Phase.PHASE_LOG,
    Phase.PHASE_LOG: Phase.LEARN,
}

# Phases to skip for LOW/MEDIUM complexity
SKIP_FOR_LOW = {Phase.PLANNING_ADVISOR}
SKIP_FOR_MEDIUM = {Phase.PLANNING_ADVISOR}


@dataclass
class PolicyPack:
    """Container for loaded policy pack data."""
    complexity: dict[str, Any] = field(default_factory=dict)
    conventions: dict[str, Any] = field(default_factory=dict)
    commands: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    escalation: dict[str, Any] = field(default_factory=dict)
    model_routing: dict[str, Any] = field(default_factory=dict)
    skills: dict[str, Any] = field(default_factory=dict)
    task_tracking: dict[str, Any] = field(default_factory=dict)
    learning_feedback: dict[str, Any] = field(default_factory=dict)
    workflow_patterns: dict[str, Any] = field(default_factory=dict)
    notifications: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseResult:
    """Outcome of executing a single lifecycle phase."""

    phase: Phase
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    decisions: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    error: str | None = None


class PhaseHandler:
    """Base class for phase handlers."""

    def __init__(self, policy_pack: PolicyPack, dispatcher: Dispatcher | None = None):
        self.policy_pack = policy_pack
        self.dispatcher = dispatcher

    def execute(self, task: TaskContext, phase: Phase) -> PhaseResult:
        """Execute the phase. Override in subclasses."""
        raise NotImplementedError

    def _load_policy_section(self, policy_name: str) -> dict[str, Any]:
        """Load a policy section from the policy pack."""
        return getattr(self.policy_pack, policy_name, {})

    def _parse_yaml_from_markdown(self, content: str) -> dict[str, Any]:
        """Extract and parse YAML blocks from markdown content."""
        yaml_blocks = re.findall(r'```yaml\s*(.*?)\s*```', content, re.DOTALL)
        if yaml_blocks:
            try:
                return yaml.safe_load(yaml_blocks[0])
            except yaml.YAMLError:
                pass
        return {}


class RouteHandler(PhaseHandler):
    """Handler for the ROUTE phase."""

    def __init__(
        self,
        policy_pack: PolicyPack,
        dispatcher: Dispatcher | None = None,
        ncp_enabled: bool = False,
        harness_cache: dict | None = None,
    ):
        super().__init__(policy_pack, dispatcher)
        self.ncp_enabled = ncp_enabled
        self._harness_cache: dict[str, HarnessConfig] = harness_cache if harness_cache is not None else {}

    def execute(self, task: TaskContext, phase: Phase) -> PhaseResult:
        """Route the task — classify TaskClass, select assembly mode, emit HarnessConfig."""
        agent_spec = getattr(task, "agent_spec", None)
        legacy_type = self._classify_task_type(task.description)
        workflow_path = self._select_workflow_path(task, legacy_type)

        if agent_spec is not None:
            task_class = agent_spec.task_class
            assembly_mode = "STANDARD"
            harness = HarnessConfig.from_agent_spec(agent_spec, task.task_id, ncp_enabled=self.ncp_enabled)
            harness.assembly_mode = assembly_mode
            perm_scope = build_permission_scope(task_class)
            harness.requires_human_approval = perm_scope.requires_human_approval
        else:
            task_class = classify_task_class(task.description)

            # Assembly mode: DEEP for mutation/evolution, FAST for cache hit, STANDARD otherwise
            is_deep = task_class.value.startswith(("mutation/", "evolution/"))
            cache_hit = None if is_deep else self._harness_cache.get(task_class.value)

            if is_deep:
                assembly_mode = "DEEP"
            elif cache_hit is not None:
                assembly_mode = "FAST"
            else:
                assembly_mode = "STANDARD"

            if assembly_mode == "FAST":
                # Reuse cached config skeleton — freshen identity fields only
                harness = HarnessConfig.from_json(cache_hit.to_json())
                harness.harness_id = str(uuid.uuid4())[:8]
                harness.task_id = task.task_id
                harness.assembled_at = datetime.utcnow().isoformat()
                harness.trace_id = str(uuid.uuid4())
                harness.assembly_mode = "FAST"
            else:
                harness = HarnessConfig.from_task_class(task_class, task.task_id, ncp_enabled=self.ncp_enabled)
                harness.assembly_mode = assembly_mode
                perm_scope = build_permission_scope(task_class)
                harness.requires_human_approval = perm_scope.requires_human_approval
                if assembly_mode == "STANDARD":
                    self._harness_cache[task_class.value] = harness

        role_plan = RoleSubrolePolicy.from_skills_section(self.policy_pack.skills).role_plan(
            task_description=task.description,
            file_paths=self._task_file_paths(task),
        )
        harness.role_plan = role_plan
        harness_dict = json.loads(harness.to_json())

        evidence = {
            "task_type": legacy_type,
            "task_class": task_class.value,
            "workflow_path": workflow_path,
            "complexity_assessed": True,
            "harness_assembled": True,
            "requires_human_approval": harness.requires_human_approval,
            "assembly_mode": assembly_mode,
            "cache_hit": assembly_mode == "FAST",
            "subroles_selected": role_plan["selected_count"],
        }

        artifacts = {
            "routing_decision": workflow_path,
            "task_class": task_class.value,
            "harness_config": harness_dict,
            "permission_scope": harness.permission_scope,
            "permission_mode": derive_permission_mode(harness.permission_scope).value,
            "assembly_mode": assembly_mode,
            "role_plan": role_plan,
        }

        if agent_spec is not None:
            evidence["agent_spec_key"] = agent_spec.key
            artifacts["agent_spec_key"] = agent_spec.key

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts=artifacts,
        )

    def _task_file_paths(self, task: TaskContext) -> list[str]:
        """Extract optional file hints from task metadata for subrole routing."""
        file_paths: list[str] = []
        for key in ("files", "file_paths", "changed_files", "paths"):
            value = task.complexity_evidence.get(key)
            if isinstance(value, str):
                file_paths.append(value)
            elif isinstance(value, list):
                file_paths.extend(str(item) for item in value if str(item).strip())
        return file_paths

    def _classify_task_type(self, description: str) -> str:
        """Legacy ad-hoc task type string (preserved for backward compatibility)."""
        desc_lower = description.lower()

        if any(word in desc_lower for word in ['bug', 'fix', 'error', 'issue']):
            return 'bug'
        elif any(word in desc_lower for word in ['feature', 'add', 'implement', 'create']):
            return 'feature'
        elif any(word in desc_lower for word in ['refactor', 'clean', 'optimize']):
            return 'refactor'
        elif any(word in desc_lower for word in ['docs', 'documentation', 'readme']):
            return 'docs'
        elif any(word in desc_lower for word in ['deploy', 'release', 'publish']):
            return 'deploy'
        else:
            return 'feature'  # default

    def _select_workflow_path(self, task: TaskContext, task_type: str) -> str:
        """Select workflow path based on task characteristics."""
        if task.complexity == Complexity.HIGH:
            return 'full'
        elif task.complexity == Complexity.MEDIUM:
            return 'accelerated'
        else:
            return 'minimal'


class PersistenceManager:
    """Manages persistence of task contexts and phase logs."""

    def __init__(self, storage_path: str | None = None):
        self.storage_path = Path(storage_path or ".sarathi/tasks")
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def save_task(self, task: TaskContext) -> None:
        """Save a task context to disk."""
        task_file = self.storage_path / f"{task.task_id}.json"

        # Convert task to serializable format
        harness_dict = None
        if getattr(task, "harness_config", None) is not None:
            harness_dict = json.loads(task.harness_config.to_json())

        task_data = {
            "task_id": task.task_id,
            "description": task.description,
            "complexity": task.complexity.value,
            "complexity_evidence": task.complexity_evidence,
            "preflight_validation": task.preflight_validation,
            "budget_snapshot": task.budget_snapshot,
            "crash_reconciliation": task.crash_reconciliation,
            "task_graph_state": task.task_graph_state,
            "current_phase": task.current_phase.value if task.current_phase else None,
            "task_class": getattr(task, "task_class", TaskClass.ANALYSIS).value,
            "harness_config": harness_dict,
            "phase_results": [
                {
                    "phase": pr.phase.value,
                    "outcome": pr.outcome,
                    "iterations": pr.iterations,
                    "decisions": pr.decisions,
                    "artifacts": pr.artifacts,
                    "evidence": pr.evidence,
                    "artifact_refs": pr.artifact_refs,
                    "error": pr.error,
                }
                for pr in task.phase_results
            ],
            "last_updated": datetime.now().isoformat(),
        }

        with open(task_file, 'w') as f:
            json.dump(task_data, f, indent=2)

    def load_task(self, task_id: str) -> TaskContext | None:
        """Load a task context from disk."""
        task_file = self.storage_path / f"{task_id}.json"

        if not task_file.exists():
            return None

        try:
            with open(task_file, 'r') as f:
                task_data = json.load(f)

            # Reconstruct TaskContext
            raw_task_class = task_data.get("task_class", "analysis")
            try:
                restored_task_class = TaskClass(raw_task_class)
            except ValueError:
                restored_task_class = TaskClass.ANALYSIS

            task = TaskContext(
                task_id=task_data["task_id"],
                description=task_data["description"],
                complexity=Complexity(task_data["complexity"]),
                complexity_evidence=task_data.get("complexity_evidence", {}),
                preflight_validation=task_data.get("preflight_validation", {}),
                task_graph_state=task_data.get("task_graph_state", {}),
                task_class=restored_task_class,
                budget_snapshot=task_data.get("budget_snapshot"),
                crash_reconciliation=task_data.get("crash_reconciliation"),
            )

            task.current_phase = Phase(task_data["current_phase"]) if task_data.get("current_phase") else None

            harness_raw = task_data.get("harness_config")
            if isinstance(harness_raw, dict):
                try:
                    task.harness_config = HarnessConfig.from_json(json.dumps(harness_raw))
                except Exception:
                    task.harness_config = None

            # Reconstruct phase results
            for pr_data in task_data.get("phase_results", []):
                pr = PhaseResult(
                    phase=Phase(pr_data["phase"]),
                    outcome=pr_data["outcome"],
                    iterations=pr_data.get("iterations", 0),
                    decisions=pr_data.get("decisions", []),
                    artifacts=pr_data.get("artifacts", {}),
                    evidence=pr_data.get("evidence", {}),
                    artifact_refs=pr_data.get("artifact_refs", []),
                    error=pr_data.get("error"),
                )
                task.phase_results.append(pr)

            return task

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error loading task {task_id}: {e}")
            return None

    def list_tasks(self) -> list[str]:
        """List all saved task IDs."""
        if not self.storage_path.exists():
            return []

        return [f.stem for f in self.storage_path.glob("*.json")]

    def save_phase_log(self, task: TaskContext, phase: Phase, status: str) -> None:
        """Save a phase transition log entry."""
        log_file = self.storage_path / f"{task.task_id}_phases.log"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "task_id": task.task_id,
            "phase": phase.value,
            "status": status,
            "complexity": task.complexity.value,
        }

        with open(log_file, 'a') as f:
            json.dump(log_entry, f)
            f.write('\n')

    def log_cost(self, *args, **kwargs) -> None:
        """Log cost (no-op for native PersistenceManager)."""
        pass


@dataclass
class TaskContext:
    """Context for a task being executed through the lifecycle."""
    task_id: str
    description: str
    complexity: Complexity = Complexity.MEDIUM
    complexity_evidence: dict[str, Any] = field(default_factory=dict)
    preflight_validation: dict[str, Any] = field(default_factory=dict)
    task_graph_state: dict[str, Any] = field(default_factory=dict)
    phase_results: list[PhaseResult] = field(default_factory=list)
    current_phase: Phase | None = None
    task_class: TaskClass = TaskClass.ANALYSIS
    harness_config: HarnessConfig | None = None
    gate_retry_hint: dict | None = field(default=None)
    budget_snapshot: dict[str, Any] | None = None
    crash_reconciliation: list[dict[str, Any]] | None = None
    # Declarative user agent (set by the CLI for `--agent <name>` runs).
    # Transient: not persisted by PersistenceManager.save_task/load_task.
    agent_spec: AgentSpec | None = None

    def get_completed_phases(self) -> set[Phase]:
        """Get set of phases that have been completed."""
        return {pr.phase for pr in self.phase_results}

    def get_phase_log_entry(self) -> dict[str, Any]:
        """Generate a phase log entry for the most recent phase."""
        if not self.phase_results:
            return {}
        last = self.phase_results[-1]
        return {
            "timestamp": self._get_timestamp(),
            "from": last.phase.value,
            "outcome": last.outcome,
            "iterations": last.iterations,
            "decisions": last.decisions,
        }

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat()


def _provider_session_constraint_keys() -> dict[str, str]:
    """Map provider name -> its session-resume constraint key (e.g. claude -> claude_session_id).

    Sourced from the provider registry so adding a new native provider spec
    (see cli_bridge.py's "one spec, not a 10-file surgery" seam) automatically
    gets session continuity here without touching this file.
    """
    try:
        specs = _all_provider_specs()
    except Exception:
        return {}
    return {
        name: spec.session_constraint_key
        for name, spec in specs.items()
        if spec.session_constraint_key
    }


class _HarnessAwareDispatcher:
    """Wraps any dispatcher and injects the harness-resolved preferred agent.

    Reads preferred_agent at dispatch time so RouteHandler can set it after
    the ROUTE phase without needing to rebuild phase handlers.

    Also threads provider session continuity across phases: when a CLI
    dispatch returns a session_id, later dispatches to that same provider in
    the same task resume it (--resume / --session / resume <id>, depending on
    provider) so the provider keeps its working context instead of replaying
    the full context pack from scratch each phase. Tracked per-provider (not
    just Claude) since BUILD's graph-node dispatches default to opencode.
    """

    def __init__(self, base: Any) -> None:
        self._base = base
        self.preferred_agent: str | None = None
        self.preferred_permission_mode: str | None = None
        self.session_ids: dict[str, str] = {}
        self.fallback_agents: list[str] = []
        self.journal: Any | None = None
        self.workspace_root: str | None = None
        # The harness_id of the HarnessConfig compiled for the current task
        # (set by _sync_task_state after ROUTE runs). Backfilled onto every
        # dispatch that doesn't already carry its own harness_id, so
        # phase-level dispatch stays traceable to the declared harness even
        # though phase modules don't set it themselves.
        self.harness_id: str | None = None

    def reset_task_state(self) -> None:
        """Clear per-task routing/session state before a new task starts."""
        self.preferred_agent = None
        self.preferred_permission_mode = None
        self.session_ids = {}
        self.fallback_agents = []
        self.harness_id = None

    def dispatch(self, request: DispatchRequest) -> Any:
        injected_provider = False
        if self.preferred_agent and not request.constraints.get("provider"):
            request = _dc_replace(
                request,
                constraints={**request.constraints, "provider": self.preferred_agent},
            )
            injected_provider = True
        effective_provider = request.constraints.get("provider")
        if self.session_ids and effective_provider:
            constraint_key = _provider_session_constraint_keys().get(effective_provider)
            session_id = self.session_ids.get(effective_provider)
            if constraint_key and session_id and not request.constraints.get(constraint_key):
                request = _dc_replace(
                    request,
                    constraints={**request.constraints, constraint_key: session_id},
                )
        if self.preferred_permission_mode and not request.constraints.get("permission_mode"):
            request = _dc_replace(
                request,
                constraints={
                    **request.constraints,
                    "permission_mode": self.preferred_permission_mode,
                },
            )
        if self.harness_id and not request.harness_id:
            request = _dc_replace(request, harness_id=self.harness_id)
        # Health-ordered fallback providers for LocalDispatcher's transient-
        # failure failover (see LocalDispatcher._attempt_provider_fallback).
        if self.fallback_agents and not request.constraints.get("fallback_providers"):
            request = _dc_replace(
                request,
                constraints={**request.constraints, "fallback_providers": list(self.fallback_agents)},
            )
        # "Declare before dispatch": graph-node/child-task dispatches must
        # carry a harness_id proving a HarnessConfig was compiled before this
        # call. Scoped to purpose == "child_task_execution" (see
        # TaskGraphExecutor) so single-task phase dispatch, which doesn't yet
        # thread a harness_id through, is unaffected.
        require_harness_id(request)
        # CLI-backed providers flake more than the deterministic local one —
        # give a non-local provider one retry inside LocalDispatcher when the
        # caller didn't already set a retry budget.
        provider = request.constraints.get("provider")
        if request.retry_budget == 0 and provider and provider != "local":
            request = _dc_replace(request, retry_budget=1)

        journal_id = self._journal_begin(request)
        try:
            response = self._base.dispatch(request)
        except Exception as exc:
            self._journal_complete(journal_id, success=False, error=str(exc))
            raise
        self._journal_complete(
            journal_id,
            success=bool(getattr(response, "success", False)),
            error=getattr(response, "error", None),
        )
        self._track_session(response)

        if (
            not getattr(response, "success", True)
            and self.fallback_agents
            and injected_provider
        ):
            response = self._attempt_failover(request, response)

        return response

    def _journal_begin(self, request: DispatchRequest) -> str | None:
        """Record dispatch intent in the write-ahead journal, if configured.

        Never raises — journal failures must never block a dispatch.
        """
        if self.journal is None or not self.workspace_root:
            return None
        try:
            return self.journal.begin(
                task_id=request.task_id,
                phase=request.phase,
                provider=request.constraints.get("provider"),
                prompt=request.prompt,
                workspace_root=self.workspace_root,
            )
        except Exception:
            logger.exception("dispatch journal begin() failed for task %s", request.task_id)
            return None

    def _journal_complete(self, journal_id: str | None, *, success: bool, error: str | None) -> None:
        """Record dispatch completion in the write-ahead journal, if configured."""
        if self.journal is None or journal_id is None:
            return
        try:
            self.journal.complete(journal_id, success=success, error=error)
        except Exception:
            logger.exception("dispatch journal complete() failed for journal_id %s", journal_id)

    def _attempt_failover(self, request: DispatchRequest, response: Any) -> Any:
        """Retry a failed primary-agent dispatch against fallback providers.

        Only called when the failure belongs to the agent this wrapper chose
        (``injected_provider``), never when the caller pinned a provider
        explicitly. Skips failover entirely if the failed attempt already
        mutated the workspace.
        """
        evidence = getattr(response, "evidence", None) or {}
        change_count = (evidence.get("workspace_delta") or {}).get("change_count", 0)
        if change_count > 0:
            response.artifacts["failover_skipped"] = "workspace_already_modified"
            return response

        failed_provider = request.constraints.get("provider")
        attempted = [failed_provider]
        last_response = response
        last_error = response.error

        for fallback_agent in self.fallback_agents:
            fallback_request = _dc_replace(
                request,
                constraints={**request.constraints, "provider": fallback_agent},
            )
            attempted.append(fallback_agent)
            fallback_response = self._base.dispatch(fallback_request)
            self._track_session(fallback_response)

            if getattr(fallback_response, "success", False):
                fallback_response.artifacts["failover"] = {
                    "failed_provider": failed_provider,
                    "fallback_used": fallback_agent,
                    "attempted": attempted,
                }
                return fallback_response

            last_response = fallback_response
            last_error = fallback_response.error

        last_response.artifacts["failover"] = {
            "failed_provider": failed_provider,
            "fallback_used": None,
            "attempted": attempted,
        }
        if last_error is not None:
            last_response.error = last_error
        return last_response

    def _track_session(self, response: Any) -> None:
        artifacts = getattr(response, "artifacts", None)
        if not isinstance(artifacts, dict):
            return
        for provider, constraint_key in _provider_session_constraint_keys().items():
            session_id = artifacts.get(constraint_key)
            if isinstance(session_id, str) and session_id:
                self.session_ids[provider] = session_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


class Engine:
    """
    Core Sarathi engine.

    Executes tasks through the 12-phase lifecycle with:
    - Evidence-weighted confidence gates
    - Policy-driven phase execution
    - Sub-agent dispatch for complex phases
    """

    def __init__(
        self,
        policy_pack_path: str | None = None,
        dispatcher: Dispatcher | None = None,
        enforce_preflight: bool = False,
        # NCP integration params
        ncp_enabled: bool | None = None,
        ncp_mode: str = "direct",
        ncp_router: bool = False,
        ncp_endpoint: str = "http://127.0.0.1:4242/mcp",
    ):
        self.policy_pack_path = policy_pack_path or "policy-pack"
        self.compiled_policy = compile_policy_pack(self.policy_pack_path)
        self.policy_pack = self._load_policy_pack()
        self._gate_evidence_policy = GateEvidencePolicy.from_review(self.policy_pack.review)
        provider_config = apply_learning_feedback_to_provider_routing(
            self.compiled_policy.get("model_routing"),
            self.compiled_policy.get("learning_feedback"),
        )
        base_dispatcher = dispatcher or LocalDispatcher(provider_config=provider_config)
        self.dispatcher = _HarnessAwareDispatcher(base_dispatcher)
        self._harness_cache: dict[str, HarnessConfig] = {}
        self.enforce_preflight = enforce_preflight
        self.preflight_policy = PreflightPolicy()

        # NCP adapter wiring
        self.ncp_mode = ncp_mode
        self.ncp_router_enabled = ncp_router
        self.ncp_endpoint = ncp_endpoint
        self.ncp_run_path = self._find_ncp_run_path() if ncp_mode == "direct" else None

        # Auto-detect NCP when not explicitly enabled/disabled
        _ncp_explicit = ncp_enabled is not None
        if ncp_enabled is None:
            ncp_enabled = self._probe_ncp()
            if not ncp_enabled:
                print(
                    "[ncp] NCP not found — using native adapters. "
                    "To enable for this workspace: `sarathi init --ncp`. "
                    "Pass --no-ncp to silence this message."
                )

        # Validate NCP when enabled before creating adapters
        if ncp_enabled:
            try:
                self._validate_ncp_available()
            except NCPNotAvailableError:
                if _ncp_explicit:
                    raise
                print("[ncp] NCP validation failed, falling back to native adapters")
                ncp_enabled = False

        self.ncp_enabled = ncp_enabled

        if ncp_enabled:
            if not _ncp_explicit:
                print("[ncp] NCP detected — using NCP adapters for context, memory, and cost tracking")
            adapter_kwargs = {"mode": ncp_mode, "endpoint": ncp_endpoint}
            if self.ncp_run_path is not None:
                adapter_kwargs["run_path"] = self.ncp_run_path
            self.context_adapter = NCPContextAdapter(**adapter_kwargs)
            self.persistence = NCPPersistenceAdapter(**adapter_kwargs)
            self.artifact_store = NCPArtifactAdapter(**adapter_kwargs)
            self.whisper_router = NCPWhisperRouter(**adapter_kwargs) if ncp_router else None
        else:
            self.context_adapter = ContextCompiler()
            self.persistence = PersistenceManager()
            self.artifact_store = ArtifactStore()
            self.whisper_router = None

        # Provider health tracking — same base directory PersistenceManager
        # uses by default (".sarathi/tasks" -> ".sarathi"), independent of
        # whether NCP persistence is active.
        health_base_dir = getattr(self.persistence, "storage_path", Path(".sarathi/tasks")).parent
        self.provider_health = ProviderHealthStore(health_base_dir)

        # Crash-safe dispatch journal — same base directory as provider health.
        self.dispatch_journal = DispatchJournal(health_base_dir)
        self.workspace_root = os.environ.get("SARATHI_WORKDIR", os.getcwd())
        if hasattr(self.dispatcher, "journal"):
            self.dispatcher.journal = self.dispatch_journal
        if hasattr(self.dispatcher, "workspace_root"):
            self.dispatcher.workspace_root = self.workspace_root

        # Outbound notifications (Slack) — policy-gated, env holds the secret.
        self.notifier = build_slack_notifier(self.compiled_policy.get("notifications"))

        # Best-effort mirror into the service SQLite DB (web cockpit
        # visibility) — inactive unless .sarathi/sarathi.db already exists.
        self.run_recorder = EngineRunRecorder.try_create()

        self.phase_handlers = self._create_phase_handlers()
        self.recovery_runner = RecoveryRunner(
            dispatcher=self.dispatcher,
            escalation=getattr(self.policy_pack, "escalation", {}) or {},
        )
        self.phases = list(Phase)

    def _load_policy_section(self, policy_name: str) -> dict[str, Any]:
        """Return a parsed policy section (mirrors PhaseHandler._load_policy_section)."""
        return getattr(self.policy_pack, policy_name, {}) or {}

    def _load_policy_pack(self) -> PolicyPack:
        """Load the policy pack from markdown files."""
        pack = PolicyPack()
        for attr in (
            "complexity",
            "conventions",
            "commands",
            "review",
            "escalation",
            "model_routing",
            "skills",
            "task_tracking",
            "learning_feedback",
            "workflow_patterns",
            "permissions",
            "notifications",
        ):
            setattr(pack, attr, self.compiled_policy.get(attr))

        return pack

    def _parse_policy_content(self, content: str) -> dict[str, Any]:
        """Parse policy content from markdown."""
        # Extract YAML blocks
        yaml_blocks = re.findall(r'```yaml\s*(.*?)\s*```', content, re.DOTALL)
        if yaml_blocks:
            try:
                return yaml.safe_load(yaml_blocks[0])
            except yaml.YAMLError:
                pass

        # Fallback: extract key-value pairs from markdown
        result = {}
        lines = content.split('\n')
        for line in lines:
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                result[key.strip()] = value.strip()
        return result

    def _create_phase_handlers(self) -> dict[Phase, PhaseHandler]:
        """Create phase handler instances."""
        ncp_ctx = self.context_adapter if self.ncp_enabled else None
        ncp_art = self.artifact_store if self.ncp_enabled else None
        ncp_per = self.persistence if self.ncp_enabled else None
        ncp_whi = self.whisper_router  # already None when disabled
        return {
            Phase.ROUTE: RouteHandler(self.policy_pack, self.dispatcher, ncp_enabled=self.ncp_enabled, harness_cache=self._harness_cache),
            Phase.BRAINSTORM: BrainstormHandler(self.policy_pack, self.dispatcher),
            Phase.PLANNING_ADVISOR: PlanningAdvisorHandler(self.policy_pack, self.dispatcher),
            Phase.PLAN: PlanHandler(self.policy_pack, self.dispatcher),
            Phase.BUILD: BuildHandler(
                self.policy_pack,
                self.dispatcher,
                ncp_context_adapter=ncp_ctx,
                ncp_artifact_adapter=ncp_art,
                ncp_whisper_router=ncp_whi,
                ncp_persistence_adapter=ncp_per,
            ),
            Phase.VERIFY: VerifyHandler(self.policy_pack, self.dispatcher, command_runner=CommandRunner(sandbox=build_sandbox_executor(self.compiled_policy.get("execution") if isinstance(self.compiled_policy, dict) else None))),
            Phase.REVIEW: ReviewHandler(self.policy_pack, self.dispatcher),
            Phase.TASK_TRACKING: TaskTrackingHandler(self.policy_pack, self.dispatcher),
            Phase.RISK_CHECK: RiskCheckHandler(self.policy_pack, self.dispatcher),
            Phase.ELEGANCE: EleganceHandler(self.policy_pack, self.dispatcher),
            Phase.PHASE_LOG: PhaseLogHandler(self.policy_pack, self.dispatcher),
            Phase.LEARN: LearnHandler(self.policy_pack, self.dispatcher, provider_health=self.provider_health),
        }

    def generate_task_id(self, description: str) -> str:
        """Generate a unique task ID based on description and timestamp."""
        # Create a deterministic but unique ID
        # Use first 8 chars of UUID for uniqueness + timestamp for ordering
        unique_part = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        # Create a readable prefix from description
        words = description.lower().split()[:2]  # First 2 words
        prefix = "-".join(words)[:20]  # Limit length

        return f"{prefix}-{timestamp}-{unique_part}"

    def _reconcile_inflight_dispatches(self, task: TaskContext) -> None:
        """Reconcile any in-flight (intent-without-completion) journal entries.

        Called at the start of ``run_task``/``resume_task`` for a task_id that
        may have crashed mid-dispatch. For each unmatched intent, measures the
        current workspace against the snapshot taken before the dispatch and
        marks the entry reconciled so it isn't re-reported.

        If any reconciliation reveals a measured, non-empty workspace delta,
        attaches a ``crash_reconciliation`` list to the task (and to the most
        recent phase result's artifacts, if any). Never raises.
        """
        try:
            incomplete_entries = self.dispatch_journal.incomplete(task_id=task.task_id)
        except Exception:
            logger.exception("Failed to query incomplete dispatch journal entries for task %s", task.task_id)
            return
        if not incomplete_entries:
            return

        reconciliations: list[dict[str, Any]] = []
        for entry in incomplete_entries:
            try:
                result = self.dispatch_journal.reconcile(entry, self.workspace_root)
                self.dispatch_journal.mark_reconciled(entry.get("journal_id"))
            except Exception:
                logger.exception(
                    "Failed to reconcile in-flight dispatch journal entry for task %s", task.task_id
                )
                continue
            reconciliations.append(result)

        if not reconciliations:
            return

        unsafe = [r for r in reconciliations if not r.get("safe_to_rerun")]
        if unsafe:
            for r in unsafe:
                files = (r.get("workspace_delta") or {}).get("files_changed", [])
                logger.warning(
                    "Task %s: in-flight dispatch (phase=%s, provider=%s) crashed mid-run and "
                    "left measured workspace changes: %s",
                    task.task_id,
                    r.get("phase"),
                    r.get("provider"),
                    files,
                )
        else:
            logger.info(
                "Task %s: %d in-flight dispatch(es) found on resume; workspace unchanged for all (safe to rerun)",
                task.task_id,
                len(reconciliations),
            )

        task.crash_reconciliation = reconciliations
        if task.phase_results:
            task.phase_results[-1].artifacts["crash_reconciliation"] = reconciliations

        try:
            self.persistence.save_task(task)
        except Exception:
            logger.exception("Failed to persist task %s after dispatch journal reconciliation", task.task_id)

    def run_task(
        self,
        task: TaskContext,
        *,
        cancel_check: Callable[[], bool] | None = None,
        task_timeout: float | None = None,
    ) -> TaskContext:
        """Run a task through the full lifecycle.

        `cancel_check` and `task_timeout` enable cooperative cancellation: both
        default to None, leaving behavior identical to a plain call. When set,
        they are polled at each phase boundary (not mid-phase) — see
        `task.stop_reason`.
        """
        task.stop_reason = None
        if hasattr(self.dispatcher, "reset_task_state"):
            self.dispatcher.reset_task_state()
        self._reconcile_inflight_dispatches(task)
        if not task.preflight_validation:
            task.preflight_validation = self.preflight_validate_policy(task.task_id)
        self.persistence.save_task(task)
        if self.enforce_preflight and task.preflight_validation.get("blocking", False):
            task.current_phase = None
            self.persistence.save_task(task)
            return task

        budget = TaskBudget.from_escalation(self.policy_pack.escalation)
        budget_warned = False

        task.current_phase = Phase.ROUTE
        deadline = time.monotonic() + task_timeout if task_timeout else None

        while task.current_phase is not None and task.current_phase != Phase.LEARN:
            phase = task.current_phase

            if cancel_check is not None and cancel_check():
                task.stop_reason = "cancelled"
                self._log_phase(task, phase, "cancelled")
                self.persistence.save_task(task)
                return task
            if deadline is not None and time.monotonic() >= deadline:
                task.stop_reason = "timeout"
                self._log_phase(task, phase, "timed_out")
                self.persistence.save_task(task)
                return task

            if self._should_skip_phase(task, phase):
                skip_result = PhaseResult(
                    phase=phase,
                    outcome="skip",
                    decisions=[f"Skipped for {task.complexity.value} complexity"]
                )
                self._attach_agent_role(skip_result)
                self._attach_artifact_refs(task, skip_result)
                task.phase_results.append(skip_result)
                self._sync_task_state(task, skip_result)
                self._log_phase(task, phase, "skipped")
                task.current_phase = PHASE_TRANSITIONS.get(phase, Phase.LEARN)
                self.persistence.save_task(task)
                continue

            phase_results = self._execute_phase_with_recovery(task, phase)
            # Bounded gate retry for Brainstorm/Plan — runs at most once, advisory on double fail.
            phase_results[-1] = self._maybe_gate_retry(task, phase, phase_results[-1])
            for phase_result in phase_results:
                task.phase_results.append(phase_result)
                self._sync_task_state(task, phase_result)
                budget.add_phase_result_usage(phase_result.artifacts)
            result = phase_results[-1]
            task.budget_snapshot = budget.to_artifact()

            # Trust gate handshake after ROUTE (NCP mode only — degrades gracefully when NCP is off)
            if phase == Phase.ROUTE and task.harness_config is not None and self.ncp_enabled:
                gate_action = self._run_trust_gate(task)
                if gate_action == "ABORT_AND_ESCALATE":
                    self._log_phase(task, phase, "trust_gate_abort")
                    task.current_phase = Phase.LEARN
                    self.persistence.save_task(task)
                    break

            # Check for early exit conditions
            if result.outcome == "fail":
                # Log failure and move to Learn phase
                self._log_phase(task, phase, "failed")
                task.current_phase = Phase.LEARN
                self.persistence.save_task(task)
                break

            if self._should_pause_after_phase(result):
                self._log_phase(task, phase, "paused")
                task.current_phase = self._phase_override(result, phase)
                self.persistence.save_task(task)
                return task

            if result.outcome == "escalate":
                self._log_phase(task, phase, "escalated")
            else:
                self._log_phase(task, phase, "completed")
            task.current_phase = PHASE_TRANSITIONS.get(phase, Phase.LEARN)

            budget_state = budget.state()
            if budget_state == "warning" and not budget_warned:
                budget_warned = True
                logger.warning(
                    "Task %s budget warning: consumed %s/%s tokens",
                    task.task_id,
                    budget.consumed_tokens,
                    budget.max_total_tokens,
                )
            elif budget_state == "exhausted":
                result.artifacts["budget_exhausted"] = budget.to_artifact()
                logger.warning(
                    "Task %s budget exhausted: consumed %s/%s tokens (on_exhausted=%s)",
                    task.task_id,
                    budget.consumed_tokens,
                    budget.max_total_tokens,
                    budget.on_exhausted,
                )
                if budget.on_exhausted == "pause":
                    if self.notifier is not None:
                        self.notifier.notify(
                            budget_exhausted_event(
                                task.task_id,
                                task.description,
                                budget.consumed_tokens,
                                budget.max_total_tokens,
                            )
                        )
                    self.persistence.save_task(task)
                    return task

            self.persistence.save_task(task)

        # Execute final Learn phase
        learn_result = self._execute_phase(task, Phase.LEARN)
        task.phase_results.append(learn_result)
        self._sync_task_state(task, learn_result)
        task.current_phase = None
        self._log_phase(task, Phase.LEARN, "completed")
        self.persistence.save_task(task)

        return task

    def resume_task(
        self,
        task: TaskContext,
        *,
        cancel_check: Callable[[], bool] | None = None,
        task_timeout: float | None = None,
    ) -> TaskContext:
        """Resume a previously saved task from the next unresolved phase.

        `cancel_check` and `task_timeout` mirror `run_task`: polled at each
        phase boundary, see `task.stop_reason`.
        """
        task.stop_reason = None
        if not task.phase_results:
            return self.run_task(task, cancel_check=cancel_check, task_timeout=task_timeout)

        self._reconcile_inflight_dispatches(task)

        if Phase.LEARN in task.get_completed_phases():
            task.current_phase = None
            return task

        last_result = task.phase_results[-1]
        last_phase = last_result.phase
        if self._pause_requires_approval(last_result):
            approval = last_result.artifacts.get("approval")
            approved = isinstance(approval, dict) and approval.get("approved") is True
            if not approved:
                rejected = isinstance(approval, dict) and approval.get("approved") is False
                task.stop_reason = "rejected" if rejected else "approval_required"
                self.persistence.save_task(task)
                return task
        if self._should_pause_after_phase(last_result):
            next_phase = self._phase_override(last_result, last_phase)
        else:
            next_phase = PHASE_TRANSITIONS.get(last_phase, Phase.LEARN)
        while next_phase != Phase.LEARN and self._should_skip_phase(task, next_phase):
            skip_result = PhaseResult(
                phase=next_phase,
                outcome="skip",
                decisions=[f"Skipped for {task.complexity.value} complexity"],
            )
            self._attach_agent_role(skip_result)
            self._attach_artifact_refs(task, skip_result)
            task.phase_results.append(skip_result)
            self._sync_task_state(task, skip_result)
            self._log_phase(task, next_phase, "skipped")
            next_phase = PHASE_TRANSITIONS.get(next_phase, Phase.LEARN)
        task.current_phase = next_phase
        deadline = time.monotonic() + task_timeout if task_timeout else None

        while task.current_phase is not None and task.current_phase != Phase.LEARN:
            phase = task.current_phase

            if cancel_check is not None and cancel_check():
                task.stop_reason = "cancelled"
                self._log_phase(task, phase, "cancelled")
                self.persistence.save_task(task)
                return task
            if deadline is not None and time.monotonic() >= deadline:
                task.stop_reason = "timeout"
                self._log_phase(task, phase, "timed_out")
                self.persistence.save_task(task)
                return task

            phase_results = self._execute_phase_with_recovery(task, phase)
            for phase_result in phase_results:
                task.phase_results.append(phase_result)
                self._sync_task_state(task, phase_result)
            result = phase_results[-1]
            if result.outcome == "fail":
                self._log_phase(task, phase, "failed")
                task.current_phase = Phase.LEARN
                self.persistence.save_task(task)
                break
            if self._should_pause_after_phase(result):
                self._log_phase(task, phase, "paused")
                task.current_phase = self._phase_override(result, phase)
                self.persistence.save_task(task)
                return task
            self._log_phase(task, phase, "escalated" if result.outcome == "escalate" else "completed")
            task.current_phase = PHASE_TRANSITIONS.get(phase, Phase.LEARN)
            self.persistence.save_task(task)

        if task.current_phase == Phase.LEARN and Phase.LEARN not in task.get_completed_phases():
            learn_result = self._execute_phase(task, Phase.LEARN)
            task.phase_results.append(learn_result)
            self._sync_task_state(task, learn_result)
            task.current_phase = None
            self._log_phase(task, Phase.LEARN, "completed")
            self.persistence.save_task(task)

        return task

    def _should_pause_after_phase(self, result: PhaseResult) -> bool:
        """Return True when a phase result requests resumable pause semantics."""
        return bool(result.artifacts.get("pause_execution"))

    def _pause_requires_approval(self, result: PhaseResult) -> bool:
        """Return True when a resumable pause is approval-flavored, not ordinary.

        Most `pause_execution` pauses (see `src/phases/build.py`) are just
        "more graph nodes remain, call resume again" — those must keep
        resuming with a bare `resume_task` call, unchanged. A pause is
        approval-flavored only when the pausing phase also flagged
        `evidence["human_attention_required"]`: a graph node exhausted its
        retry budget and was moved to `waiting_human` (see
        `require_human_for_graph_node`), the same signal `sarathi log`
        already keys off to render an escalation summary. Only that narrower
        case is gated behind an explicit approval/rejection artifact.
        """
        return bool(result.artifacts.get("pause_execution")) and bool(
            result.evidence.get("human_attention_required")
        )

    def record_approval(
        self,
        task: TaskContext,
        *,
        approved_by: str,
        approve: bool = True,
        note: str | None = None,
    ) -> TaskContext:
        """Record a human approval decision on a task paused for approval.

        Attaches an `approval` artifact to the phase result that triggered
        the approval-flavored pause (see `_pause_requires_approval`) and
        persists the task via `self.persistence`. Approving clears the
        transient `approval_required` stop marker so the next `resume_task`
        call proceeds past the pause; rejecting sets
        `task.stop_reason = "rejected"` and leaves the pause in place — a
        rejected task never auto-advances, only a fresh approval unblocks it.

        Raises `ValueError` if the task has no phase history, or if its most
        recent phase result is not an approval-flavored pause.
        """
        if not task.phase_results:
            raise ValueError(f"Task {task.task_id} has no phase history to approve.")
        last_result = task.phase_results[-1]
        if not self._pause_requires_approval(last_result):
            raise ValueError(
                f"Task {task.task_id} is not paused on an approval-flavored escalation."
            )
        last_result.artifacts["approval"] = {
            "approved_by": approved_by,
            "approved_at": datetime.now().isoformat(),
            "approved": bool(approve),
            "note": note,
        }
        task.stop_reason = None if approve else "rejected"
        self.persistence.save_task(task)
        return task

    def _phase_override(self, result: PhaseResult, current_phase: Phase) -> Phase:
        """Resolve the next phase override from a phase result."""
        override = result.artifacts.get("next_phase_override")
        if isinstance(override, str):
            try:
                return Phase(override)
            except ValueError:
                pass
        return current_phase

    def _execute_phase_with_recovery(self, task: TaskContext, phase: Phase) -> list[PhaseResult]:
        """Execute a phase and bounded policy-controlled recovery retries."""
        results = [self._execute_phase(task, phase)]
        attempts = 0
        while self._should_run_recovery(results[-1], attempts):
            attempts += 1
            action = self.recovery_runner.execute(
                task_id=task.task_id,
                phase=phase.value,
                attempt=attempts,
                result=results[-1],
            )
            action_artifact = action.to_artifact()
            results[-1].artifacts.setdefault("recovery_actions", []).append(action_artifact)
            results[-1].evidence["recovery_executed"] = True
            results[-1].evidence["recovery_attempt"] = attempts
            self._attach_artifact_refs(task, results[-1])

            retry_result = self._execute_phase(task, phase)
            retry_result.iterations = attempts
            retry_result.decisions.append(f"Retried after recovery action {attempts}")
            retry_result.artifacts.setdefault("recovery_context", []).append(action_artifact)
            results.append(retry_result)
            if retry_result.outcome == "pass":
                break
        return results

    def _should_run_recovery(self, result: PhaseResult, completed_attempts: int) -> bool:
        """Return True when policy allows an executable recovery retry."""
        if result.phase not in {Phase.VERIFY, Phase.REVIEW}:
            return False
        if result.outcome == "pass":
            return False
        if not result.artifacts.get("retry_recommended"):
            return False
        if not result.artifacts.get("auto_fix_allowed"):
            return False
        policy = result.artifacts.get("quality_loop_policy", {})
        if not isinstance(policy, dict):
            return False
        auto_fix_attempts = int(policy.get("auto_fix_attempts", 0) or 0)
        phase_budget_key = "verify_retry_budget" if result.phase == Phase.VERIFY else "review_retry_budget"
        phase_budget = int(policy.get(phase_budget_key, 0) or 0)
        return completed_attempts < min(auto_fix_attempts, phase_budget)

    def preflight_validate_policy(self, task_id: str) -> dict[str, Any]:
        """Validate the policy-pack before executing lifecycle phases."""
        try:
            from .validate import PolicyValidator, ValidationStatus
        except ImportError:
            from validate import PolicyValidator, ValidationStatus

        validator = PolicyValidator(engine_path="engine", policy_pack_path=self.policy_pack_path)
        results = validator.validate()
        summary = {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == ValidationStatus.PASS),
            "drift": sum(1 for r in results if r.status == ValidationStatus.DRIFT),
            "todo": sum(1 for r in results if r.status == ValidationStatus.TODO),
            "warning_count": 0,
            "blocking": False,
            "results": [
                {
                    "status": r.status.value,
                    "input": r.required_input,
                    "phase": r.phase,
                    "policy_file": r.policy_file,
                    "issue": r.issue,
                }
                for r in results
            ],
        }
        summary["warning_count"] = self.preflight_policy.warning_count(summary["drift"])
        summary["blocking"] = self.preflight_policy.should_block(
            todo_count=summary["todo"],
            drift_count=summary["drift"],
        )
        artifact_ref = self.artifact_store.save_phase_artifacts(
            task_id=task_id,
            phase="Preflight",
            artifacts={"policy_preflight": summary},
            evidence={},
        )
        if artifact_ref is not None:
            summary["artifact_ref"] = artifact_ref
        return summary

    def _next_phase(self, task: TaskContext) -> Phase | None:
        """Determine the next phase based on current state and transitions."""
        if task.current_phase is None:
            return Phase.ROUTE

        # Check if we're done
        if task.current_phase == Phase.LEARN:
            return None

        # Get the transition target
        next_phase = PHASE_TRANSITIONS.get(task.current_phase)

        # Handle complexity-based skipping
        if next_phase and self._should_skip_phase(task, next_phase):
            # Find the next non-skipped phase
            while next_phase and self._should_skip_phase(task, next_phase):
                next_phase = PHASE_TRANSITIONS.get(next_phase)

        return next_phase

    def _should_skip_phase(self, task: TaskContext, phase: Phase) -> bool:
        """Check if a phase should be skipped based on policy-driven rules."""
        # Load complexity policy for skip rules
        complexity_policy = self._load_policy_section('complexity')

        # Check hardcoded rules first (fallback)
        if task.complexity == Complexity.LOW:
            return phase in SKIP_FOR_LOW
        elif task.complexity == Complexity.MEDIUM:
            return phase in SKIP_FOR_MEDIUM

        # Check policy-driven skip rules
        skip_rules = complexity_policy.get('skip_rules', {})
        complexity_key = task.complexity.value

        if complexity_key in skip_rules:
            skip_phases = skip_rules[complexity_key]
            return phase.value in skip_phases

        return False

    def _execute_phase(self, task: TaskContext, phase: Phase) -> PhaseResult:
        """Execute a single phase using the appropriate handler."""
        handler = self.phase_handlers.get(phase)
        if handler is None:
            raise RuntimeError(f"No handler registered for phase {phase!r}")
        try:
            result = handler.execute(task, phase)
            self._attach_agent_role(result)
            self._attach_gate_result(result)
            self._attach_artifact_refs(task, result)
            self._log_phase_cost(result, phase)
            return result
        except Exception as e:
            logger.exception(
                "Phase %s handler raised for task %s", phase.value, task.task_id
            )
            result = PhaseResult(
                phase=phase,
                outcome="fail",
                error=f"Phase execution failed: {type(e).__name__}: {e}",
            )
            self._attach_agent_role(result)
            self._attach_artifact_refs(task, result)
            return result

    def _maybe_gate_retry(self, task: TaskContext, phase: Phase, first: PhaseResult) -> PhaseResult:
        """Attempt exactly one gate retry when the first result fails the gate.

        Returns the result to use (whichever has the higher gate score).
        Gate failures after retry are advisory — the task continues regardless.
        """
        if not self._gate_evidence_policy.is_retry_phase(phase.value):
            return first
        if first.outcome == "fail":
            # Recovery machinery owns hard failures; don't interfere.
            return first
        gate = first.artifacts.get("gate_result")
        if not isinstance(gate, dict) or gate.get("passed", True):
            return first

        first_score = gate.get("score", 0.0)
        missing = gate.get("missing_evidence", [])
        remediation = gate.get("remediation", {})

        task.gate_retry_hint = {
            "phase": phase.value,
            "missing_evidence": missing,
            "remediation": remediation,
        }
        try:
            retry = self._execute_phase(task, phase)
        finally:
            task.gate_retry_hint = None

        retry_gate = retry.artifacts.get("gate_result", {})
        retry_score = retry_gate.get("score", 0.0) if isinstance(retry_gate, dict) else 0.0

        kept = "retry" if retry_score >= first_score else "first"
        chosen = retry if kept == "retry" else first
        chosen.artifacts["gate_retry"] = {
            "attempted": True,
            "first_score": first_score,
            "retry_score": retry_score,
            "kept": kept,
        }

        # If the chosen result still fails the gate, demote to advisory.
        chosen_gate = chosen.artifacts.get("gate_result", {})
        if isinstance(chosen_gate, dict) and not chosen_gate.get("passed", True):
            logger.warning(
                "Gate advisory phase=%s score=%.4f threshold=%.2f — retry did not resolve missing evidence %s; proceeding",
                phase.value,
                chosen_gate.get("score", 0.0),
                chosen_gate.get("threshold", 0.0),
                chosen_gate.get("missing_evidence", []),
            )

        return chosen

    def _log_phase_cost(self, result: PhaseResult, phase: Phase) -> None:
        """Log token usage from a phase result to NCP cost log."""
        usage = result.artifacts.get("dispatch_usage")
        if usage is not None and hasattr(self.persistence, "log_cost"):
            self.persistence.log_cost(usage, pipeline_id=f"sarathi.{phase.value}")

        # Also extract usage from graph executor events (build phase)
        graph_exec = result.artifacts.get("task_graph_execution", {})
        if isinstance(graph_exec, dict):
            for event in graph_exec.get("events", []):
                provider_result = event.get("provider_result", {}) if isinstance(event, dict) else {}
                if isinstance(provider_result, dict):
                    node_usage = provider_result.get("usage")
                    if node_usage is not None and hasattr(self.persistence, "log_cost"):
                        node_label = provider_result.get("title") or provider_result.get("objective", "graph-node")
                        self.persistence.log_cost(
                            node_usage,
                            pipeline_id=f"sarathi.{phase.value}",
                            agent_id=node_usage.get("provider_id", "graph_executor"),
                        )

    def _log_phase(self, task: TaskContext, phase: Phase, status: str) -> None:
        """Log phase transition and persist task state."""
        # Save phase log entry
        self.persistence.save_phase_log(task, phase, status)
        self._notify_phase(task, phase, status)
        if self.run_recorder is not None:
            self.run_recorder.record_phase(task, phase, status)

    def _notify_phase(self, task: TaskContext, phase: Phase, status: str) -> None:
        """Forward attention-worthy phase transitions to the notifier."""
        if self.notifier is None:
            return
        event = phase_event(
            task.task_id,
            task.description,
            phase.value,
            status,
            final_phase=phase is Phase.LEARN,
        )
        if event is not None:
            self.notifier.notify(event)

    def _sync_task_state(self, task: TaskContext, result: PhaseResult) -> None:
        """Promote selected phase artifacts into task-level state."""
        task_graph = result.artifacts.get("task_graph")
        if isinstance(task_graph, dict):
            task.task_graph_state = annotate_graph_for_supervision(task_graph, parent_task_id=task.task_id)
        task_graph_state = result.artifacts.get("task_graph_state")
        if isinstance(task_graph_state, dict) and task_graph_state:
            task.task_graph_state = annotate_graph_for_supervision(task_graph_state, parent_task_id=task.task_id)

        # Promote HarnessConfig from ROUTE phase into task state
        if result.phase == Phase.ROUTE:
            harness_dict = result.artifacts.get("harness_config")
            if isinstance(harness_dict, dict):
                try:
                    task.harness_config = HarnessConfig.from_json(json.dumps(harness_dict))
                    task.task_class = task.harness_config.task_class
                    # Wire the resolved primary_agent into the harness-aware dispatcher.
                    # Only inject when a specific non-local agent was chosen; "local" means
                    # "no strong preference — let provider-config routing decide."
                    if hasattr(self.dispatcher, "preferred_agent"):
                        agent_id = task.harness_config.primary_agent.agent_id
                        self.dispatcher.preferred_agent = agent_id if agent_id != "local" else None
                    if hasattr(self.dispatcher, "preferred_permission_mode"):
                        self.dispatcher.preferred_permission_mode = derive_permission_mode(
                            task.harness_config.permission_scope
                        ).value
                    if hasattr(self.dispatcher, "fallback_agents"):
                        self.dispatcher.fallback_agents = [
                            b.agent_id for b in task.harness_config.fallback_agents
                        ]
                    # Declare-before-dispatch: make this task's harness_id
                    # available for the dispatcher to backfill onto every
                    # dispatch it makes for this task (see
                    # _HarnessAwareDispatcher.dispatch), including graph-node
                    # dispatch during BUILD.
                    if hasattr(self.dispatcher, "harness_id"):
                        self.dispatcher.harness_id = task.harness_config.harness_id
                except Exception:
                    logger.exception(
                        "Failed to restore harness_config for task %s; "
                        "harness routing will fall back to provider-config defaults",
                        task.task_id,
                    )

        # Save updated task state
        self.persistence.save_task(task)

    def _attach_gate_result(self, result: PhaseResult) -> None:
        """Persist gate evaluation details for phases with confidence thresholds."""
        if not self._gate_evidence_policy.is_retry_phase(result.phase.value):
            return

        passed, score = self.check_gate(result.phase, result.evidence)
        default_threshold = 0.80 if result.phase == Phase.BRAINSTORM else 0.90
        threshold = self._gate_evidence_policy.threshold_for(result.phase.value, default_threshold)
        _gate_keys = {
            Phase.BRAINSTORM: {
                "alternative_approaches_considered",
                "risks_identified",
                "success_criteria_defined",
                "reversibility_assessed",
            },
            Phase.PLAN: {"checkpoint_list", "dependency_map", "rollback_plan"},
        }
        expected = _gate_keys.get(result.phase, set())
        missing = [key for key in expected if not result.evidence.get(key)]
        remediation = {
            key: self._gate_evidence_policy.remediation_for(key)
            for key in missing
            if self._gate_evidence_policy.remediation_for(key) is not None
        }
        if not passed:
            remedy_lines = "".join(f"\n  [{key}] {msg}" for key, msg in remediation.items())
            logger.warning(
                "Gate FAILED phase=%s score=%.4f threshold=%.2f missing=%s%s",
                result.phase.value, score, threshold, missing, remedy_lines,
            )
        gate_result = GateResult(
            passed=passed,
            score=score,
            threshold=threshold,
            missing_evidence=missing,
            decision="pass" if passed else "escalate",
        )
        result.artifacts["gate_result"] = {
            "passed": gate_result.passed,
            "score": gate_result.score,
            "threshold": gate_result.threshold,
            "missing_evidence": gate_result.missing_evidence,
            "decision": gate_result.decision,
            "remediation": remediation,
        }

    def _attach_agent_role(self, result: PhaseResult) -> None:
        """Attach the Sanskrit-inspired role identity for this phase."""
        result.artifacts.setdefault("agent_role", phase_agent_role_artifact(result.phase.value))
        result.evidence.setdefault("agent_role_assigned", True)

    def _attach_artifact_refs(self, task: TaskContext, result: PhaseResult) -> None:
        """Persist per-phase artifacts and attach references to the phase result."""
        artifact_ref = self.artifact_store.save_phase_artifacts(
            task_id=task.task_id,
            phase=result.phase.value,
            artifacts=result.artifacts,
            evidence=result.evidence,
        )
        if artifact_ref is not None:
            result.artifact_refs.append(artifact_ref)

    def classify_complexity(
        self,
        description: str,
        file_count: int = 0,
        has_external_deps: bool = False,
        is_cross_cutting: bool = False,
        is_security_sensitive: bool = False,
    ) -> Complexity:
        """
        Classify task complexity based on indicators.

        Override this method to implement policy-driven complexity detection.
        """
        score = 0

        # File-based scoring
        if file_count == 1:
            score += 1
        elif file_count <= 5:
            score += 2
        elif file_count <= 10:
            score += 3
        else:
            score += 4

        # Complexity indicators
        if has_external_deps:
            score += 2
        if is_cross_cutting:
            score += 3
        if is_security_sensitive:
            score += 2

        # Map score to complexity
        if score <= 2:
            return Complexity.LOW
        elif score <= 5:
            return Complexity.MEDIUM
        else:
            return Complexity.HIGH

    def check_gate(
        self,
        phase: Phase,
        evidence: dict[str, Any],
        threshold: float | None = None,
        _epsilon: float = 1e-9,
    ) -> tuple[bool, float]:
        """
        Check if evidence meets the confidence gate for a phase.

        When threshold is None the per-phase default applies (Brainstorm 0.80,
        Plan 0.90), unless overridden by the policy pack's review.gate_thresholds
        block (see GateEvidencePolicy). The epsilon absorbs float accumulation
        error so a score exactly at threshold passes (0.3 + 0.3 + 0.2 < 0.8 in
        float math).

        Returns (passed, actual_confidence).
        """
        if phase == Phase.BRAINSTORM:
            # Evidence-weighted confidence calculation
            weights = {
                "alternative_approaches_considered": 0.3,
                "risks_identified": 0.3,
                "success_criteria_defined": 0.2,
                "reversibility_assessed": 0.2,
            }
            gate_threshold = (
                self._gate_evidence_policy.threshold_for(phase.value, 0.80)
                if threshold is None
                else threshold
            )
            confidence = 0.0
            for key, weight in weights.items():
                if key in evidence and evidence[key]:
                    confidence += weight

            return confidence >= gate_threshold - _epsilon, confidence

        elif phase == Phase.PLAN:
            weights = {
                "checkpoint_list": 0.4,
                "dependency_map": 0.3,
                "rollback_plan": 0.3,
            }
            gate_threshold = (
                self._gate_evidence_policy.threshold_for(phase.value, 0.90)
                if threshold is None
                else threshold
            )
            confidence = 0.0
            for key, weight in weights.items():
                if key in evidence and evidence[key]:
                    confidence += weight

            return confidence >= gate_threshold - _epsilon, confidence

        return True, 1.0

    def _run_trust_gate(self, task: TaskContext) -> str:
        """
        Run NCP trust gate evaluation after ROUTE phase.
        Updates task.harness_config.trust_gate_result and returns the arbitration action.
        Degrades gracefully — never raises.
        """
        try:
            gate = TrustGate(ncp_mcp_url=self.ncp_endpoint)
            response = gate.evaluate(
                task_class_value=task.task_class.value,
                required_context_keys=[],
                pipeline_id=task.task_id,
            )
            action = arbitrate(response.result, task.task_class.value)

            if task.harness_config is not None:
                if action == "ABORT_AND_ESCALATE":
                    task.harness_config.trust_gate_result = "BLOCK"
                    task.harness_config.stale_keys = response.stale_keys
                elif action in ("EXECUTE_FLAGGED", "REFRESH_THEN_EXECUTE",
                                "BLOCK_UNTIL_REFRESH", "PAUSE_AND_NOTIFY"):
                    task.harness_config.trust_gate_result = "WARN"
                    task.harness_config.stale_keys = response.stale_keys
                else:
                    task.harness_config.trust_gate_result = "PASS"

            if action == "BLOCK_UNTIL_REFRESH":
                refreshed = gate.refresh(response.stale_keys, task.task_id)
                if refreshed:
                    response2 = gate.evaluate(task.task_class.value, [], task.task_id)
                    action = arbitrate(response2.result, task.task_class.value)
                    if task.harness_config is not None:
                        if action == "EXECUTE":
                            task.harness_config.trust_gate_result = "PASS"
                            task.harness_config.stale_keys = []
                        else:
                            task.harness_config.trust_gate_result = "WARN"

            return action
        except Exception as exc:
            logger.warning("Trust gate degraded (error): %s", exc, exc_info=True)
            return "EXECUTE"

    @staticmethod
    def _find_ncp_run_path() -> Path | None:
        """Find an executable direct-mode NCP bridge in CWD or nearby parents."""
        cwd = Path.cwd().resolve()
        for i, parent in enumerate([cwd] + list(cwd.parents)):
            if i > 3:
                break
            ncp_dir = parent / ".ncp"
            run_path = ncp_dir / "run.py"
            if (
                ncp_dir.is_dir()
                and (ncp_dir / "config.toml").exists()
                and run_path.exists()
                and os.access(run_path, os.X_OK)
            ):
                return run_path
        return None

    @staticmethod
    def _probe_ncp() -> bool:
        """Probe whether direct-mode NCP is available for the local project."""
        import subprocess

        run_path = Engine._find_ncp_run_path()
        if run_path is None:
            return False

        try:
            result = subprocess.run(
                [str(run_path), "status"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _validate_ncp_available(self) -> None:
        """Check NCP is reachable. Raises NCPNotAvailableError if not."""
        from .ncp_adapter import NCPContextAdapter
        adapter = NCPContextAdapter(
            mode=self.ncp_mode,
            endpoint=getattr(self, 'ncp_endpoint', 'http://127.0.0.1:4242/mcp'),
            run_path=self.ncp_run_path or ".ncp/run.py",
        )
        if not adapter.check_available():
            mode_hint = "Run 'sarathi init --ncp' first." if self.ncp_mode == "direct" else "Start 'ncp serve' first."
            raise NCPNotAvailableError(
                f"NCP not reachable in {self.ncp_mode} mode. {mode_hint}"
            )
