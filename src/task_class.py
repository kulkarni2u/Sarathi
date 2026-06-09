"""TaskClass taxonomy and assembly defaults for the Sarathi Harness Engine."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskClass(Enum):
    QUERY                    = "query"
    ANALYSIS                 = "analysis"
    CODEGEN_GREENFIELD       = "codegen/greenfield"
    CODEGEN_REFACTOR         = "codegen/refactor"
    CODEGEN_PATCH            = "codegen/patch"
    MUTATION_CONFIG          = "mutation/config"
    MUTATION_INFRA           = "mutation/infra"
    MUTATION_DATA            = "mutation/data"
    ORCHESTRATION_PIPELINE   = "orchestration/pipeline"
    ORCHESTRATION_DELEGATION = "orchestration/delegation"
    EVOLUTION_HARNESS        = "evolution/harness"
    EVOLUTION_CONTEXT        = "evolution/context"


@dataclass
class AssemblyDefaults:
    context_scope: str     # minimal | domain_relevant | full_domain | targeted | cross_domain | full_history
    permission_scope: str  # read_only | read_plus_idempotent | repo_write | infra_write_declared | ...
    agent_preference: str  # fastest | balanced | highest_capability | sarathi_native
    lazy_loading: bool
    human_in_loop: bool
    quality_signals: list[str]


TASK_CLASS_DEFAULTS: dict[TaskClass, AssemblyDefaults] = {
    TaskClass.QUERY: AssemblyDefaults(
        context_scope    = "minimal",
        permission_scope = "read_only",
        agent_preference = "fastest",
        lazy_loading     = True,
        human_in_loop    = False,
        quality_signals  = ["relevance", "latency"],
    ),
    TaskClass.ANALYSIS: AssemblyDefaults(
        context_scope    = "domain_relevant",
        permission_scope = "read_plus_idempotent",
        agent_preference = "balanced",
        lazy_loading     = True,
        human_in_loop    = False,
        quality_signals  = ["accuracy", "trust_utilization", "token_efficiency"],
    ),
    TaskClass.CODEGEN_GREENFIELD: AssemblyDefaults(
        context_scope    = "full_domain",
        permission_scope = "repo_write",
        agent_preference = "highest_capability",
        lazy_loading     = False,
        human_in_loop    = False,
        quality_signals  = ["test_pass_rate", "drift_introduced", "token_cost"],
    ),
    TaskClass.CODEGEN_REFACTOR: AssemblyDefaults(
        context_scope    = "full_domain",
        permission_scope = "repo_write",
        agent_preference = "balanced",
        lazy_loading     = False,
        human_in_loop    = False,
        quality_signals  = ["test_pass_rate", "blast_radius", "token_cost"],
    ),
    TaskClass.CODEGEN_PATCH: AssemblyDefaults(
        context_scope    = "targeted",
        permission_scope = "repo_write_scoped",
        agent_preference = "balanced",
        lazy_loading     = True,
        human_in_loop    = False,
        quality_signals  = ["test_pass_rate", "blast_radius"],
    ),
    TaskClass.MUTATION_CONFIG: AssemblyDefaults(
        context_scope    = "targeted",
        permission_scope = "config_write_declared",
        agent_preference = "balanced",
        lazy_loading     = True,
        human_in_loop    = False,
        quality_signals  = ["success_rate", "rollback_triggered"],
    ),
    TaskClass.MUTATION_INFRA: AssemblyDefaults(
        context_scope    = "full_domain",
        permission_scope = "infra_write_declared",
        agent_preference = "highest_capability",
        lazy_loading     = False,
        human_in_loop    = True,
        quality_signals  = ["success_rate", "rollback_triggered", "latency"],
    ),
    TaskClass.MUTATION_DATA: AssemblyDefaults(
        context_scope    = "full_domain",
        permission_scope = "data_write_declared",
        agent_preference = "highest_capability",
        lazy_loading     = False,
        human_in_loop    = True,
        quality_signals  = ["success_rate", "records_affected", "rollback_triggered"],
    ),
    TaskClass.ORCHESTRATION_PIPELINE: AssemblyDefaults(
        context_scope    = "cross_domain",
        permission_scope = "child_scope_union",
        agent_preference = "sarathi_native",
        lazy_loading     = True,
        human_in_loop    = False,
        quality_signals  = ["pipeline_success", "child_harness_efficiency", "e2e_latency"],
    ),
    TaskClass.ORCHESTRATION_DELEGATION: AssemblyDefaults(
        context_scope    = "domain_relevant",
        permission_scope = "child_scope_union",
        agent_preference = "sarathi_native",
        lazy_loading     = True,
        human_in_loop    = False,
        quality_signals  = ["delegation_success", "e2e_latency"],
    ),
    TaskClass.EVOLUTION_HARNESS: AssemblyDefaults(
        context_scope    = "full_history",
        permission_scope = "harness_engine_write",
        agent_preference = "highest_capability",
        lazy_loading     = False,
        human_in_loop    = True,
        quality_signals  = ["improvement_delta", "regression_rate"],
    ),
    TaskClass.EVOLUTION_CONTEXT: AssemblyDefaults(
        context_scope    = "full_history",
        permission_scope = "ncp_store_write",
        agent_preference = "highest_capability",
        lazy_loading     = False,
        human_in_loop    = True,
        quality_signals  = ["trust_improvement", "eviction_reduction"],
    ),
}

# Legacy ad-hoc type strings → TaskClass
_LEGACY_MAP: dict[str, TaskClass] = {
    "bug":      TaskClass.CODEGEN_PATCH,
    "fix":      TaskClass.CODEGEN_PATCH,
    "feature":  TaskClass.CODEGEN_GREENFIELD,
    "refactor": TaskClass.CODEGEN_REFACTOR,
    "docs":     TaskClass.QUERY,
    "deploy":   TaskClass.MUTATION_INFRA,
}


def from_legacy_type(task_type: str) -> TaskClass:
    """Map a legacy ad-hoc task type string to TaskClass."""
    return _LEGACY_MAP.get(task_type.lower(), TaskClass.ANALYSIS)


def classify_task_class(description: str) -> TaskClass:
    """Infer TaskClass from task description using keyword heuristics."""
    desc = description.lower()

    # Mutations first — strongest signal (irreversible side effects)
    if any(w in desc for w in ["deploy", "terraform", "provision", "infra"]):
        return TaskClass.MUTATION_INFRA
    if any(w in desc for w in ["migrate data", "alter table", "delete records", "backfill"]):
        return TaskClass.MUTATION_DATA
    if any(w in desc for w in ["config", "env var", "environment variable", "setting"]):
        if any(w in desc for w in ["update", "change", "set", "modify"]):
            return TaskClass.MUTATION_CONFIG

    # Code changes
    if any(w in desc for w in ["greenfield", "new project", "scaffold", "bootstrap from scratch"]):
        return TaskClass.CODEGEN_GREENFIELD
    if any(w in desc for w in ["refactor", "clean up", "restructure", "reorganize"]):
        return TaskClass.CODEGEN_REFACTOR
    if any(w in desc for w in ["bug", "fix", "patch", "hotfix", "null pointer", "error"]):
        return TaskClass.CODEGEN_PATCH
    if any(w in desc for w in ["implement", "add feature", "create", "build", "write"]):
        return TaskClass.CODEGEN_PATCH  # conservative default for write tasks

    # Analysis and query — checked before orchestration to avoid "pipeline" false positives
    if any(w in desc for w in ["analyze", "analysis", "report", "evaluate", "assess", "compare"]):
        return TaskClass.ANALYSIS
    if any(w in desc for w in ["what", "how", "why", "explain", "describe", "list", "show", "find"]):
        return TaskClass.QUERY

    # Orchestration — requires explicit orchestration verb, not just the word "pipeline"
    if any(w in desc for w in ["orchestrate", "coordinate", "run pipeline", "build pipeline"]):
        return TaskClass.ORCHESTRATION_PIPELINE
    if any(w in desc for w in ["delegate", "hand off", "assign to"]):
        return TaskClass.ORCHESTRATION_DELEGATION

    return TaskClass.ANALYSIS
