# Sarathi How-To Guide

**Last Updated:** 2026-04-24  
**Version:** 1.0

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Installation Options](#2-installation-options)
3. [Using as a CLI](#3-using-as-a-cli)
4. [Using as a Python API](#4-using-as-a-python-api)
5. [Using with AI Agents](#5-using-with-ai-agents)
6. [Policy Pack Setup](#6-policy-pack-setup)
7. [NCP Integration (optional)](#7-ncp-integration-optional)
8. [Common Workflows](#8-common-workflows)
9. [Task Management](#9-task-management)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Quick Start

### One-Line Install

```bash
cd /path/to/Sarathi
python3 -m pip install -e .
```

### Verify Installation

```bash
sarathi --help
```

Output:
```
usage: sarathi [-h] {init,validate,run,list,log,status,resume,proposals,agents} ...

Sarathi - Workflow orchestration framework
```

### Initialize a Project

```bash
cd my-project
sarathi init .
sarathi validate ./policy-pack
```

---

## 2. Installation Options

### Option A: Developer Install (Recommended)

```bash
cd Sarathi
python3 -m pip install -e .
```

**Pros:** Updates reflect immediately, can edit source  
**Cons:** Requires git clone

### Option B: From Wheel

```bash
python3 -m pip install sarathi-*.whl
```

### Option C: Virtual Environment

```bash
cd Sarathi
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

---

## 3. Using as a CLI

### 3.1 Initialize New Project

```bash
sarathi init ./my-new-project
```

This creates:
```
my-new-project/
└── policy-pack/
    ├── complexity.md
    ├── commands.md
    ├── conventions.md
    ├── escalation.md
    ├── model-routing.md
    ├── review.md
    ├── skills.md
    └── task-tracking.md
```

### 3.2 Validate Policy Pack

```bash
# Quick check
sarathi validate ./policy-pack

# Detailed output
sarathi validate ./policy-pack --verbose
```

Sample output:
```
Validating policy pack: ./policy-pack
Summary: 8 PASS, 0 DRIFT, 2 TODO
```

### 3.3 Provider Dispatch Options

Workspace provider settings are used by the local service when a subtask is dispatched:

- `local` uses the deterministic built-in adapter.
- `codex` uses a native `codex exec` bridge when the Codex CLI is installed.
- `copilot` and `claude` can use native CLI bridges when those CLIs are available locally.
- Advanced users can point any provider at a custom executable that accepts Sarathi JSON on stdin and returns normalized JSON on stdout.

For native Claude/Copilot runs, Sarathi now executes the provider from the workspace root and records native CLI metadata such as provider family, invocation kind, and workspace root inside persisted dispatch evidence/artifacts.

Those provider details also feed the bounded recovery loop: verify/review retries can now carry forward provider context plus a classified recovery reason such as `auth`, `provider_offline`, or `native_cli_failure`.

If a provider emits `review_trace` data inside dispatch evidence, Sarathi lifts that into persisted review findings with provider/file/line metadata and includes provider trace counts in review summaries.

If a provider emits `diff_trace` or `spec_trace` data, Sarathi also persists:

- exact diff hunks with provider/file/line/header/excerpt metadata
- acceptance-criterion references with `AC-*` IDs, criterion text, and code-region links

When structured `spec_trace` references are present, the review loop uses them to compute AC coverage precisely instead of marking every criterion covered just because some evidence exists.

Those structured references are now review-enforcing, not just informative:

- a failing provider `spec_reference` can reject the review
- an uncovered acceptance criterion can reject the review
- rejected units are requeued to `in_progress` so the orchestration loop can continue with clearer evidence

Provider `diff_trace` hunks can now also include:

- `category` such as `security`, `logic`, or `coverage`
- `confidence` as a numeric provider signal
- `suggestion` for the likely remediation

Sarathi persists those on the review findings and rolls them up into review metadata including diff blockers, average diff confidence, risk categories, and highlighted patch regions.

Sarathi now also clusters neighboring hunks in the same file/category into grouped patch regions and computes a final `review_confidence_verdict` plus explicit reasons such as blocker count or low average confidence. This makes the review output easier to scan than a flat list of hunk findings.

### 3.4 Workspace Repository Bootstrap

Workspace repository setup is intentionally two-step and approval-gated:

1. Preview the repository path to inspect Git state, detected languages/tools, and missing Sarathi bootstrap artifacts.
2. Attach the repository only after explicit approval.
3. Initialize the repository only after explicit approval; initialization creates only missing files and preserves existing repo-owned docs/policy files.

The current bootstrap creates or reconciles:

- `SARATHI.md`
- `wiki/README.md`, `wiki/architecture.md`, `wiki/development.md`
- `coding-standards.md`
- `guidelines.md`
- `learnings.md`
- the full canonical `policy-pack/` file set

### 3.4.1 Policy-Driven Cascade Scheduling

The service runtime can auto-start ready task-graph units when a workspace policy pack enables it:

```yaml
graph_execution:
  auto_schedule_ready_nodes: true
```

With that enabled:

1. approving the task graph gate immediately starts ready root units
2. completing a blocker automatically starts newly unblocked downstream units
3. manual scheduling remains available as an explicit fallback

### 3.3 Run a Task

```bash
# Basic run
sarathi run "Fix null pointer in user service" --policy-pack ./policy-pack

# Dry run (see phases without executing)
sarathi run "Add OAuth2" --policy-pack ./policy-pack --dry-run

# Override complexity
sarathi run "Refactor database layer" --complexity high --policy-pack ./policy-pack
```

### 3.4 Task Complexity

| Complexity | Indicators | Skips PlanningAdvisor |
|------------|------------|----------------------|
| Low | Bug fix, docs, single file | Yes |
| Medium | Multi-file, new feature | Yes |
| High | Architecture, security, multi-service | No |

---

## 4. Using as a Python API

### 4.1 Import the Engine

```python
from src.engine import Engine, TaskContext, Complexity, Phase
```

### 4.2 Run Task Programmatically

```python
from src.engine import Engine

engine = Engine(policy_pack_path="./policy-pack", enforce_preflight=True)

# Run a task
result = engine.run_task(
    description="Add user authentication",
    complexity=Complexity.MEDIUM
)

print(f"Task {result.task_id} completed at phase: {result.current_phase}")
```

### 4.3 Access Phase Results

```python
for phase_result in result.phase_results:
    print(f"{phase_result.phase.value}: {phase_result.outcome}")
    print(f"  Artifacts: {list(phase_result.artifacts.keys())}")
```

### 4.4 Check Task Status

```python
from src.engine import PersistenceManager

persistence = PersistenceManager()
task = persistence.load_task("task-id-123")

print(f"Current phase: {task.current_phase}")
print(f"Phase results: {len(task.phase_results)}")
print(f"Graph state: {task.task_graph_state}")
```

### 4.5 Resume Failed Task

```python
engine = Engine(policy_pack_path="./policy-pack")
engine.persistence = PersistenceManager()

task = engine.persistence.load_task("task-id-123")
result = engine.resume_task(task)
```

### 4.6 Agent Role Registry

```python
from src.runtime import list_agent_roles, get_agent_role

# List all roles
for role in list_agent_roles():
    print(f"{role.name}: {role.purpose}")

# Get specific role
planner = get_agent_role("planner")  # Returns Disha
```

---

## 5. Using with AI Agents

### 5.1 Attach Skill to Agent

Copy the repo's `skill/` folder to your agent's skills directory:

| Agent | Skill Location |
|-------|---------------|
| Cursor | `.cursor/skills/sarathi/` |
| Claude Code | `.claude/skills/sarathi/` |
| GitHub Copilot | `.copilot/skills/` |
| Codex CLI | `.codex/skills/sarathi/` |

### 5.2 GitHub Copilot Setup

```bash
ln -s "$(pwd)/skill" "$HOME/.copilot/skills/sarathi"
```

Then in your `AGENTS.md`:

```yaml
- name: sarathi
  description: "Sarathi workflow orchestration for complex development tasks."
  trigger:
    when: "the task requires structured planning, build, verify, review workflow"
  command: |
    cd Sarathi
    python3 -m pip install -e .
    sarathi run "{{task}}" --policy-pack ./policy-pack
```

### 5.3 Agent Prompt Integration

When your agent uses the skill, it should:
1. Read policy pack files for context
2. Follow the 12-phase lifecycle
3. Track phase outcomes
4. Persist artifacts under `.sarathi/tasks/`

---

## 6. Policy Pack Setup

### 6.1 Manual Policy Pack

Create `policy-pack/` with these files:

```bash
mkdir -p policy-pack
touch policy-pack/{complexity,conventions,commands,review,escalation,model-routing,skills,task-tracking}.md
```

### 6.2 Key Policy Files

**complexity.md** - Complexity triggers:
```markdown
# Complexity Triggers

## Low Complexity
- Single file change
- Bug fix with clear root cause

## Medium Complexity  
-Multiple files (2-10)
- New feature with clear scope

## High Complexity
- Cross-cutting concern
- Architectural change
```

**commands.md** - Build commands:
```markdown
# Build Commands

## Build
```bash
npm run build
```

## Test
```bash
npm test
```
```

**escalation.md** - Retry budgets:
```markdown
# Escalation Policy

## Verify Phase
- retry_budget: 3
- severity_threshold: major
- auto_fix_attempts: 2
```

### 6.3 Validate Your Pack

```bash
sarathi validate ./policy-pack --verbose
```

---

## 7. NCP Integration (optional)

Sarathi works fully without NCP. This section is for teams that want persistent cross-session memory, cross-agent context passing for dynamic workflow patterns, and pipeline cost tracking.

### 7.1 What is NCP?

NCP (Neural Context Protocol) is a **separate tool** — a sidecar process or server that Sarathi calls out to. It is not bundled with Sarathi. You must install it independently.

**Repository:** [kulkarni2u/neural-context-protocol](https://github.com/kulkarni2u/neural-context-protocol)

Without NCP, Sarathi uses native local adapters for context compilation, persistence, and artifact storage. These work for most tasks. NCP adds value when:

- Tasks span multiple sessions and agents need to remember prior findings
- You use dynamic workflow patterns (FANOUT, CLASSIFY, LOOP) and want branch agents to receive context from their parent automatically
- You want per-node token cost logged back to a central store

### 7.2 Checking NCP availability

```bash
# Check if ncp is on PATH
ncp --version

# Check whether Sarathi detects NCP in your project
sarathi run --dry-run "test" --policy-pack ./policy-pack
# Look for: "[ncp] NCP detected" or "[ncp] NCP not available"
```

If you see `[ncp] NCP not available, using native adapters` — Sarathi checked for `.ncp/run.py`
in your project root and didn't find it. That is fine; native adapters are used automatically.

### 7.3 Setting up NCP

Once `ncp` is on your PATH:

```bash
# 1. Bootstrap NCP into your project (creates .ncp/ directory)
sarathi init --ncp

# 2. Verify Sarathi detects it
sarathi run --dry-run "test" --policy-pack ./policy-pack
# Expect: "[ncp] NCP detected, using NCP adapters"

# 3. Run a task with NCP active (auto-detected, no flag needed)
sarathi run "Add authentication" --policy-pack ./policy-pack
```

To force NCP on or off regardless of auto-detect:

```bash
sarathi run --ncp "task"       # force NCP, fail if unavailable
sarathi run --no-ncp "task"    # force native adapters
```

### 7.4 NCP transport modes

| Mode | How it works | When to use |
|------|-------------|-------------|
| `direct` (default) | Sarathi forks `.ncp/run.py` as subprocess | Local dev, single machine |
| `mcp` | Sarathi sends JSON-RPC to an NCP HTTP server | Remote NCP server, team shared instance |

```bash
# MCP mode — NCP server must be running at the endpoint
sarathi run --ncp --ncp-mode mcp --ncp-endpoint http://ncp.internal:4242/mcp "task"
```

### 7.5 Dynamic workflow patterns without NCP

If you enable dynamic workflow patterns (`workflow-patterns.md`) but NCP is not active:

- FANOUT/CLASSIFY branch agents still execute, but receive no whisper context from the parent
- SYNTHESIZE nodes dispatch without pre-fetched branch outputs in their context
- LOOP_GATE iterations start without prior-iteration findings in memory
- Node outputs are not persisted across sessions

For single-session tasks this is usually acceptable. For long-running or multi-session workflows, NCP is strongly recommended when patterns are enabled.

---

## 8. Common Workflows

### 7.1 Bug Fix Workflow

```bash
# 1. Initialize (first time only)
sarathi init .

# 2. Run as low complexity
sarathi run "Fix null pointer in user service" \
  --policy-pack ./policy-pack \
  --complexity low

# 3. Check result
sarathi log <task-id>

# 4. If failed, resume
sarathi resume <task-id>
```

### 7.2 New Feature Workflow

```bash
# 1. Run as high complexity (gets PlanningAdvisor)
sarathi run "Add OAuth2 authentication" \
  --policy-pack ./policy-pack \
  --complexity high

# 2. Monitor status
sarathi status <task-id>

# 3. If paused for human input
sarathi resume <task-id>
```

### 7.3 Architecture Refactor

```bash
# 1. High complexity for full lifecycle
sarathi run "Refactor to microservices" \
  --policy-pack ./policy-pack \
  --complexity high

# 2. Review proposals from learnings
sarathi proposals

# 3. Monitor graph progress
sarathi status <task-id>
```

### 7.4 Policy Iteration

```bash
# 1. Edit policy pack
vim policy-pack/conventions.md

# 2. Validate changes
sarathi validate ./policy-pack --verbose

# 3. Run test task
sarathi run "Quick test" --policy-pack ./policy-pack --dry-run
```

---

## 9. Task Management

### 8.1 List All Tasks

```bash
sarathi list
```

Output:
```
Available tasks:
- task-20260424-001
- task-20260424-002
```

### 8.2 View Task Log

```bash
sarathi log <task-id>
```

Output:
```
Task: task-20260424-001
Phase Results:
------------------------------------------------------------
Phase              Agent       Outcome  Iterations Evidence
Route              Marga       pass     0          complexity=medium
Brainstorm         Vichara     pass     0          evidence=0.95
Plan               Disha       pass     0          checkpoints=5
Build              Pravaha     pass     1          
Verify             Nirnaya     pass     0          
Review             Nirnaya     pass     0          
```

### 8.3 Check Task Status

```bash
sarathi status <task-id>
```

Output:
```
Task: task-20260424-001
Complexity: medium
Current Phase: Review
Task Graph: 3 completed, 2 pending, 5 total
Next Node: verify-config - Verify config files
Last Completed Node: build-core (attempts: 1)
```

### 8.4 Resume Paused Task

```bash
sarathi resume <task-id>
```

### 8.5 View Policy Proposals

```bash
sarathi proposals
```

Output:
```
Policy Proposals: 2
- Add verify failure recovery guidance -> commands.md
  Confidence: 0.70
  Rationale: Verify recorded 3 repeated failure signal(s).
```

---

## 10. Troubleshooting

### 10.1 "Command not found: sarathi"

```bash
# Reinstall
python3 -m pip install -e /path/to/Sarathi

# Or use module directly
python3 -m src.cli --help
```

### 10.2 "No policy pack found"

```bash
# Initialize first
sarathi init .

# Or specify path
sarathi run "Task" --policy-pack ./policy-pack
```

### 10.3 Validation fails

```bash
# Check with verbose
sarathi validate ./policy-pack --verbose

# Common issues:
# - Missing required policy files
# - Invalid YAML syntax
# - Missing required sections
```

### 10.4 Task hangs at a phase

```bash
# Check status
sarathi status <task-id>

# Resume with new attempt
sarathi resume <task-id>
```

### 10.5 Python API ImportError

```bash
# Use virtual environment
source .venv/bin/activate

# Or add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:/path/to/Sarathi/src"
```

### 10.6 "[ncp] NCP not available, using native adapters"

This message means Sarathi checked for `.ncp/run.py` and didn't find it. **This is not an error** — Sarathi automatically falls back to native adapters.

If you want NCP:
```bash
# 1. Install NCP from https://github.com/kulkarni2u/neural-context-protocol
ncp --version   # verify it's on your PATH

# 2. Bootstrap NCP into your project
sarathi init --ncp

# 3. Re-run — Sarathi should now detect .ncp/run.py automatically
```

If you don't need NCP, suppress the message:
```bash
sarathi run --no-ncp "task"
```

### 10.7 "NCP get_context failed" or "NCP write_memory failed"

NCP is installed but failing. Diagnose:
```bash
# Check NCP server status
.ncp/run.py status

# Test a direct NCP call
.ncp/run.py get_context '{"agent_id":"s.test","role":"test","owns":[],"must_not":[],"task":"ping","slot":"Build","intent":"ping"}'
```

Common causes:
- NCP process crashed — restart it
- Permissions on `.ncp/run.py` — needs execute bit: `chmod +x .ncp/run.py`
- MCP mode but server not running — start the NCP MCP server first

Sarathi will fall back to native adapters automatically if NCP errors occur mid-run, but the `compilation.ncp_fallback: true` flag will appear in the context pack summary for affected nodes.

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `sarathi init <path>` | Initialize policy pack |
| `sarathi init <path> --ncp` | Initialize with NCP (requires `ncp` on PATH) |
| `sarathi validate <path>` | Validate policy pack |
| `sarathi run "task" --policy-pack <path>` | Run a task (NCP auto-detected) |
| `sarathi run "task" --ncp` | Force NCP on (fails if unavailable) |
| `sarathi run "task" --no-ncp` | Force native adapters |
| `sarathi list` | List saved tasks |
| `sarathi log <id>` | Show task log |
| `sarathi status <id>` | Show task status |
| `sarathi resume <id>` | Resume a task |
| `sarathi proposals` | Show policy proposals |
| `sarathi agents` | List agent roles |

---

## Agent Role Names (Sanskrit)

| Role | Name | Purpose |
|------|------|---------|
| Orchestrator | Sarathi | Main controller |
| Planner | Disha | Planning phase |
| Researcher | Vichara | Brainstorm phase |
| Executor | Pravaha | Build phase |
| Reviewer | Nirnaya | Verify/Review |
| Router | Marga | Route phase |

---

## Support

- **Issues:** https://github.com/kulkarni2u/Sarathi/issues
- **Docs:** See `README.md` and `DESIGN.md`
- **Skill:** See `skill/SKILL.md`
