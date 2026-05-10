"""Core engine logic for Sarathi - Workflow orchestration framework."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

try:
    from .dispatch import Dispatcher, LocalDispatcher
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
        ArtifactStore,
        apply_learning_feedback_to_provider_routing,
        DispatchRequest,
        GateResult,
        PreflightPolicy,
        RecoveryRunner,
        phase_agent_role_artifact,
    )
    from .task_graph import annotate_graph_for_supervision
except ImportError:
    from dispatch import Dispatcher, LocalDispatcher
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
        ArtifactStore,
        apply_learning_feedback_to_provider_routing,
        DispatchRequest,
        GateResult,
        PreflightPolicy,
        RecoveryRunner,
        phase_agent_role_artifact,
    )
    from task_graph import annotate_graph_for_supervision


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

    def execute(self, task: TaskContext, phase: Phase) -> PhaseResult:
        """Route the task based on description and complexity."""
        # Load complexity policy
        complexity_policy = self._load_policy_section('complexity')

        # Classify task type from description
        task_type = self._classify_task_type(task.description)

        # Determine workflow path
        workflow_path = self._select_workflow_path(task, task_type)

        evidence = {
            "task_type": task_type,
            "workflow_path": workflow_path,
            "complexity_assessed": True,
        }

        return PhaseResult(
            phase=phase,
            outcome="pass",
            evidence=evidence,
            artifacts={"routing_decision": workflow_path}
        )

    def _classify_task_type(self, description: str) -> str:
        """Classify task type from description."""
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
        task_data = {
            "task_id": task.task_id,
            "description": task.description,
            "complexity": task.complexity.value,
            "complexity_evidence": task.complexity_evidence,
            "preflight_validation": task.preflight_validation,
            "task_graph_state": task.task_graph_state,
            "current_phase": task.current_phase.value if task.current_phase else None,
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
            task = TaskContext(
                task_id=task_data["task_id"],
                description=task_data["description"],
                complexity=Complexity(task_data["complexity"]),
                complexity_evidence=task_data.get("complexity_evidence", {}),
                preflight_validation=task_data.get("preflight_validation", {}),
                task_graph_state=task_data.get("task_graph_state", {}),
            )

            task.current_phase = Phase(task_data["current_phase"]) if task_data.get("current_phase") else None

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
    ):
        self.policy_pack_path = policy_pack_path or "policy-pack"
        self.compiled_policy = compile_policy_pack(self.policy_pack_path)
        self.policy_pack = self._load_policy_pack()
        provider_config = apply_learning_feedback_to_provider_routing(
            self.compiled_policy.get("model_routing"),
            self.compiled_policy.get("learning_feedback"),
        )
        self.dispatcher = dispatcher or LocalDispatcher(provider_config=provider_config)
        self.enforce_preflight = enforce_preflight
        self.preflight_policy = PreflightPolicy()
        self.phase_handlers = self._create_phase_handlers()
        self.persistence = PersistenceManager()
        self.artifact_store = ArtifactStore()
        self.recovery_runner = RecoveryRunner(dispatcher=self.dispatcher)
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
        return {
            Phase.ROUTE: RouteHandler(self.policy_pack, self.dispatcher),
            Phase.BRAINSTORM: BrainstormHandler(self.policy_pack, self.dispatcher),
            Phase.PLANNING_ADVISOR: PlanningAdvisorHandler(self.policy_pack, self.dispatcher),
            Phase.PLAN: PlanHandler(self.policy_pack, self.dispatcher),
            Phase.BUILD: BuildHandler(self.policy_pack, self.dispatcher),
            Phase.VERIFY: VerifyHandler(self.policy_pack, self.dispatcher),
            Phase.REVIEW: ReviewHandler(self.policy_pack, self.dispatcher),
            Phase.TASK_TRACKING: TaskTrackingHandler(self.policy_pack, self.dispatcher),
            Phase.RISK_CHECK: RiskCheckHandler(self.policy_pack, self.dispatcher),
            Phase.ELEGANCE: EleganceHandler(self.policy_pack, self.dispatcher),
            Phase.PHASE_LOG: PhaseLogHandler(self.policy_pack, self.dispatcher),
            Phase.LEARN: LearnHandler(self.policy_pack, self.dispatcher),
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

    def run_task(self, task: TaskContext) -> TaskContext:
        """Run a task through the full lifecycle."""
        if not task.preflight_validation:
            task.preflight_validation = self.preflight_validate_policy(task.task_id)
        self.persistence.save_task(task)
        if self.enforce_preflight and task.preflight_validation.get("blocking", False):
            task.current_phase = None
            self.persistence.save_task(task)
            return task

        task.current_phase = Phase.ROUTE

        while task.current_phase is not None and task.current_phase != Phase.LEARN:
            phase = task.current_phase

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
            for phase_result in phase_results:
                task.phase_results.append(phase_result)
                self._sync_task_state(task, phase_result)
            result = phase_results[-1]

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
            self.persistence.save_task(task)

        # Execute final Learn phase
        learn_result = self._execute_phase(task, Phase.LEARN)
        task.phase_results.append(learn_result)
        self._sync_task_state(task, learn_result)
        task.current_phase = None
        self._log_phase(task, Phase.LEARN, "completed")
        self.persistence.save_task(task)

        return task

    def resume_task(self, task: TaskContext) -> TaskContext:
        """Resume a previously saved task from the next unresolved phase."""
        if not task.phase_results:
            return self.run_task(task)

        if Phase.LEARN in task.get_completed_phases():
            task.current_phase = None
            return task

        last_result = task.phase_results[-1]
        last_phase = last_result.phase
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

        while task.current_phase is not None and task.current_phase != Phase.LEARN:
            phase = task.current_phase
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
            return result
        except Exception as e:
            result = PhaseResult(
                phase=phase,
                outcome="fail",
                error=f"Phase execution failed: {str(e)}",
            )
            self._attach_agent_role(result)
            self._attach_artifact_refs(task, result)
            return result

    def _log_phase(self, task: TaskContext, phase: Phase, status: str) -> None:
        """Log phase transition and persist task state."""
        # Save phase log entry
        self.persistence.save_phase_log(task, phase, status)

    def _sync_task_state(self, task: TaskContext, result: PhaseResult) -> None:
        """Promote selected phase artifacts into task-level state."""
        task_graph = result.artifacts.get("task_graph")
        if isinstance(task_graph, dict):
            task.task_graph_state = annotate_graph_for_supervision(task_graph, parent_task_id=task.task_id)
        task_graph_state = result.artifacts.get("task_graph_state")
        if isinstance(task_graph_state, dict) and task_graph_state:
            task.task_graph_state = annotate_graph_for_supervision(task_graph_state, parent_task_id=task.task_id)

        # Save updated task state
        self.persistence.save_task(task)

    def _attach_gate_result(self, result: PhaseResult) -> None:
        """Persist gate evaluation details for phases with confidence thresholds."""
        passed, score = self.check_gate(result.phase, result.evidence)
        if result.phase not in {Phase.BRAINSTORM, Phase.PLAN}:
            return

        threshold = 0.90
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
        missing = [
            key for key in expected
            if not result.evidence.get(key)
        ]
        if not passed:
            import logging
            logging.getLogger(__name__).warning(
                "Gate FAILED phase=%s score=%.2f threshold=%.2f missing=%s",
                result.phase.value, score, threshold, missing,
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
        threshold: float = 0.90,
    ) -> tuple[bool, float]:
        """
        Check if evidence meets the confidence gate for a phase.

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
            confidence = 0.0
            for key, weight in weights.items():
                if key in evidence and evidence[key]:
                    confidence += weight

            return confidence >= threshold, confidence

        elif phase == Phase.PLAN:
            weights = {
                "checkpoint_list": 0.4,
                "dependency_map": 0.3,
                "rollback_plan": 0.3,
            }
            confidence = 0.0
            for key, weight in weights.items():
                if key in evidence and evidence[key]:
                    confidence += weight

            return confidence >= threshold, confidence

        return True, 1.0
