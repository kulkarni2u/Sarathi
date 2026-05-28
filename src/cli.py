"""CLI implementation for Sarathi."""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .evolve import Evolver, ProposalReviewStore
    from .init import InitWorkflow
    from .runtime import UsageRecord, list_agent_roles, list_phase_agent_roles
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
    from init import InitWorkflow
    from runtime import UsageRecord, list_agent_roles, list_phase_agent_roles
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
    if service_url:
        try:
            data = _service_get_json(service_url, "/api/workspaces")
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
    parser.add_argument(
        "-m", "--message",
        default=None,
        help="Initial message to send to the TUI"
    )
    parser.add_argument(
        "-x", "--exit",
        action="store_true",
        help="Exit after processing initial message (for testing)"
    )
    subparsers = parser.add_subparsers(dest="command")

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

    # Chat command (launches TUI)
    chat_parser = subparsers.add_parser("chat", help="Start interactive chat mode")

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

    resume_parser = subparsers.add_parser("resume", help="Resume a saved task")
    resume_parser.add_argument(
        "task_id",
        help="Task ID to resume",
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

    if len(sys.argv) > 1 and sys.argv[1] == "desktop":
        args, _desktop_passthrough = parser.parse_known_args()
        setattr(args, "desktop_args", sys.argv[2:])
    else:
        args = parser.parse_args()

    # Check for stdin input or message argument
    initial_message = None
    if args.message:
        initial_message = args.message
    elif not sys.stdin.isatty():
        # Read from stdin if piped
        initial_message = sys.stdin.read().strip()

    if args.command is None:
        _show_home()
        return
    if args.command == "chat":
        from src.tui import launch_sarathi_tui
        launch_sarathi_tui(initial_message, exit_after=args.exit)
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
    elif args.command == "list":
        handle_list_tasks()
    elif args.command == "proposals":
        handle_proposals(args)
    elif args.command == "reuse":
        handle_reuse(args)
    elif args.command == "agents":
        handle_agents()


def handle_init(args: argparse.Namespace) -> None:
    """Handle the init command."""
    print(f"Initializing Sarathi policy pack at: {args.target_path}")
    print(f"Using engine: {args.engine}")

    workflow = InitWorkflow(
        target_path=args.target_path,
        engine_path=args.engine
    )

    # Phase 1: Inspect
    print("\n[1/5] Inspect: Scanning repository...")
    inspection = workflow.inspect()
    print(f"  Detected: {inspection.get('languages', [])}")
    print(f"  Build tools: {inspection.get('build_tools', [])}")
    print(f"  Test patterns: {inspection.get('test_patterns', [])}")

    # Phase 2: Interview
    print("\n[2/5] Interview: Gathering policy preferences...")
    interview = workflow.interview(inspection)
    print("  Policy keys: configured")
    print("  Task tracking: configured")

    # Phase 3: Generate
    print("\n[3/5] Generate: Creating policy pack...")
    policy_path = workflow.generate(inspection, interview)
    print(f"  Created: {policy_path}")

    # Phase 4: Validate
    print("\n[4/5] Validate: Checking policy pack...")
    validation_results = workflow.validate(policy_path)
    passed = sum(1 for r in validation_results if r.status.value == "PASS")
    print(f"  Passed: {passed}/{len(validation_results)}")

    # Phase 5: Evolve
    print("\n[5/5] Evolve: Learning from setup...")
    workflow.evolve()

    # NCP Integration
    if args.ncp:
        print("\n[6/6] NCP: Initializing Neural Context Protocol...")
        import subprocess
        import sys
        from pathlib import Path

        # Determine init target — use explicit target_path or CWD
        init_target = Path(args.target_path)

        # 1. Run ncp init to bootstrap
        ncp_init_result = subprocess.run(
            [sys.executable, "-m", "ncp", "init"],
            capture_output=True, text=True, cwd=str(init_target),
        )
        if ncp_init_result.returncode == 0:
            print("  ✓ NCP initialized")
        else:
            print(f"  ⚠ NCP init warning: {ncp_init_result.stderr.strip()}")

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
            "Run `sarathi run --ncp \"task description\"` to use it.\n"
        )
        print("  ✓ Wrote .ncp/WELCOME.md")

    print("\n✓ Policy pack initialized successfully!")
    print(f"\nNext steps:")
    print(f"  1. Review generated files in {policy_path}/")
    print(f"  2. Customize policy-pack/*.md to your team's needs")
    print(f"  3. Run: sarathi validate {policy_path}")


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


def handle_run(args: argparse.Namespace) -> None:
    """Handle the run command."""
    # Auto-discover policy pack
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
    print("-" * 75)
    print(f"| {'Phase':<20} | {'Agent':<12} | {'Outcome':<10} | {'Iterations':<10} |")
    print("|" + "-" * 21 + "+" + "-" * 14 + "+" + "-" * 12 + "+" + "-" * 12 + "|")
    for pr in result.phase_results:
        print(
            f"| {pr.phase.value:<20} | {phase_agent_name(pr):<12} |"
            f" {pr.outcome:<10} | {pr.iterations:<10} |"
        )


def handle_list_tasks() -> None:
    """List task IDs persisted by the engine."""
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


def _service_get_json(service_url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{service_url.rstrip('/')}{path}", timeout=2) as response:
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
    if not service_url:
        print("Sarathi desktop service not running — start it with: sarathi desktop")
        return

    try:
        workspaces = _service_get_json(service_url, "/api/workspaces").get("workspaces", [])
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


def handle_log(args: argparse.Namespace) -> None:
    """Handle the log command."""
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


def handle_status(args: argparse.Namespace) -> None:
    """Handle the status command."""
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


def handle_watch(args: argparse.Namespace) -> None:
    """Watch a persisted task and refresh the compact supervision view."""
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


if __name__ == "__main__":
    main()
