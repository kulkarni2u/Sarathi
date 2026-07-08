"""CLI implementation for Sarathi."""
import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .evolve import Evolver, ProposalReviewStore
    from .init import InitWorkflow, bootstrap_workspace, import_policy_pack_from_source
    from .policy import compile_policy_pack
    from .policy.layering import extract_server_caps
    from .runtime import AutoresearchStore, UsageRecord, list_agent_roles, list_phase_agent_roles, register_agent_role
    from .runtime import TaskGraphExecutor, load_recipe, load_recipes
    from .runtime.agent_spec import load_agent_specs
    from .task_graph import (
        graph_summary,
        latest_completed_node,
        latest_failed_node,
        next_ready_node,
        next_retryable_failed_node,
        supervision_summary,
        task_manifest_from_graph,
    )
    from .validate import PolicyValidator
    from .engine import Engine, TaskContext, Phase, Complexity, PHASE_TRANSITIONS, PhaseResult
except ImportError:
    # Support direct execution via sarathi.py, which prepends src/ to sys.path.
    from evolve import Evolver, ProposalReviewStore
    from init import InitWorkflow, bootstrap_workspace, import_policy_pack_from_source
    from policy import compile_policy_pack
    from policy.layering import extract_server_caps
    from runtime import AutoresearchStore, UsageRecord, list_agent_roles, list_phase_agent_roles, register_agent_role
    from runtime import TaskGraphExecutor, load_recipe, load_recipes
    from runtime.agent_spec import load_agent_specs
    from task_graph import (
        graph_summary,
        latest_completed_node,
        latest_failed_node,
        next_ready_node,
        next_retryable_failed_node,
        supervision_summary,
        task_manifest_from_graph,
    )
    from validate import PolicyValidator
    from engine import Engine, TaskContext, Phase, Complexity, PHASE_TRANSITIONS, PhaseResult
import time


def _find_ncp_template(filename: str) -> Path | None:
    """Return the source or installed NCP template path."""
    candidates = [
        Path(__file__).resolve().parents[1] / "docs" / "ncp" / filename,
        Path(sys.prefix) / "share" / "sarathi" / "ncp" / filename,
        Path(sys.base_prefix) / "share" / "sarathi" / "ncp" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ensure_ncp_sidecar(init_target: Path) -> dict[str, bool]:
    """Ensure Sarathi's direct-mode NCP files exist under ``init_target/.ncp``."""
    import shutil

    ncp_dir = init_target / ".ncp"
    ncp_dir.mkdir(parents=True, exist_ok=True)

    created = {"config": False, "run_py": False}
    config_path = ncp_dir / "config.toml"
    if not config_path.exists():
        config_template = _find_ncp_template("config.toml.example")
        if config_template is not None:
            shutil.copyfile(config_template, config_path)
            created["config"] = True

    run_path = ncp_dir / "run.py"
    if not run_path.exists():
        run_template = _find_ncp_template("run.py.example")
        if run_template is not None:
            shutil.copyfile(run_template, run_path)
            created["run_py"] = True

    if run_path.exists():
        run_path.chmod(run_path.stat().st_mode | 0o111)

    return created


def _prompt_yes_no(label: str, default: bool) -> bool:
    """Prompt for a yes/no setup choice."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{label} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def _setup_choice(args: argparse.Namespace, attr: str, label: str, default: bool) -> bool:
    """Resolve a setup component from explicit flags, --yes, or prompt."""
    explicit = getattr(args, attr)
    if explicit is not None:
        return bool(explicit)
    if getattr(args, "yes", False):
        return default
    return _prompt_yes_no(label, default)


def _setup_extras_install_plan(extras: list[str], repo_root: Path) -> tuple[str, list[str], str | None]:
    """Return display text, command, and cwd for installing selected extras."""
    extras_spec = ",".join(extras)
    source_checkout = (repo_root / "pyproject.toml").exists()
    if source_checkout:
        return (
            f'python3 -m pip install -e ".[{extras_spec}]"',
            [sys.executable, "-m", "pip", "install", "-e", f".[{extras_spec}]"],
            str(repo_root),
        )
    return (
        f'python3 -m pip install "sarathi-ai[{extras_spec}]"',
        [sys.executable, "-m", "pip", "install", f"sarathi-ai[{extras_spec}]"],
        None,
    )


def _resolve_workspace_ncp(args, cwd: str) -> bool | None:
    """Resolve ncp_enabled from CLI flags and workspace metadata.
    
    Returns:
        True  → force NCP (--ncp flag or workspace metadata)
        False → force native (--no-ncp flag)
        None  → auto-detect (no explicit preference)
    """
    if getattr(args, 'no_ncp', False):
        return False
    if getattr(args, 'ncp', False):
        return True
    
    # Check workspace metadata
    from pathlib import Path
    try:
        from src.storage import Storage, connect

        # Walk up from cwd looking for .sarathi/sarathi.db
        search = Path(cwd).resolve()
        for parent in [search] + list(search.parents):
            db = parent / ".sarathi" / "sarathi.db"
            if db.exists():
                conn = connect(db)
                try:
                    storage = Storage(conn)
                    for ws in storage.list_workspaces():
                        ws_path = ws.get("root_path", "")
                        if ws_path and cwd.startswith(ws_path):
                            meta = ws.get("metadata") or {}
                            if "ncp_enabled" in meta:
                                return bool(meta["ncp_enabled"])
                            return None  # absent → auto-detect
                finally:
                    conn.close()
                break
    except Exception:
        pass
    return None  # no workspace found → auto-detect


# ============================================================================
# Auto-discovery functions
# ============================================================================

def discover_policy_pack(start_path: str = ".") -> str | None:
    """
    Auto-discover policy-pack directory.
    
    Searches in order:
    1. start_path/policy-pack
    2. start_path/policy_pack
    3. Parent directories (up to workspace root)
    4. Common locations: ./policy-pack, ../policy-pack, etc.
    """
    search_paths = [
        Path(start_path) / "policy-pack",
        Path(start_path) / "policy_pack",
        Path(start_path) / ".sarathi",
        Path.cwd() / "policy-pack",
        Path.cwd() / "policy_pack",
        Path.cwd() / ".sarathi",
    ]
    
    # Also check parent directories
    cwd = Path.cwd()
    for parent in [cwd.parent, cwd.parent.parent, cwd.parent.parent.parent]:
        if parent != cwd:
            search_paths.extend([
                parent / "policy-pack",
                parent / "policy_pack",
            ])
    
    for path in search_paths:
        if path.exists() and path.is_dir():
            # Verify it looks like a policy pack
            files = list(path.glob("*.md"))
            if len(files) >= 3:  # At least 3 markdown files
                return str(path)
    
    return None


def calculate_complexity(task_description: str) -> Complexity:
    """
    Auto-calculate complexity from task description.
    
    Uses keyword analysis to determine complexity level:
    - HIGH: architectural, refactor, migrate, multi-service, new feature with scope
    - LOW: fix, bug, typo, update docs, simple change
    - MEDIUM: everything else
    """
    text = task_description.lower()
    
    # High complexity indicators
    high_patterns = [
        r'\b(architect|architecture|refactor|migrate|redesign)\b',
        r'\b(multi-?service|distributed|microservice)\b',
        r'\b(new\s+(feature|service|module|system))\b',
        r'\b(cross-?cutting|global|shared)\b',
        r'\b(security|performance|critical|urgent)\b',
        r'\b(prototype|spike|experimental)\b',
        r'\b(database\s*schema|api\s*v[23]|breaking)\b',
        r'\b(oauth|jwt|authentication|authorization)\b',
        r'\b(ci/cd|pipeline|deployment)\b',
        r'\b(technical\s*debt|cleanup|large\s*refactor)\b',
    ]
    
    # Low complexity indicators
    low_patterns = [
        r'\b(fix|bug|typo|error)\b',
        r'\b(update|add)\s+(docs?|comments?|readme)\b',
        r'\b(docs?|documentation)\b',
        r'\b(rename|rename)\b',
        r'\b(simple|trivial|easy)\b',
        r'\b(single\s+file|one\s+file)\b',
        r'\b(cleanup|format)\b',
        r'\b(lint|style)\b',
        r'\b(test|tests)\s+only\b',
        r'\b(bump\s+version|version\s+update)\b',
        r'\b(dependency|dependency\s+update)\b',
        r'\bconfig(uration)?\b',
    ]
    
    # Count matches
    high_score = sum(1 for p in high_patterns if re.search(p, text))
    low_score = sum(1 for p in low_patterns if re.search(p, text))
    
    # Check for explicit complexity mentions
    if re.search(r'\bhigh\s*(complexity|effort)?\b', text):
        return Complexity.HIGH
    if re.search(r'\blow\s*(complexity|effort)?\b', text):
        return Complexity.LOW
    if re.search(r'\bmedium\s*(complexity|effort)?\b', text):
        return Complexity.MEDIUM
    
    # Score-based classification
    if high_score >= 2 or (high_score >= 1 and low_score == 0):
        return Complexity.HIGH
    elif low_score >= 2 and high_score == 0:
        return Complexity.LOW
    
    return Complexity.MEDIUM


def format_preflight_summary(preflight: dict) -> list[str]:
    """Render a concise preflight summary for CLI output."""
    lines = [
        "Preflight:"
        f" {preflight.get('passed', 0)} PASS,"
        f" {preflight.get('warning_count', 0)} WARN,"
        f" {preflight.get('todo', 0)} TODO"
    ]
    artifact_ref = preflight.get("artifact_ref")
    if artifact_ref:
        lines.append(f"  Artifact: {artifact_ref}")
    if preflight.get("blocking", False):
        lines.append("  Blocking issues detected. Fix policy-pack gaps before execution.")
    return lines


def latest_escalation_bundle(task: TaskContext) -> dict | None:
    """Return the newest escalation bundle recorded on a task."""
    for result in reversed(task.phase_results):
        bundle = result.artifacts.get("escalation_bundle")
        if isinstance(bundle, dict):
            return bundle
    return None


def print_escalation_summary(bundle: dict, prefix: str = "") -> None:
    """Print a compact escalation summary for CLI views."""
    print(f"{prefix}Escalation: {bundle.get('reason', 'attention required')}")
    graph_node = bundle.get("graph_node")
    if isinstance(graph_node, dict):
        print(
            f"{prefix}Escalation Node:"
            f" {graph_node.get('id')} - {graph_node.get('title')}"
            f" ({graph_node.get('status')})"
        )
    artifact_refs = bundle.get("artifact_refs")
    if isinstance(artifact_refs, list) and artifact_refs:
        print(f"{prefix}Evidence Ref: {artifact_refs[-1]}")
    print(f"{prefix}Recommended Action: {bundle.get('recommended_action', 'Inspect evidence and resume.')}")


def phase_agent_name(result: PhaseResult) -> str:
    """Return the display name of the agent role attached to a phase result."""
    agent_role = result.artifacts.get("agent_role")
    if isinstance(agent_role, dict):
        name = agent_role.get("name")
        if isinstance(name, str) and name:
            return name
    return "-"


def _gate_status_label(result: PhaseResult) -> str:
    """Return a Gate column label for a phase result.

    ok       — gate present and passed on first attempt
    retry    — gate passed after one retry
    advisory — gate failed on both attempts, task continued
    -        — no gate for this phase
    """
    gate = result.artifacts.get("gate_result")
    if not isinstance(gate, dict):
        return "-"
    retry = result.artifacts.get("gate_retry")
    if isinstance(retry, dict):
        chosen_passed = gate.get("passed", False)
        if chosen_passed:
            return "retry"
        return "advisory"
    return "ok" if gate.get("passed", False) else "advisory"


def _task_usage_records(task: TaskContext) -> list[UsageRecord]:
    records: list[UsageRecord] = []
    for phase_result in task.phase_results:
        records.extend(_usage_records_from_value(phase_result.artifacts))
        records.extend(_usage_records_from_value(phase_result.evidence))
    return records


def _usage_records_from_value(value: Any) -> list[UsageRecord]:
    record = UsageRecord.from_mapping(value if isinstance(value, dict) else None)
    if record is not None:
        return [record]
    if isinstance(value, dict):
        records: list[UsageRecord] = []
        usage_value = value.get("usage")
        if isinstance(usage_value, dict):
            usage_record = UsageRecord.from_mapping(usage_value)
            if usage_record is not None:
                records.append(usage_record)
        for key, nested in value.items():
            if key == "usage":
                continue
            records.extend(_usage_records_from_value(nested))
        return records
    if isinstance(value, list):
        records: list[UsageRecord] = []
        for item in value:
            records.extend(_usage_records_from_value(item))
        return records
    return []


def _usage_summary_line(task: TaskContext) -> str | None:
    records = _task_usage_records(task)
    if not records:
        return None

    total_tokens = sum(record.total_tokens for record in records)
    budget_limit = next((record.budget_limit for record in records if record.budget_limit is not None), None)
    budget_remaining = None
    budget_state = "unknown"
    if budget_limit is not None:
        budget_remaining = max(budget_limit - total_tokens, 0)
        ratio = total_tokens / budget_limit if budget_limit > 0 else 1.0
        if ratio >= 1.0:
            budget_state = "exhausted"
        elif ratio >= 0.9:
            budget_state = "near_limit"
        elif ratio >= 0.75:
            budget_state = "warning"
        else:
            budget_state = "ok"
    else:
        severity = {"unknown": 0, "ok": 1, "warning": 2, "near_limit": 3, "exhausted": 4}
        budget_state = max((record.budget_state for record in records), key=lambda state: severity.get(state, 0))

    usage_source = _usage_source_summary(records)
    tokens_text = _format_token_count(total_tokens)
    if budget_limit is not None:
        return (
            "Token Budget:"
            f" {tokens_text} / {_format_token_count(budget_limit)}"
            f" | remaining: {_format_token_count(budget_remaining or 0)}"
            f" | budget: {budget_state}"
            f" | usage source: {usage_source}"
        )
    return (
        "Token Budget:"
        f" {tokens_text}"
        f" | budget: {budget_state}"
        f" | usage source: {usage_source}"
    )


def _usage_source_summary(records: list[UsageRecord]) -> str:
    sources = {record.usage_source for record in records}
    if sources == {"reported"}:
        return "reported"
    if sources == {"estimated"}:
        return "estimated"
    return "mixed"


def _format_token_count(value: int) -> str:
    if value >= 1_000_000:
        scaled = value / 1_000_000
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + "m"
    if value >= 1000:
        scaled = value / 1000
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + "k"
    return str(value)


def _budget_summary_line(task: TaskContext) -> str | None:
    """Render the policy-enforced per-task budget snapshot, if any."""
    snapshot = getattr(task, "budget_snapshot", None)
    if not isinstance(snapshot, dict):
        for pr in reversed(task.phase_results):
            exhausted = pr.artifacts.get("budget_exhausted")
            if isinstance(exhausted, dict):
                snapshot = exhausted
                break
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("enforcement") != "enabled":
        return None

    consumed = _format_token_count(snapshot.get("consumed_tokens", 0) or 0)
    max_tokens = snapshot.get("max_total_tokens")
    max_text = _format_token_count(max_tokens) if max_tokens is not None else "unbounded"
    return (
        "Budget:"
        f" {consumed} / {max_text}"
        f" | state: {snapshot.get('state', 'unknown')}"
    )


def _crash_recovery_summary_line(task: TaskContext) -> str | None:
    """Render a summary of any in-flight dispatches reconciled on resume."""
    reconciliations = getattr(task, "crash_reconciliation", None)
    if not reconciliations:
        return None

    count = len(reconciliations)
    changed = any(not r.get("safe_to_rerun") for r in reconciliations)
    status = "workspace changes detected" if changed else "no workspace changes detected"
    return (
        "Crash recovery:"
        f" {count} interrupted dispatch{'es' if count != 1 else ''}"
        f" | {status}"
    )


# ============================================================================
# CLI handlers
# ============================================================================

def handle_home() -> None:
    """Render the default calm home for bare CLI launch."""
    print("Sarathi")
    print("Workspace: no workspace selected")
    print("Actions:")
    print("  chat         start brainstorming or create a task")
    print("  desktop      launch the local desktop stack")
    print("  reuse        inspect workflow templates and learned playbooks")
    print("  run          execute a task through Sarathi")
    print("  status       inspect task progress")
    print("  resume       continue a saved task")
    print("  new workspace create or select a workspace")


def _show_home() -> None:
    banner = r"""
  ███████  █████  ██████   █████  ████████ ██   ██ ██
  ██      ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
  ███████ ███████ ██████  ███████    ██    ███████ ██
       ██ ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
  ███████ ██   ██ ██   ██ ██   ██    ██    ██   ██ ██
    """
    print(banner)
    print("  Your AI Charioteer  ·  Workflow Orchestration Framework")
    print()

    service_url = None
    workspace_count = None
    info = _read_service_discovery()
    if info is not None:
        service_url = info.get("url")
    service_token = _service_auth_token(info)
    if service_url:
        try:
            data = _service_get_json(service_url, "/api/workspaces", token=service_token)
            workspace_count = len(data.get("workspaces", []))
        except Exception:
            pass

    if service_url and workspace_count is not None:
        print(f"  Service   {service_url}  ({workspace_count} workspace{'s' if workspace_count != 1 else ''})")
    elif service_url:
        print(f"  Service   {service_url}  (connecting…)")
    else:
        print("  Service   not running  →  python3 -m src.service --db ~/.sarathi/sarathi.db --port 8765")

    print()
    print("  Commands")
    print("    sarathi tui                                      open the terminal dashboard")
    print("    sarathi desktop                                  launch the desktop stack")
    print("    sarathi reuse                                    inspect workflow templates and playbooks")
    print("    sarathi run \"<task>\" --policy-pack ./policy-pack   orchestrate a task")
    print("    sarathi init .                                     initialize a project")
    print("    sarathi validate ./policy-pack                     check policy pack")
    print("    sarathi list                                       list tasks")
    print("    sarathi log <task_id>                              show task log")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sarathi",
        description="Sarathi - Workflow orchestration framework"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Setup command
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactively configure Sarathi components for this machine/workspace",
    )
    setup_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace to initialize when NCP is enabled (default: .)",
    )
    setup_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Accept recommended defaults without prompting",
    )
    setup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the setup plan without changing files or installing dependencies",
    )
    setup_parser.add_argument(
        "--install-extras",
        action="store_true",
        help="Install selected optional Python extras with pip",
    )
    for flag, help_text in [
        ("tui", "Terminal UI support"),
        ("mcp", "MCP server support"),
        ("webui", "Web cockpit assets/build guidance"),
        ("ncp", "NCP workspace bootstrap"),
        ("desktop", "Desktop launcher guidance"),
    ]:
        group = setup_parser.add_mutually_exclusive_group()
        group.add_argument(
            f"--{flag}",
            dest=f"setup_{flag}",
            action="store_true",
            default=None,
            help=f"Enable {help_text}",
        )
        group.add_argument(
            f"--no-{flag}",
            dest=f"setup_{flag}",
            action="store_false",
            help=f"Skip {help_text}",
        )

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new Sarathi policy pack")
    init_parser.add_argument(
        "target_path",
        nargs="?",
        default=".",
        help="Target path for initialization (default: .)",
    )
    init_parser.add_argument(
        "--engine",
        default="markdown",
        help="Engine to use (default: markdown)",
    )
    init_parser.add_argument(
        "--ncp",
        action="store_true",
        help="Initialize with NCP context protocol (bootstraps .ncp/ directory required for auto-detect)",
    )
    init_parser.add_argument(
        "--no-wiki",
        action="store_true",
        help="Skip generated .sarathi/wiki creation.",
    )
    init_parser.add_argument(
        "--from",
        dest="from_source",
        default=None,
        help="Import policy pack from: local directory, recipe name (e.g. bakeoff), "
             "git URL, or registry entry (registry:<name> or <name>@<version>)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing non-empty policy-pack directory when using --from",
    )

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a policy pack")
    validate_parser.add_argument(
        "policy_pack",
        nargs="?",
        help="Path to the policy pack to validate (auto-discovered if not provided)",
    )
    validate_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed validation results",
    )

    # Dashboard command (terminal UI)
    tui_parser = subparsers.add_parser(
        "tui",
        aliases=["dashboard"],
        help="Open the terminal dashboard (tasks, phase logs, proposals)",
    )
    tui_parser.add_argument(
        "--task",
        default=None,
        help="Task ID to select on launch",
    )
    tui_parser.add_argument(
        "--workspace",
        default=None,
        help="Folder/repo to operate on (default: current directory)",
    )

    # Chat command (inline REPL)
    chat_parser = subparsers.add_parser(
        "chat",
        help="Start an interactive terminal chat REPL",
    )
    chat_parser.add_argument(
        "--provider",
        default=None,
        help="Agent CLI to use (default: first available on PATH from claude, opencode, codex)",
    )
    chat_parser.add_argument(
        "--workspace",
        default=None,
        help="Folder/repo to operate on (default: current directory)",
    )
    chat_parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming; use blocking send instead",
    )

    subparsers.add_parser("desktop", help="Run the local Sarathi desktop stack")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a task through the lifecycle")
    run_parser.add_argument(
        "task_description",
        help="Task description or path to task file",
    )
    run_parser.add_argument(
        "--policy-pack",
        default=None,  # Auto-discovered
        help="Policy pack to use (auto-discovered if not provided)",
    )
    run_parser.add_argument(
        "--complexity",
        choices=["low", "medium", "high", "auto"],
        default="auto",  # Auto-calculated
        help="Complexity classification (auto-calculated if not provided)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show phase sequence without executing",
    )
    run_parser.add_argument(
        "--agent",
        default=None,
        help="Name (key) of a declarative user agent to dispatch this run through (see agents/<name>.md in the policy pack)",
    )
    run_parser.add_argument(
        "--agents-dir",
        default=None,
        help="Directory containing agent spec files (default: <policy-pack>/agents)",
    )
    run_parser.add_argument(
        "--recipe",
        default=None,
        help="Path to a recipe dir/file to execute as a FANOUT/JUDGE workflow graph (instead of the standard lifecycle)",
    )

    # NCP Integration
    run_parser.add_argument(
        "--ncp",
        action="store_true",
        help="Force NCP (Neural Context Protocol) as the context backend. Fails if NCP is unavailable.",
    )
    run_parser.add_argument(
        "--no-ncp",
        action="store_true",
        help="Disable NCP and use native Sarathi adapters.",
    )
    run_parser.add_argument(
        "--ncp-mode",
        choices=["direct", "mcp"],
        default="direct",
        help="NCP transport mode: 'direct' (subprocess via .ncp/run.py, default) or 'mcp' (JSON-RPC over HTTP to the NCP server).",
    )
    run_parser.add_argument(
        "--ncp-router",
        action="store_true",
        help="Enable NCP whisper-based cross-phase signaling router for phase-to-phase context handoff.",
    )

    # Phase log command
    log_parser = subparsers.add_parser("log", help="Show phase log")
    log_parser.add_argument(
        "task_id",
        help="Task ID to show log for",
    )

    status_parser = subparsers.add_parser("status", help="Show task status summary")
    status_parser.add_argument(
        "task_id",
        help="Task ID to show status for",
    )

    watch_parser = subparsers.add_parser("watch", help="Watch task status live")
    watch_parser.add_argument(
        "task_id",
        help="Task ID to watch",
    )
    watch_parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between refreshes (default: 2.0)",
    )
    watch_parser.add_argument(
        "--stale-after",
        type=int,
        default=300,
        help="Mark nodes stale after this many seconds without activity",
    )
    watch_parser.add_argument(
        "--once",
        action="store_true",
        help="Render a single snapshot and exit",
    )
    watch_parser.add_argument(
        "--follow",
        action="store_true",
        help="Stream lifecycle events via SSE instead of polling",
    )
    watch_parser.add_argument(
        "--workspace",
        type=str,
        help="Workspace ID (required when using --follow for service tasks)",
    )

    resume_parser = subparsers.add_parser("resume", help="Resume a saved task")
    resume_parser.add_argument(
        "task_id",
        help="Task ID to resume",
    )

    approve_parser = subparsers.add_parser(
        "approve", help="Approve (or reject) a task paused on a human-attention escalation, then resume it"
    )
    approve_parser.add_argument(
        "task_id",
        help="Task ID to approve",
    )
    approve_parser.add_argument(
        "--note",
        default=None,
        help="Optional note to attach to the approval decision",
    )
    approve_parser.add_argument(
        "--reject",
        action="store_true",
        help="Reject the escalation instead of approving it",
    )

    subparsers.add_parser("list", help="List saved task IDs under .sarathi/tasks")
    proposals_parser = subparsers.add_parser("proposals", help="Show or review policy proposals from persisted learnings")
    proposals_parser.add_argument(
        "--policy-pack",
        default=None,
        help="Policy pack to update when accepting a proposal",
    )
    proposals_parser.add_argument(
        "--accept",
        default=None,
        help="Accept and append the matching proposal ID/prefix to its policy file",
    )
    proposals_parser.add_argument(
        "--reject",
        default=None,
        help="Reject and record the matching proposal ID/prefix",
    )
    proposals_parser.add_argument(
        "--reason",
        default=None,
        help="Optional rejection reason",
    )
    reuse_parser = subparsers.add_parser("reuse", help="Show reusable workflow templates, saved views, and learned playbooks")
    reuse_parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace id or exact workspace name. Required only when multiple workspaces exist.",
    )
    subparsers.add_parser("agents", help="Show Sarathi agent role names and phase mapping")

    autoresearch_parser = subparsers.add_parser(
        "autoresearch",
        help="Manage pre-registered autoresearch experiments",
    )
    autoresearch_parser.add_argument(
        "--store",
        default=".sarathi",
        help="Directory containing autoresearch.jsonl (default: .sarathi)",
    )
    autoresearch_subparsers = autoresearch_parser.add_subparsers(dest="action", required=True)
    ar_register = autoresearch_subparsers.add_parser("register", help="Pre-register a hypothesis")
    ar_register.add_argument("--hypothesis", required=True, help="Hypothesis to test")
    ar_register.add_argument("--prediction", required=True, help="Pre-registered prediction")
    ar_register.add_argument("--tier", choices=["MINE", "MICRO", "FULL"], required=True, help="Evidence tier")
    ar_register.add_argument("--method", required=True, help="Experiment method")
    ar_register.add_argument("--quality-gate", required=True, help="Quality gate that must hold")
    ar_register.add_argument("--created-by", default="sarathi", help="Role or agent registering the hypothesis")

    ar_evidence = autoresearch_subparsers.add_parser("evidence", help="Append evidence to an experiment")
    ar_evidence.add_argument("experiment_id", help="Experiment id")
    ar_evidence.add_argument("--summary", required=True, help="Evidence summary")
    ar_evidence.add_argument("--uri", default=None, help="Artifact URI or path")
    ar_evidence.add_argument(
        "--metric",
        action="append",
        default=[],
        help="Metric as key=value; repeat for multiple metrics",
    )
    ar_evidence.add_argument("--recorded-by", default="sarathi", help="Role or agent recording evidence")

    ar_verdict = autoresearch_subparsers.add_parser("verdict", help="Record a verdict")
    ar_verdict.add_argument("experiment_id", help="Experiment id")
    ar_verdict.add_argument(
        "--verdict",
        choices=["confirmed", "refuted", "inconclusive", "backlog", "superseded"],
        required=True,
        help="Experiment verdict",
    )
    ar_verdict.add_argument("--summary", required=True, help="Verdict summary")
    ar_verdict.add_argument(
        "--evidence-ref",
        action="append",
        default=None,
        help="Evidence id or external ref; repeat for multiple refs",
    )
    ar_verdict.add_argument("--cost-usd", type=float, default=0.0, help="Observed experiment cost")
    ar_verdict.add_argument("--recorded-by", default="sarathi", help="Role or agent recording verdict")

    ar_list = autoresearch_subparsers.add_parser("list", help="List experiments")
    ar_list.add_argument("--status", default=None, help="Filter by status/verdict")

    recipes_parser = subparsers.add_parser("recipes", help="List reference recipes (FANOUT/JUDGE workflow packs)")
    recipes_parser.add_argument(
        "--recipes-dir",
        default="policy-pack/RECIPES",
        help="Directory containing recipe sub-packs (default: policy-pack/RECIPES)",
    )

    # Attach command (join a shared session)
    attach_parser = subparsers.add_parser(
        "attach", help="Attach to a shared Sarathi session via its share token"
    )
    attach_parser.add_argument("share_token", help="The session share token (from a share link)")
    attach_parser.add_argument(
        "--user", default=None, help="Your participant identifier (default: $USER or 'local')"
    )
    attach_parser.add_argument(
        "--role",
        default="observer",
        choices=["observer", "driver"],
        help="Join as observer (read-only) or driver",
    )

    # Fork command (fork a session into a new independent task)
    fork_parser = subparsers.add_parser(
        "fork", help="Fork a session into a new independent task"
    )
    fork_parser.add_argument("session_id", help="The session id to fork")
    fork_parser.add_argument(
        "--owner", default=None, help="Owner for the forked session (default: source owner)"
    )

    if len(sys.argv) > 1 and sys.argv[1] == "desktop":
        args, _desktop_passthrough = parser.parse_known_args()
        setattr(args, "desktop_args", sys.argv[2:])
    else:
        args = parser.parse_args()

    if args.command is None:
        _show_home()
        return
    if args.command == "setup":
        handle_setup(args)
        return
    if args.command in ("tui", "dashboard"):
        handle_tui(args)
        return
    if args.command == "chat":
        handle_chat(args)
        return
    if args.command == "desktop":
        handle_desktop(args)
        return
    if args.command == "init":
        handle_init(args)
    elif args.command == "validate":
        handle_validate(args)
    elif args.command == "run":
        handle_run(args)
    elif args.command == "log":
        handle_log(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "watch":
        handle_watch(args)
    elif args.command == "resume":
        handle_resume(args)
    elif args.command == "approve":
        handle_approve(args)
    elif args.command == "list":
        handle_list_tasks()
    elif args.command == "proposals":
        handle_proposals(args)
    elif args.command == "reuse":
        handle_reuse(args)
    elif args.command == "autoresearch":
        handle_autoresearch(args)
    elif args.command == "attach":
        handle_attach(args)
    elif args.command == "fork":
        handle_fork(args)
    elif args.command == "agents":
        handle_agents()
    elif args.command == "recipes":
        handle_recipes(args)


def handle_init(args: argparse.Namespace) -> None:
    """Handle the init command."""
    from_source = getattr(args, "from_source", None)
    force = getattr(args, "force", False)

    print(f"Initializing Sarathi policy pack at: {args.target_path}")
    print(f"Using engine: {args.engine}")
    if from_source:
        print(f"Importing from: {from_source}")
        if force:
            print("  (--force: will overwrite existing pack)")

    # Handle --from import workflow
    if from_source:
        print("\n[1/3] Import: Loading policy pack from source...")
        import_result = import_policy_pack_from_source(
            from_source,
            args.target_path,
            force=force
        )

        if import_result.get("status") == "error":
            print(f"  Error: {import_result.get('error')}")
            sys.exit(1)

        policy_path = Path(import_result.get("path"))
        print(f"  ✓ Imported {import_result.get('files_copied')} files from {from_source}")
        if import_result.get("warnings"):
            for warning in import_result.get("warnings", []):
                print(f"  ⚠ {warning}")

        # Validate the imported pack
        print("\n[2/3] Validate: Checking imported policy pack...")
        workflow = InitWorkflow(target_path=args.target_path, engine_path=args.engine)
        validation_results = workflow.validate(policy_path)
        passed = sum(1 for r in validation_results if r.status.value == "PASS")
        warnings = sum(1 for r in validation_results if r.status.value == "DRIFT")
        todos = sum(1 for r in validation_results if r.status.value == "TODO")
        print(f"  Results: {passed} PASS, {warnings} DRIFT, {todos} TODO")

        # Generate wiki if needed
        print("\n[3/3] Bootstrap: Finalizing workspace artifacts...")
        if not getattr(args, "no_wiki", False):
            try:
                from .repo_wiki import generate_repo_wiki
            except ImportError:
                from repo_wiki import generate_repo_wiki
            wiki_result = generate_repo_wiki(Path(args.target_path))
            print(f"  Wiki: {wiki_result.get('status')} → {wiki_result.get('path')}")

        # Write provider-native permission config files
        try:
            from .runtime.providers.cli_bridge import ensure_provider_permissions
        except ImportError:
            from runtime.providers.cli_bridge import ensure_provider_permissions
        written = ensure_provider_permissions(args.target_path)
        for provider, config_path in written.items():
            print(f"  Wrote {provider} permissions → {config_path}")

        print("\n✓ Policy pack imported successfully!")
        print(f"\nNext steps:")
        print(f"  1. Review imported files in {policy_path}/")
        print(f"  2. Customize policy-pack/*.md to your team's needs")
        print(f"  3. Run: sarathi validate {policy_path}")
        return

    # Original bootstrap workflow for non-import case
    # Phase 1: Inspect
    print("\n[1/5] Inspect: Scanning repository...")
    workflow = InitWorkflow(target_path=args.target_path, engine_path=args.engine)
    inspection = workflow.inspect()
    print(f"  Detected: {inspection.get('languages', [])}")
    print(f"  Build tools: {inspection.get('build_tools', [])}")
    print(f"  Test patterns: {inspection.get('test_patterns', [])}")

    # Phases 2-3: bootstrap policy pack and wiki.
    print("\n[2/5] Bootstrap: Creating or reusing workspace artifacts...")
    bootstrap = bootstrap_workspace(
        args.target_path,
        engine_path=args.engine,
        with_wiki=not getattr(args, "no_wiki", False),
    )
    policy_path = Path(bootstrap["policy_pack"]["path"])
    print(f"  Policy pack: {bootstrap['policy_pack']['status']} → {policy_path}")
    print(f"  Wiki: {bootstrap['wiki']['status']} → {bootstrap['wiki']['path']}")
    # Write provider-native permission config files from the generated permissions.md
    try:
        from .runtime.providers.cli_bridge import ensure_provider_permissions
    except ImportError:
        from runtime.providers.cli_bridge import ensure_provider_permissions
    written = ensure_provider_permissions(args.target_path)
    for provider, config_path in written.items():
        print(f"  Wrote {provider} permissions → {config_path}")

    # Phase 4: Validate
    print("\n[3/5] Validate: Checking policy pack...")
    validation_results = workflow.validate(policy_path)
    passed = sum(1 for r in validation_results if r.status.value == "PASS")
    print(f"  Passed: {passed}/{len(validation_results)}")

    # Phase 5: Evolve
    print("\n[4/5] Evolve: Learning from setup...")
    workflow.evolve()

    # NCP Integration
    if args.ncp:
        print("\n[6/6] NCP: Initializing Neural Context Protocol...")
        import subprocess

        # Determine init target — use explicit target_path or CWD
        init_target = Path(args.target_path)

        # 1. Run ncp init to bootstrap
        ncp_init_result = subprocess.run(
            ["ncp", "init"],
            capture_output=True, text=True, cwd=str(init_target),
        )
        if ncp_init_result.returncode == 0:
            print("  ✓ NCP initialized")
        else:
            print(f"  ⚠ NCP init warning: {ncp_init_result.stderr.strip()}")

        sidecar_created = _ensure_ncp_sidecar(init_target)
        if sidecar_created["config"]:
            print("  ✓ Wrote .ncp/config.toml from Sarathi template")
        if sidecar_created["run_py"]:
            print("  ✓ Wrote .ncp/run.py direct-mode bridge")
        elif (init_target / ".ncp" / "run.py").exists():
            print("  ✓ Verified .ncp/run.py direct-mode bridge")

        # 2. Write Sarathi-optimized config overrides
        ncp_config_path = init_target / ".ncp" / "config.toml"
        if ncp_config_path.exists():
            config_text = ncp_config_path.read_text()
            overrides = """
# Sarathi-optimized overrides
max_chunk_tokens = 400
default_ttl_hours = 168
"""
            # Only append if not already present
            if "Sarathi-optimized" not in config_text:
                ncp_config_path.write_text(config_text.strip() + "\n" + overrides.strip() + "\n")
                print("  ✓ Wrote Sarathi-optimized NCP config (max_chunk_tokens=400, ttl=168h)")

        # 3. Write welcome note
        welcome_path = init_target / ".ncp" / "WELCOME.md"
        welcome_path.write_text(
            "# NCP + Sarathi\n\n"
            "NCP is configured as the context handler for this project.\n"
            "Run `sarathi run \"task description\"` to use auto-detected NCP, "
            "or pass `--no-ncp` to use native adapters.\n"
        )
        print("  ✓ Wrote .ncp/WELCOME.md")

    print("\n✓ Policy pack initialized successfully!")
    print(f"\nNext steps:")
    print(f"  1. Review generated files in {policy_path}/")
    print(f"  2. Customize policy-pack/*.md to your team's needs")
    print(f"  3. Run: sarathi validate {policy_path}")


def handle_setup(args: argparse.Namespace) -> None:
    """Handle the setup command."""
    workspace = Path(args.workspace).expanduser().resolve()
    choices = {
        "tui": _setup_choice(args, "setup_tui", "Enable Terminal UI?", True),
        "mcp": _setup_choice(args, "setup_mcp", "Enable MCP server?", False),
        "webui": _setup_choice(args, "setup_webui", "Enable WebUI?", True),
        "ncp": _setup_choice(args, "setup_ncp", "Initialize NCP for this workspace?", True),
        "desktop": _setup_choice(args, "setup_desktop", "Configure desktop launcher?", False),
    }

    labels = {
        "tui": "Terminal UI",
        "mcp": "MCP server",
        "webui": "WebUI",
        "ncp": "NCP workspace",
        "desktop": "Desktop launcher",
    }
    extras = [name for name in ("tui", "mcp") if choices[name]]
    repo_root = Path(__file__).resolve().parents[1]
    web_dir = repo_root / "web"

    print("Sarathi setup plan")
    print(f"Workspace: {workspace}")
    for name in ("tui", "mcp", "webui", "ncp", "desktop"):
        state = "enabled" if choices[name] else "skipped"
        print(f"{labels[name]}: {state}")

    planned_commands: list[tuple[str, list[str] | None]] = []
    if extras:
        display, command, _cwd = _setup_extras_install_plan(extras, repo_root)
        planned_commands.append((
            display,
            command,
        ))
    if choices["webui"]:
        planned_commands.append((
            f"cd {web_dir} && npm install && npm run build",
            None,
        ))
    if choices["ncp"]:
        planned_commands.append((
            f"sarathi init {workspace} --ncp",
            None,
        ))
    if choices["desktop"]:
        planned_commands.append((
            "sarathi desktop",
            None,
        ))

    if planned_commands:
        print("\nPlanned actions:")
        for display, _cmd in planned_commands:
            prefix = "Would run" if args.dry_run else "Run"
            print(f"{prefix}: {display}")
    else:
        print("\nNo components selected.")

    if args.dry_run:
        print("\nDry run: no changes made.")
        return

    import subprocess

    if extras:
        if args.install_extras:
            _display, command, cwd = _setup_extras_install_plan(extras, repo_root)
            subprocess.run(
                command,
                cwd=cwd,
                check=True,
            )
        else:
            print("\nOptional Python extras were not installed. Re-run with --install-extras to apply them.")

    if choices["ncp"]:
        handle_init(argparse.Namespace(target_path=str(workspace), engine="markdown", ncp=True, no_wiki=False))

    if choices["webui"]:
        print(f"\nWebUI selected. Build assets when needed with: cd {web_dir} && npm install && npm run build")
    if choices["desktop"]:
        print("Desktop launcher selected. Start it with: sarathi desktop")


def handle_validate(args: argparse.Namespace) -> None:
    """Handle the validate command."""
    # Auto-discover policy pack if not provided
    policy_pack_path = args.policy_pack
    if not policy_pack_path:
        policy_pack_path = discover_policy_pack()
        if policy_pack_path:
            print(f"Auto-discovered policy pack: {policy_pack_path}")
        else:
            print("Error: No policy pack found. Run 'sarathi init' first or specify --policy-pack")
            sys.exit(1)
    else:
        policy_pack_path = str(Path.cwd() / policy_pack_path)

    path = Path(policy_pack_path)
    if not path.exists():
        print(f"Error: Policy pack not found: {policy_pack_path}")
        sys.exit(1)

    print(f"Validating policy pack: {policy_pack_path}")

    validator = PolicyValidator(
        engine_path="engine",
        policy_pack_path=str(path)
    )

    results = validator.validate()

    # Summary
    passed = sum(1 for r in results if r.status.value == "PASS")
    todo = sum(1 for r in results if r.status.value == "TODO")
    drifted = sum(1 for r in results if r.status.value == "DRIFT")

    print(f"\nSummary: {passed} PASS, {drifted} DRIFT, {todo} TODO")

    try:
        compiled = compile_policy_pack(str(path))
        caps = extract_server_caps(compiled)
    except Exception:
        caps = None

    if caps is not None:
        print("\nPolicy caps (server tier):")
        budget = caps["cost_budget_tokens"]
        print(f"  cost_budget_tokens: {budget if budget is not None else 'uncapped'}")
        max_calls = caps["max_tool_calls"]
        print(f"  max_tool_calls: {max_calls if max_calls is not None else 'uncapped'}")
        gates = caps["required_approval_gates"]
        print(f"  required_approval_gates: {gates if gates else 'none'}")

    if args.verbose:
        print("\nDetailed Results:")
        print("-" * 60)
        for r in results:
            status_icon = {"PASS": "✓", "DRIFT": "~", "TODO": "✗"}[r.status.value]
            print(f"  {status_icon} [{r.status.value}] {r.phase}: {r.required_input}")
            if r.policy_file:
                print(f"      → {r.policy_file}")
            if r.issue:
                print(f"      → {r.issue}")


def handle_recipes(args: argparse.Namespace) -> None:
    """List reference recipes discovered under the recipes directory."""
    recipes_dir = Path(args.recipes_dir)
    recipes = load_recipes(recipes_dir)
    if not recipes:
        print(f"No recipes found under {recipes_dir}")
        return
    print(f"Recipes in {recipes_dir}:\n")
    for key, recipe in recipes.items():
        node_count = len(recipe.workflow.get("nodes", []))
        providers = ", ".join(recipe.providers) or "(default)"
        print(f"  {key:<16} {recipe.name}")
        print(f"      {recipe.description}")
        print(f"      providers: {providers}  |  nodes: {node_count}")
        print()


def _run_recipe(args: argparse.Namespace, policy_pack: str) -> None:
    """Execute a recipe's FANOUT/JUDGE workflow graph and print a measured summary."""
    recipe = load_recipe(args.recipe)
    print(f"\nRunning recipe: {recipe.name} ({recipe.key})")
    print(f"  {recipe.description}")
    print(f"  Declared providers: {', '.join(recipe.providers) or '(policy default)'}")

    engine = Engine(
        policy_pack_path=policy_pack,
        enforce_preflight=False,
        ncp_enabled=_resolve_workspace_ncp(args, os.getcwd()),
        ncp_mode=args.ncp_mode,
        ncp_router=args.ncp_router,
    )
    graph = recipe.build_graph().to_artifact()
    executor = TaskGraphExecutor(dispatcher=engine.dispatcher)
    result = executor.execute_all(graph).to_artifact()

    state = result["graph_state"]
    providers_used = set()
    total_tokens = 0
    for event in result["events"]:
        pr = event.get("provider_result") or {}
        usage = pr.get("usage") or {}
        total_tokens += int(usage.get("total_tokens", 0) or 0)
    # Derive providers used from the executed branch nodes' pattern_config
    for node in state.get("nodes", []):
        prov = (node.get("pattern_config") or {}).get("provider")
        if prov:
            providers_used.add(prov)

    print(f"\n✓ Recipe complete: {len(state.get('completed_nodes', []))} nodes")
    print(f"  Providers used (fan-out): {', '.join(sorted(providers_used)) or '(single/default)'}")
    print(f"  Measured token cost: {total_tokens}")


def _run_via_service(args: argparse.Namespace) -> bool:
    """If the local service is reachable, no --recipe, no --dry-run, and a
    workspace can be selected, create a service task draft and print a
    summary — returning True to indicate the caller should return early.

    Returns False for any fallback condition (no service, ambiguous/no
    workspace, --recipe, --dry-run).
    """
    if getattr(args, "recipe", None) or getattr(args, "dry_run", False):
        return False
    try:
        from .service_client import ServiceClient

        client = ServiceClient()
        if not client.available:
            return False
        client.list_workspaces()  # verify reachability
    except Exception:
        return False

    ws = client.select_workspace(cwd=os.getcwd())
    if ws is None:
        return False

    workspace_id = ws.get("id")
    workspace_name = ws.get("name") or workspace_id
    if not isinstance(workspace_id, str) or not workspace_id:
        return False

    prompt = args.task_description
    title = None
    context = None
    try:
        result = client.create_task_draft(workspace_id, prompt, title=title, context=context)
    except RuntimeError as exc:
        print(f"Service task creation failed: {exc}")
        print("Falling back to engine…")
        return False

    task = result.get("task") or {}
    gate = result.get("approval_gate") or {}
    task_id = task.get("id", "")
    gate_id = gate.get("id", "")
    print(f"Created service task draft: {task_id}")
    print(f"  Workspace: {workspace_name} ({workspace_id})")
    print(f"  PRD/AC approval gate: {gate_id}")
    print("  The task is awaiting PRD/AC approval.")
    print("  Use the web cockpit or `sarathi desktop` to review and approve.")
    return True


def handle_run(args: argparse.Namespace) -> None:
    """Handle the run command."""
    # Service route: when the service is reachable, no --recipe, no --dry-run,
    # and a workspace is selectable, create a task draft without needing a
    # policy pack.  The engine path still needs a policy pack below.
    if not getattr(args, "recipe", None) and not getattr(args, "dry_run", False):
        if _run_via_service(args):
            return

    # Auto-discover policy pack (needed for engine and recipe paths)
    policy_pack = args.policy_pack
    if not policy_pack:
        policy_pack = discover_policy_pack()
        if policy_pack:
            print(f"Auto-discovered policy pack: {policy_pack}")
        else:
            print("Error: No policy pack found. Run 'sarathi init' first or specify --policy-pack")
            sys.exit(1)
    else:
        policy_pack = str(Path.cwd() / policy_pack)

    if getattr(args, "recipe", None):
        _run_recipe(args, policy_pack)
        return

    # Resolve declarative user agent (--agent), if requested
    agent_spec = None
    if getattr(args, "agent", None):
        agents_dir_arg = getattr(args, "agents_dir", None)
        agents_dir = Path(agents_dir_arg) if agents_dir_arg else Path(policy_pack) / "agents"
        specs = load_agent_specs(agents_dir)
        if args.agent not in specs:
            available = ", ".join(sorted(specs)) or "(none found)"
            print(f"Error: Unknown agent '{args.agent}'. Available agents in {agents_dir}: {available}")
            sys.exit(1)
        agent_spec = specs[args.agent]
        register_agent_role(agent_spec.to_role())
        print(f"Using declarative agent: {agent_spec.name} ({agent_spec.key})")
        if agent_spec.tools:
            print(f"  Tools: {', '.join(tool.name for tool in agent_spec.tools)}")

    # Auto-calculate or use provided complexity
    if args.complexity == "auto":
        complexity = calculate_complexity(args.task_description)
        print(f"Auto-detected complexity: {complexity.value}")
    else:
        complexity = {"low": Complexity.LOW, "medium": Complexity.MEDIUM, "high": Complexity.HIGH}[args.complexity]

    print(f"\nRunning task: {args.task_description}")
    print(f"Complexity: {complexity.value}")
    print(f"Policy pack: {policy_pack}")

    # Create engine to generate task ID
    engine = Engine(
        policy_pack_path=policy_pack,
        enforce_preflight=True,
        ncp_enabled=_resolve_workspace_ncp(args, os.getcwd()),
        ncp_mode=args.ncp_mode,
        ncp_router=args.ncp_router,
    )

    # Create task context with proper ID generation
    task = TaskContext(
        task_id=engine.generate_task_id(args.task_description),
        description=args.task_description,
        complexity=complexity,
    )
    if agent_spec is not None:
        task.agent_spec = agent_spec

    if args.dry_run:
        phase = Phase.ROUTE
        phases = []
        while phase != Phase.LEARN:
            phases.append(phase.value)
            phase = PHASE_TRANSITIONS.get(phase, Phase.LEARN)
        phases.append(Phase.LEARN.value)

        for i, p in enumerate(phases, 1):
            skip_note = " (skip)" if p == "PlanningAdvisor" and complexity != Complexity.HIGH else ""
            print(f"  {i}. {p}{skip_note}")
        return

    preflight = engine.preflight_validate_policy(task.task_id)
    task.preflight_validation = preflight
    print()
    for line in format_preflight_summary(preflight):
        print(line)
    if preflight["blocking"]:
        return

    print("\nExecuting lifecycle phases:")
    result = engine.run_task(task)

    if result.current_phase is None:
        print(f"\n✓ Task completed: {result.task_id}")
    else:
        print(f"\n↻ Task paused: {result.task_id}")
        print(f"  Resume from: {result.current_phase.value}")
    print(f"  Phases executed: {len(result.phase_results)}")

    # Show phase log
    print("\nPhase Log:")
    print("-" * 85)
    print(f"| {'Phase':<20} | {'Agent':<12} | {'Outcome':<10} | {'Iterations':<10} | {'Gate':<8} |")
    print("|" + "-" * 21 + "+" + "-" * 14 + "+" + "-" * 12 + "+" + "-" * 12 + "+" + "-" * 10 + "|")
    for pr in result.phase_results:
        gate_status = _gate_status_label(pr)
        print(
            f"| {pr.phase.value:<20} | {phase_agent_name(pr):<12} |"
            f" {pr.outcome:<10} | {pr.iterations:<10} | {gate_status:<8} |"
        )


def handle_chat(
    args: argparse.Namespace,
    input_fn=None,
    output_fn=None,
) -> None:
    """Interactive inline terminal REPL for free-form chat with agent CLIs.

    Args:
        args: Parsed arguments with 'provider', 'workspace', 'no_stream' attributes.
        input_fn: Optional callable for testing; defaults to input().
        output_fn: Optional callable for testing; defaults to print().
    """
    try:
        from .tui_data import ChatSession
    except ImportError:
        from tui_data import ChatSession

    if input_fn is None:
        input_fn = input
    if output_fn is None:
        output_fn = print

    workspace = getattr(args, "workspace", None) or os.getcwd()
    provider_name = getattr(args, "provider", None)
    no_stream = getattr(args, "no_stream", False)

    session = ChatSession(workspace_root=workspace)

    # Resolve provider: explicit flag, or first available
    if provider_name:
        if not session.set_provider(provider_name):
            available = ", ".join(name for name, _ in session.available_providers())
            if available:
                output_fn(f"Error: Unknown provider '{provider_name}'. Available: {available}")
            else:
                output_fn("Error: No agent CLIs found on PATH (looked for: claude, opencode, codex)")
            sys.exit(1)
    else:
        provider = session.resolve_provider()
        if provider is None:
            available_providers = session.available_providers()
            if not available_providers:
                output_fn("Error: No agent CLIs found on PATH (looked for: claude, opencode, codex)")
                output_fn("\nSupported providers:")
                for prov_name in session.PROVIDERS:
                    output_fn(f"  - {prov_name}")
                sys.exit(1)

    provider = session.resolve_provider()
    if provider:
        provider_name_active, _ = provider
        output_fn(f"Sarathi Chat | provider: {provider_name_active} | workspace: {workspace} | /help for commands")

    # Main REPL loop
    try:
        while True:
            try:
                user_input = input_fn("you> ")
            except EOFError:
                # Ctrl-D
                break

            if not user_input.strip():
                continue

            # Handle slash commands
            if user_input.startswith("/"):
                parts = user_input[1:].split(maxsplit=1)
                command = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else None

                if command == "quit":
                    break
                elif command == "help":
                    output_fn("\nSlash commands:")
                    output_fn("  /quit              exit the chat")
                    output_fn("  /model [name]      show or switch provider")
                    output_fn("  /help              show this help")
                    output_fn("")
                    continue
                elif command == "model":
                    if arg:
                        if session.set_provider(arg):
                            provider = session.resolve_provider()
                            if provider:
                                provider_name_active, _ = provider
                                output_fn(f"Provider switched to: {provider_name_active}")
                        else:
                            available = ", ".join(
                                name for name, _ in session.available_providers()
                            )
                            output_fn(f"Error: Unknown provider '{arg}'. Available: {available}")
                    else:
                        provider = session.resolve_provider()
                        if provider:
                            provider_name_active, _ = provider
                            output_fn(f"Current provider: {provider_name_active}")
                    continue
                else:
                    output_fn(f"Unknown command: /{command}. Use /help for available commands.")
                    continue

            # Send message (streaming or blocking)
            try:
                if no_stream:
                    reply = session.send(user_input)
                    output_fn(f"assistant> {reply}\n")
                else:
                    # Stream with callback
                    def on_text(accumulated: str) -> None:
                        # Note: for terminal, use print() to avoid carriage return issues
                        # but for testability, we store state in output collection
                        pass

                    reply = session.send_streaming(user_input, on_text=on_text)
                    output_fn(f"assistant> {reply}\n")
            except KeyboardInterrupt:
                # Ctrl-C during a reply: cancel and keep the REPL alive
                session.cancel()
                output_fn("(cancelled)")
    except KeyboardInterrupt:
        # Ctrl-C at the prompt
        output_fn("\n(interrupted)")


def handle_tui(args: argparse.Namespace) -> None:
    """Launch the terminal dashboard."""
    try:
        import textual  # noqa: F401
    except ModuleNotFoundError:
        print("The Sarathi dashboard requires the optional TUI dependencies.")
        print('Install them with: python3 -m pip install "sarathi-ai[tui]"')
        raise SystemExit(1)
    try:
        from .tui import launch_sarathi_tui
    except ImportError:
        from tui import launch_sarathi_tui
    launch_sarathi_tui(
        task_id=getattr(args, "task", None),
        workspace=getattr(args, "workspace", None),
    )


def handle_list_tasks() -> None:
    """List task IDs — from the service when reachable, else local persistence."""
    try:
        from .service_client import ServiceClient

        client = ServiceClient()
        if client.available:
            client.list_workspaces()  # verify reachability
            ws = client.select_workspace(cwd=os.getcwd())
            if ws is not None:
                tasks = client.list_tasks(ws["id"])
                if not tasks:
                    print("No tasks found on the service.")
                    return
                print(f"Service tasks (workspace: {ws.get('name') or ws['id']}):")
                for t in tasks:
                    status = t.get("status", "")
                    title = t.get("title", "")
                    print(f"  {t['id']:<40} {status:<15} {title}")
                return
    except Exception:
        pass

    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()
    ids = persistence.list_tasks()
    if not ids:
        print("No saved tasks. Run `sarathi run \"…\"` first.")
        return
    print(f"Saved tasks ({persistence.storage_path}):")
    for tid in sorted(ids):
        print(f"  {tid}")


def handle_agents() -> None:
    """Show Sarathi's Sanskrit-inspired agent role registry."""
    roles = list_agent_roles()
    print(f"Sarathi Agent Roles: {len(roles)}")
    for role in roles:
        print(f"- {role.name} ({role.purpose})")
        print(f"  Key: {role.key}")
        print(f"  Description: {role.description}")

    print("\nLifecycle Phase Mapping:")
    for mapping in list_phase_agent_roles():
        print(f"- {mapping['phase']}: {mapping['name']} ({mapping['purpose']})")


def _service_discovery_path() -> Path:
    return Path.home() / ".sarathi" / "service.json"


def _read_service_discovery() -> dict[str, Any] | None:
    discovery_path = _service_discovery_path()
    if not discovery_path.exists():
        return None
    try:
        payload = json.loads(discovery_path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _service_auth_token(info: dict[str, Any] | None) -> str | None:
    if not isinstance(info, dict):
        return None
    auth = info.get("auth")
    if not isinstance(auth, dict) or auth.get("type") != "bearer":
        return None
    token = auth.get("token")
    return token if isinstance(token, str) and token else None


def _service_get_json(service_url: str, path: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(f"{service_url.rstrip('/')}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected service response.")
    if not payload.get("ok"):
        error = payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "Service request failed."))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Service response did not contain a data object.")
    return data


def _service_post_json(
    service_url: str,
    path: str,
    body: dict[str, Any],
    *,
    token: str | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{service_url.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        message = None
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            if isinstance(error_payload, dict):
                err = error_payload.get("error") or {}
                if isinstance(err, dict):
                    message = err.get("message")
        except Exception:
            message = None
        raise RuntimeError(str(message or f"Service request failed (HTTP {error.code})."))
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected service response.")
    if not payload.get("ok"):
        error = payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "Service request failed."))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Service response did not contain a data object.")
    return data


def _desktop_launcher_main():
    try:
        from .service.desktop import main as desktop_main
    except ImportError:
        from service.desktop import main as desktop_main
    return desktop_main


def handle_desktop(args: argparse.Namespace) -> None:
    """Run the integrated local desktop launcher via the main Sarathi CLI."""
    launcher = _desktop_launcher_main()
    original_argv = sys.argv[:]
    try:
        sys.argv = ["sarathi desktop", *getattr(args, "desktop_args", [])]
        launcher()
    finally:
        sys.argv = original_argv


def handle_reuse(args: argparse.Namespace) -> None:
    """Show the live reusable workflow kit from the running Sarathi local service."""
    info = _read_service_discovery()
    service_url = info.get("url") if isinstance(info, dict) else None
    service_token = _service_auth_token(info)
    if not service_url:
        print("Sarathi desktop service not running — start it with: sarathi desktop")
        return

    try:
        workspaces = _service_get_json(service_url, "/api/workspaces", token=service_token).get("workspaces", [])
    except Exception as error:
        print(f"Failed to read Sarathi workspaces: {error}")
        return

    if not isinstance(workspaces, list) or len(workspaces) == 0:
        print("No workspaces available yet. Create one in the desktop first.")
        return

    selector = getattr(args, "workspace", None)
    selected = None
    if isinstance(selector, str) and selector.strip():
        needle = selector.strip()
        selected = next(
            (
                workspace for workspace in workspaces
                if workspace.get("id") == needle or workspace.get("name") == needle
            ),
            None,
        )
        if selected is None:
            print(f"Workspace not found: {needle}")
            return
    elif len(workspaces) == 1:
        selected = workspaces[0]
    else:
        print("Multiple workspaces found. Re-run with --workspace <id-or-name>.")
        for workspace in workspaces:
            print(f"  - {workspace.get('name')} ({workspace.get('id')})")
        return

    workspace_id = selected.get("id")
    workspace_name = selected.get("name") or workspace_id
    if not isinstance(workspace_id, str) or not workspace_id:
        print("Selected workspace is missing an id.")
        return

    try:
        reuse_kit = _service_get_json(
            service_url,
            f"/api/workspaces/{workspace_id}/reuse-kit",
            token=service_token,
        )
    except Exception as error:
        print(f"Failed to read workspace reuse kit: {error}")
        return

    templates = reuse_kit.get("templates") if isinstance(reuse_kit.get("templates"), list) else []
    saved_views = reuse_kit.get("saved_views") if isinstance(reuse_kit.get("saved_views"), list) else []
    playbooks = reuse_kit.get("playbooks") if isinstance(reuse_kit.get("playbooks"), list) else []
    active_saved_view = reuse_kit.get("active_saved_view_id")

    print(f"Workspace reuse kit: {workspace_name}")
    print(f"Active saved view: {active_saved_view or 'none'}")

    print("\nWorkflow templates:")
    if templates:
        for template in templates:
            name = template.get("name") or template.get("id") or "template"
            summary = template.get("summary") or "Reusable workflow template."
            recommended_views = template.get("recommended_view_ids") or []
            line = f"  - {name}: {summary}"
            if isinstance(recommended_views, list) and recommended_views:
                line += f" | views: {', '.join(str(item) for item in recommended_views)}"
            print(line)
    else:
        print("  No workflow templates recorded.")

    print("\nSaved views:")
    if saved_views:
        for view in saved_views:
            name = view.get("name") or view.get("id") or "view"
            metric = view.get("metric_label") or "items"
            print(f"  - {name}: {metric}")
    else:
        print("  No saved views recorded.")

    print("\nLearned playbooks:")
    if playbooks:
        for playbook in playbooks:
            name = playbook.get("name") or playbook.get("id") or "playbook"
            summary = playbook.get("summary") or "Reusable playbook from accepted learnings."
            recommended_template = playbook.get("recommended_template_id")
            line = f"  - {name}: {summary}"
            if isinstance(recommended_template, str) and recommended_template:
                line += f" | template: {recommended_template}"
            print(line)
    else:
        print("  No learned playbooks recorded yet.")


def handle_autoresearch(args: argparse.Namespace) -> None:
    """Manage append-only autoresearch experiment records."""
    action = getattr(args, "action", None)

    try:
        store = AutoresearchStore(getattr(args, "store", ".sarathi"))
        if action == "register":
            experiment = store.register(
                hypothesis=args.hypothesis,
                prediction=args.prediction,
                tier=args.tier,
                method=args.method,
                quality_gate=args.quality_gate,
                created_by=getattr(args, "created_by", "sarathi"),
            )
            print(f"Registered experiment {experiment.experiment_id} [{experiment.tier.value}]")
            print(f"  Hypothesis: {experiment.hypothesis}")
            print(f"  Prediction: {experiment.prediction}")
            print(f"  Gate: {experiment.quality_gate}")
        elif action == "evidence":
            evidence = store.append_evidence(
                args.experiment_id,
                summary=args.summary,
                uri=getattr(args, "uri", None),
                metrics=_parse_autoresearch_metrics(getattr(args, "metric", [])),
                recorded_by=getattr(args, "recorded_by", "sarathi"),
            )
            print(f"Recorded evidence {evidence.evidence_id} for {evidence.experiment_id}")
            if evidence.uri:
                print(f"  URI: {evidence.uri}")
        elif action == "verdict":
            evidence_refs = getattr(args, "evidence_ref", None)
            verdict = store.record_verdict(
                args.experiment_id,
                verdict=args.verdict,
                summary=args.summary,
                evidence_refs=list(evidence_refs) if evidence_refs is not None else None,
                cost_usd=float(getattr(args, "cost_usd", 0.0) or 0.0),
                recorded_by=getattr(args, "recorded_by", "sarathi"),
            )
            print(f"Recorded verdict {verdict.verdict} for {args.experiment_id}")
            print(f"  Summary: {verdict.summary}")
        elif action == "list":
            experiments = store.list(status=getattr(args, "status", None))
            print(f"Autoresearch Experiments: {len(experiments)}")
            for experiment in experiments:
                print(
                    f"- {experiment.experiment_id}"
                    f" [{experiment.tier.value}]"
                    f" {experiment.status}: {experiment.hypothesis}"
                )
                print(f"  Prediction: {experiment.prediction}")
                if experiment.verdict is not None:
                    print(f"  Verdict: {experiment.verdict.summary}")
        else:
            raise SystemExit(f"Unknown autoresearch action: {action}")
    except KeyError as exc:
        message = exc.args[0] if exc.args else str(exc)
        raise SystemExit(message) from exc
    except ValueError as exc:
        raise SystemExit(f"Invalid autoresearch input: {exc}") from exc


def _parse_autoresearch_metrics(metric_args: list[str] | None) -> dict[str, Any]:
    """Parse repeated key=value metric flags into JSON-friendly values."""
    metrics: dict[str, Any] = {}
    for item in metric_args or []:
        key, separator, value = item.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"metric must be key=value: {item}")
        metrics[key] = _parse_metric_value(value.strip())
    return metrics


def _parse_metric_value(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def handle_attach(args: argparse.Namespace) -> None:
    """Attach to a shared Sarathi session via its share token."""
    info = _read_service_discovery()
    service_url = info.get("url") if isinstance(info, dict) else None
    token = _service_auth_token(info)
    if not service_url:
        print(
            "No running Sarathi service found. Start it with: "
            "python3 -m src.service --db ~/.sarathi/sarathi.db --port 8765"
        )
        return

    user = args.user or os.environ.get("USER") or "local"

    try:
        data = _service_post_json(
            service_url,
            "/api/sessions/attach",
            {"share_token": args.share_token, "user": user, "role": args.role},
            token=token,
        )
    except RuntimeError as exc:
        print(f"Could not attach: {exc}")
        return

    session = data["session"]
    participant = data["participant"]
    role = participant.get("role", args.role)

    print(f"Attached to session {session['id']}")
    print(f"  task: {session['task_id']}")
    print(f"  role: {role}")
    print(f"  visibility: {session.get('visibility', 'unknown')}")

    try:
        detail = _service_get_json(service_url, f"/api/sessions/{session['id']}", token=token)
        participants = detail.get("participants", [])
        print("\nParticipants:")
        if participants:
            for member in participants:
                print(
                    f"  - {member.get('user')} ({member.get('role')}) "
                    f"[{member.get('status')}]"
                )
        else:
            print("  (none)")

        msgs = _service_get_json(
            service_url, f"/api/sessions/{session['id']}/messages", token=token
        ).get("messages", [])
        print("\nRecent messages:")
        if msgs:
            for message in msgs[-10:]:
                print(f"  {message.get('role')}: {message.get('content')}")
        else:
            print("  (no messages yet)")
    except RuntimeError as exc:
        print(f"\n(Could not load session details: {exc})")

    if role == "observer":
        print("\nNote: observers are read-only and cannot drive the session.")


def handle_fork(args: argparse.Namespace) -> None:
    """Fork a session into a new independent task via the running service."""
    info = _read_service_discovery()
    service_url = info.get("url") if isinstance(info, dict) else None
    token = _service_auth_token(info)
    if not service_url:
        print(
            "No running Sarathi service found. Start it with: "
            "python3 -m src.service --db ~/.sarathi/sarathi.db --port 8765"
        )
        return

    body: dict[str, Any] = {}
    if args.owner:
        body["owner"] = args.owner

    try:
        data = _service_post_json(
            service_url,
            f"/api/sessions/{args.session_id}/fork",
            body,
            token=token,
        )
    except RuntimeError as exc:
        print(f"Could not fork: {exc}")
        return

    task = data["task"]
    session = data["session"]
    checkpoint = data.get("checkpoint") or {}

    print(f"Forked session {args.session_id}")
    print(f"  new task:    {task['id']}")
    print(f"  new session: {session['id']}")
    if checkpoint.get("id"):
        print(f"  checkpoint:  {checkpoint['id']}")
    print(f"  messages copied: {data.get('messages_copied', 0)}")

    ncp = data.get("ncp")
    if isinstance(ncp, dict):
        print(
            "  NCP seed: "
            f"{ncp.get('parent_findings_carried', 0)} parent finding(s) carried, "
            f"seed_written={ncp.get('seed_written')}"
        )


def handle_proposals(args: argparse.Namespace | None = None) -> None:
    """Show policy proposals generated from persisted Learn artifacts."""
    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()
    records = []
    for task_id in persistence.list_tasks():
        task = persistence.load_task(task_id)
        if task is None:
            continue
        for result in task.phase_results:
            record = result.artifacts.get("learning_record")
            if isinstance(record, dict):
                records.append(record)

    proposals = Evolver().generate_policy_proposals(learning_records=records)
    if not proposals:
        print("No policy proposals found from persisted learnings.")
        return

    accept_id = getattr(args, "accept", None) if args is not None else None
    reject_id = getattr(args, "reject", None) if args is not None else None
    if accept_id and reject_id:
        print("Choose either --accept or --reject, not both.")
        return
    if accept_id or reject_id:
        proposal = _find_proposal(proposals, accept_id or reject_id)
        if proposal is None:
            print(f"Proposal not found: {accept_id or reject_id}")
            return
        policy_pack = (
            getattr(args, "policy_pack", None)
            if args is not None and getattr(args, "policy_pack", None)
            else discover_policy_pack()
        )
        if not policy_pack:
            print("No policy pack found. Pass --policy-pack to accept or reject proposals.")
            return
        store = ProposalReviewStore(policy_pack)
        if accept_id:
            decision = store.accept(proposal)
            print(f"Accepted proposal {decision['id']} -> {decision['policy_file']}")
        else:
            decision = store.reject(proposal, reason=getattr(args, "reason", None))
            print(f"Rejected proposal {decision['id']}: {decision['title']}")
        return

    print(f"Policy Proposals: {len(proposals)}")
    for proposal in proposals:
        artifact = proposal.to_artifact()
        print(f"- [{artifact['id']}] {artifact['title']} -> {artifact['policy_file']}")
        print(f"  Confidence: {artifact['confidence']:.2f}")
        print(f"  Rationale: {artifact['rationale']}")


def _find_proposal(proposals, proposal_id: str):
    matches = [
        proposal for proposal in proposals
        if proposal.proposal_id == proposal_id or proposal.proposal_id.startswith(proposal_id)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _log_via_service(task_id: str) -> bool:
    """Print a service task log if the task exists on the service.
    Returns True if handled, False for fallback."""
    try:
        from .service_client import ServiceClient

        client = ServiceClient()
        if not client.available:
            return False
        client.list_workspaces()  # verify reachability
    except Exception:
        return False

    task = client.get_task(task_id)
    if task is None:
        return False

    title = task.get("title", "")
    description = task.get("description", "")
    status = task.get("status", "")
    metadata = task.get("metadata") or {}

    print(f"Task: {task_id}")
    print(f"Description: {title or description}")
    print(f"Complexity: {metadata.get('complexity', '-')}")
    print(f"Status: {status}")
    print()

    messages = client.get_messages(task_id)
    if messages:
        print(f"Messages ({len(messages)}):")
        print("-" * 60)
        for msg in messages[-10:]:
            role = msg.get("role", "?")
            content = (msg.get("content") or "")[:200]
            print(f"  [{role}] {content}")
        print()

    approvals = client.get_approvals(task_id)
    if approvals:
        print("Approval Gates:")
        for gate in approvals:
            gate_name = gate.get("name", "?")
            gate_status = gate.get("status", "?")
            print(f"  - {gate_name}: {gate_status}")

    events = client.get_events(task_id)
    if events:
        print(f"\nLifecycle Events ({len(events)}):")
        for ev in events:
            ts = str(ev.get("created_at", ""))[:19].replace("T", " ")
            etype = ev.get("event_type", "")
            print(f"  {ts}  {etype}")

    return True


def handle_log(args: argparse.Namespace) -> None:
    """Handle the log command — tries the service first, then local persistence."""
    if _log_via_service(args.task_id):
        return

    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()

    # Try to load the task
    task = persistence.load_task(args.task_id)

    if task is None:
        print(f"Task {args.task_id} not found. Available tasks: {persistence.list_tasks()}")
        return

    print(f"Task: {task.task_id}")
    print(f"Description: {task.description}")
    print(f"Complexity: {task.complexity.value}")
    print(f"Current Phase: {task.current_phase.value if task.current_phase else 'Completed'}")
    print()

    if task.phase_results:
        print("Phase Results:")
        print("-" * 94)
        print(f"{'Phase':<20} {'Agent':<12} {'Outcome':<10} {'Iterations':<10} {'Evidence'}")
        print("-" * 94)

        for pr in task.phase_results:
            evidence_summary = ", ".join(f"{k}: {v}" for k, v in pr.evidence.items() if isinstance(v, (str, int, bool)))
            if len(evidence_summary) > 50:
                evidence_summary = evidence_summary[:47] + "..."
            print(
                f"{pr.phase.value:<20} {phase_agent_name(pr):<12}"
                f" {pr.outcome:<10} {pr.iterations:<10} {evidence_summary}"
            )

            if pr.error:
                print(f"  Error: {pr.error}")
            bundle = pr.artifacts.get("escalation_bundle")
            if isinstance(bundle, dict):
                print_escalation_summary(bundle, prefix="  ")
    else:
        print("No phase results recorded yet.")

    # Show phase log file if it exists
    log_file = persistence.storage_path / f"{args.task_id}_phases.log"
    if log_file.exists():
        print(f"\nPhase Transition Log ({log_file}):")
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    print(f"  {line.strip()}")
        except Exception as e:
            print(f"  Error reading log: {e}")


def _status_via_service(task_id: str) -> bool:
    """Print a service task status if the task exists on the service.
    Returns True if handled, False for fallback."""
    try:
        from .service_client import ServiceClient

        client = ServiceClient()
        if not client.available:
            return False
        client.list_workspaces()  # verify reachability
    except Exception:
        return False

    task = client.get_task(task_id)
    if task is None:
        return False

    title = task.get("title", "")
    description = task.get("description", "")
    status = task.get("status", "")
    metadata = task.get("metadata") or {}
    created = str(task.get("created_at", ""))[:19].replace("T", " ")
    updated = str(task.get("updated_at", ""))[:19].replace("T", " ")

    print(f"Task: {task_id}")
    print(f"Description: {title or description}")
    print(f"Complexity: {metadata.get('complexity', '-')}")
    print(f"Status: {status}")
    print(f"Created: {created}")
    print(f"Updated: {updated}")
    print()

    approvals = client.get_approvals(task_id)
    if approvals:
        print("Approval Gates:")
        for gate in approvals:
            gate_name = gate.get("name", "?")
            gate_status = gate.get("status", "?")
            print(f"  - {gate_name}: {gate_status}")
    print()

    events = client.get_events(task_id)
    if events:
        last_event = events[-1]
        ts = str(last_event.get("created_at", ""))[:19].replace("T", " ")
        etype = last_event.get("event_type", "")
        print(f"Last event: {ts}  {etype}")
    else:
        print("No lifecycle events recorded.")
    return True


def handle_status(args: argparse.Namespace) -> None:
    """Handle the status command — tries the service first, then local persistence."""
    if _status_via_service(args.task_id):
        return

    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()
    task = persistence.load_task(args.task_id)

    if task is None:
        print(f"Task {args.task_id} not found. Available tasks: {persistence.list_tasks()}")
        return

    _print_task_status(task, stale_after_seconds=300)


def _print_task_status(task: TaskContext, *, stale_after_seconds: int = 300) -> None:
    """Print a compact supervision snapshot for a persisted task."""
    print(f"Task: {task.task_id}")
    print(f"Description: {task.description}")
    print(f"Complexity: {task.complexity.value}")
    print(f"Current Phase: {task.current_phase.value if task.current_phase else 'Completed'}")
    if task.preflight_validation:
        print(
            "Preflight:"
            f" {task.preflight_validation.get('passed', 0)} PASS,"
            f" {task.preflight_validation.get('warning_count', 0)} WARN,"
            f" {task.preflight_validation.get('todo', 0)} TODO"
        )
    print(f"Phases Recorded: {len(task.phase_results)}")
    usage_line = _usage_summary_line(task)
    if usage_line is not None:
        print(usage_line)
    budget_line = _budget_summary_line(task)
    if budget_line is not None:
        print(budget_line)
    crash_line = _crash_recovery_summary_line(task)
    if crash_line is not None:
        print(crash_line)
    if task.task_graph_state:
        summary = graph_summary(task.task_graph_state)
        print(
            "Task Graph:"
            f" {summary.get('completed', 0)} completed,"
            f" {summary.get('pending', 0)} pending,"
            f" {summary.get('total', 0)} total"
        )
        next_node = next_ready_node(task.task_graph_state)
        if next_node is not None:
            print(f"Next Node: {next_node.get('id')} - {next_node.get('title')}")
        last_node = latest_completed_node(task.task_graph_state)
        if last_node is not None:
            print(
                "Last Completed Node:"
                f" {last_node.get('id')} - {last_node.get('title')}"
                f" (attempts: {last_node.get('attempts', 0)})"
            )
        failed_node = latest_failed_node(task.task_graph_state)
        if failed_node is not None:
            print(
                "Failed Node:"
                f" {failed_node.get('id')} - {failed_node.get('title')}"
                f" (attempts: {failed_node.get('attempts', 0)})"
            )
        retryable_node = next_retryable_failed_node(task.task_graph_state)
        if retryable_node is not None:
            print(f"Retryable Node: {retryable_node.get('id')} - {retryable_node.get('title')}")
        compact_summary = supervision_summary(task.task_graph_state, stale_after_seconds=stale_after_seconds)
        print(
            "Supervision:"
            f" {compact_summary.get('running', 0)} running,"
            f" {compact_summary.get('blocked', 0)} blocked,"
            f" {compact_summary.get('waiting_user', 0)} waiting_user,"
            f" {compact_summary.get('stale', 0)} stale,"
            f" {compact_summary.get('done', 0)} done"
        )
        manifest = task_manifest_from_graph(
            task.task_graph_state,
            parent_task_id=task.task_id,
            stale_after_seconds=stale_after_seconds,
        )
        if manifest:
            print("Task Manifest:")
            for item in manifest:
                line = (
                    f"  - {item['node_id']}: {item['title']}"
                    f" [{item['progress_state']}]"
                )
                if item.get("parent_task_id"):
                    line += f" parent={item['parent_task_id']}"
                if item.get("child_task_ids"):
                    line += f" child={','.join(item['child_task_ids'])}"
                if item.get("needs_from"):
                    line += f" needs_from={','.join(item['needs_from'])}"
                if item.get("block_reason"):
                    line += f" reason={item['block_reason']}"
                context_summary = item.get("context_pack_summary")
                if isinstance(context_summary, dict):
                    objective = context_summary.get("objective")
                    token_budget = context_summary.get("token_budget")
                    estimated_tokens = context_summary.get("estimated_tokens")
                    if isinstance(objective, str) and objective:
                        line += f" ctx={objective}"
                    if token_budget is not None and estimated_tokens is not None:
                        line += f" budget={estimated_tokens}/{token_budget}"
                print(line)
    if task.phase_results:
        last = task.phase_results[-1]
        print(f"Last Outcome: {last.phase.value} -> {last.outcome}")
        print(f"Last Agent: {phase_agent_name(last)}")
    bundle = latest_escalation_bundle(task)
    if bundle is not None:
        print_escalation_summary(bundle)


def _parse_sse_stream(lines: list[str]) -> Any:
    """Parse SSE stream lines into (event_id, event_type, data_dict) tuples.

    Yields (event_id, event_type, data_dict) for each complete SSE frame.
    Handles multi-line data payloads, ignores junk lines.
    """
    event_id = None
    event_type = None
    data_lines = []

    for line in lines:
        line = line.rstrip("\r\n")

        # Blank line signals end of frame
        if not line:
            if event_type is not None:
                # Join multi-line data payloads
                data_str = "\n".join(data_lines)
                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, ValueError):
                    data = data_str
                yield (event_id, event_type, data)
            # Reset for next frame
            event_id = None
            event_type = None
            data_lines = []
            continue

        # Parse SSE frame lines
        if line.startswith("id:"):
            event_id = line[3:].lstrip()
        elif line.startswith("event:"):
            event_type = line[6:].lstrip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        # Ignore comments and other lines


def _follow_task_events(base_url: str, token: str, workspace_id: str, task_id: str) -> None:
    """Stream task lifecycle events from SSE endpoint.

    Opens the SSE stream at {base_url}/api/workspaces/{workspace_id}/tasks/{task_id}/events/stream,
    parses events, and prints one concise line per event. Handles KeyboardInterrupt cleanly.
    On connection drop, reconnects once with Last-Event-ID header.
    """
    stream_url = f"{base_url.rstrip('/')}/api/workspaces/{workspace_id}/tasks/{task_id}/events/stream"
    last_event_id = None
    reconnect_count = 0
    max_reconnects = 1

    try:
        while reconnect_count <= max_reconnects:
            try:
                request = urllib.request.Request(stream_url)
                request.add_header("Authorization", f"Bearer {token}")
                if last_event_id:
                    request.add_header("Last-Event-ID", last_event_id)

                with urllib.request.urlopen(request, timeout=None) as response:
                    print(f"Following task {task_id}...")
                    reconnect_count = 0  # Reset on successful connection

                    # Read lines from the stream
                    buffer = []
                    for line_bytes in response:
                        line = line_bytes.decode("utf-8")
                        buffer.append(line)

                    # Parse all buffered lines
                    for event_id, event_type, data in _parse_sse_stream(buffer):
                        last_event_id = event_id
                        # Print concise summary
                        timestamp = time.strftime("%H:%M:%S")
                        if isinstance(data, dict):
                            payload_summary = data.get("object_id", "")
                            if payload_summary:
                                print(f"{timestamp} [{event_type}] {payload_summary}")
                            else:
                                print(f"{timestamp} [{event_type}]")
                        else:
                            print(f"{timestamp} [{event_type}]")

                    # Stream ended cleanly
                    raise SystemExit(0)

            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print("Authentication failed. Check your service token.")
                    raise SystemExit(1)
                elif e.code == 404:
                    print("Task or workspace not found.")
                    raise SystemExit(1)
                else:
                    if reconnect_count < max_reconnects:
                        print(f"Connection failed (HTTP {e.code}). Reconnecting...")
                        reconnect_count += 1
                        time.sleep(1)
                    else:
                        print(f"Connection dropped. Exiting.")
                        raise SystemExit(0)

            except urllib.error.URLError as e:
                if reconnect_count < max_reconnects:
                    print(f"Connection lost: {e.reason}. Reconnecting...")
                    reconnect_count += 1
                    time.sleep(1)
                else:
                    print(f"Connection dropped. Exiting.")
                    raise SystemExit(0)

    except KeyboardInterrupt:
        print("\nStream stopped.")
        raise SystemExit(0)


def handle_watch(args: argparse.Namespace) -> None:
    """Watch a persisted task and refresh the compact supervision view."""
    # Check if following via SSE
    if getattr(args, "follow", False):
        info = _read_service_discovery()
        service_url = info.get("url") if isinstance(info, dict) else None
        service_token = _service_auth_token(info)
        if not service_url:
            print("Sarathi desktop service not running — start it with: sarathi desktop")
            raise SystemExit(1)

        workspace_id = getattr(args, "workspace", None)
        if not workspace_id:
            # Try to find workspace by querying service
            try:
                workspaces = _service_get_json(service_url, "/api/workspaces", token=service_token).get("workspaces", [])
            except Exception as e:
                print(f"Could not discover workspaces: {e}")
                raise SystemExit(1)

            if not workspaces:
                print("No workspaces available. Create one with: sarathi desktop")
                raise SystemExit(1)
            elif len(workspaces) == 1:
                workspace_id = workspaces[0].get("id")
            else:
                print("Multiple workspaces found. Specify one with: --workspace <id>")
                for ws in workspaces:
                    print(f"  - {ws.get('name')} ({ws.get('id')})")
                raise SystemExit(1)

        _follow_task_events(service_url, service_token, workspace_id, args.task_id)
        return

    # Default polling behavior
    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()
    iterations = 1 if getattr(args, "once", False) else None
    count = 0
    try:
        while iterations is None or count < iterations:
            task = persistence.load_task(args.task_id)
            if task is None:
                print(f"Task {args.task_id} not found. Available tasks: {persistence.list_tasks()}")
                return
            if count > 0:
                print("\n" + "=" * 94 + "\n")
            print(f"Watch: {task.task_id}")
            print(f"Refreshed: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            _print_task_status(task, stale_after_seconds=getattr(args, "stale_after", 300))
            count += 1
            if iterations is None:
                time.sleep(max(getattr(args, "interval", 2.0), 0.1))
    except KeyboardInterrupt:
        print("\nWatch stopped.")


def handle_resume(args: argparse.Namespace) -> None:
    """Handle the resume command."""
    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()
    task = persistence.load_task(args.task_id)

    if task is None:
        print(f"Task {args.task_id} not found. Available tasks: {persistence.list_tasks()}")
        return

    policy_pack = discover_policy_pack()
    if not policy_pack:
        print("Error: No policy pack found. Run 'sarathi init' first or specify --policy-pack")
        raise SystemExit(1)
    engine = Engine(policy_pack_path=policy_pack, enforce_preflight=True)
    engine.persistence = persistence

    result = engine.resume_task(task)
    print(f"Resumed task: {result.task_id}")
    if result.current_phase is not None:
        print(f"Current phase: {result.current_phase.value}")
        role = list_phase_agent_roles()
        current_role = next(
            (mapping for mapping in role if mapping.get("phase") == result.current_phase.value),
            None,
        )
        if current_role is not None:
            print(f"Current agent: {current_role['name']}")
    print(f"Phases executed: {len(result.phase_results)}")


def _current_username() -> str:
    """Best-effort local username for approval attribution."""
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or "local"


def handle_approve(args: argparse.Namespace) -> None:
    """Handle the approve command: record an approval/rejection, then resume."""
    persistence_cls = globals().get("PersistenceManager")
    if persistence_cls is None:
        try:
            from .engine import PersistenceManager as persistence_cls
        except ImportError:
            from engine import PersistenceManager as persistence_cls

    persistence = persistence_cls()
    task = persistence.load_task(args.task_id)

    if task is None:
        print(f"Task {args.task_id} not found. Available tasks: {persistence.list_tasks()}")
        raise SystemExit(1)

    policy_pack = discover_policy_pack()
    if not policy_pack:
        print("Error: No policy pack found. Run 'sarathi init' first or specify --policy-pack")
        raise SystemExit(1)
    engine = Engine(policy_pack_path=policy_pack, enforce_preflight=True)
    engine.persistence = persistence

    approve = not args.reject
    try:
        task = engine.record_approval(
            task,
            approved_by=_current_username(),
            approve=approve,
            note=args.note,
        )
    except ValueError as exc:
        print(f"Cannot approve task {args.task_id}: {exc}")
        raise SystemExit(1)

    if not approve:
        print(f"Rejected task: {task.task_id}")
        if args.note:
            print(f"Reason: {args.note}")
        return

    print(f"Approved task: {task.task_id}")
    result = engine.resume_task(task)
    print(f"Resumed task: {result.task_id}")
    if result.current_phase is not None:
        print(f"Current phase: {result.current_phase.value}")
    print(f"Phases executed: {len(result.phase_results)}")


if __name__ == "__main__":
    main()
