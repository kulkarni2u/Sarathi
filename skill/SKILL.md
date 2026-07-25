---
name: sarathi
description: "Generic workflow orchestration framework - policy-backed lifecycle (Route → Brainstorm → Plan → Build → Verify → Review → etc.) with sub-agent dispatch, learn-evolve loop, and model selection. Use when building complex tasks that need systematic execution."
---

# Sarathi - Workflow Orchestration Framework

A generic, tool-agnostic workflow orchestration framework for AI agents. Defines a canonical delivery model that policy-backed workflows inherit.

## Use anywhere (Cursor · Claude · Copilot · Codex · OpenCode)

1. **Install the CLI** (same on every machine): from the Sarathi repo run `python3 -m pip install -e .` or install a built wheel. This gives you `sarathi init`, `validate`, `run`, `list`, and `log`.
2. **Start the local service** — no token needed for local connections:
   ```bash
   python3 -m src.service --db ~/.sarathi/sarathi.db --port 8765
   ```
   The service writes `~/.sarathi/service.json` on start. No token configuration required for local connections.
3. **Attach this skill to your agent**: copy this folder (or symlink it) into the skills directory your product expects, then invoke the skill when you want the Sarathi lifecycle.
   - **Cursor**: project `.cursor/skills/sarathi/SKILL.md` (or your global skills path).
   - **Claude Code / Claude plugins**: project `.claude/skills/sarathi/SKILL.md` or `~/.claude/skills/…`.
   - **GitHub Copilot (agent mode)**: merge the workflow into repo `AGENTS.md` / agent instructions, or your org's skill bundle location. Use this repo's `skill/SKILL.md` as the Copilot skill entry and register the agent in this repo's `AGENTS.md` for repo-local discovery.
   - **OpenAI Codex CLI**: `~/.codex/skills/sarathi/SKILL.md` or workspace `.codex/skills/sarathi/SKILL.md`.
   - **OpenCode**: `~/.opencode/skills/sarathi/SKILL.md` or workspace `.opencode/skills/sarathi/SKILL.md`.

### Session-start auto-detection hook

Sarathi ships an optional session-start hook, modeled after Superpowers, for
agent hosts that support startup hooks or plugins.

- Claude/Copilot/Codex-style hosts can use `hooks/hooks.json`, which invokes
  `hooks/run-hook.cmd session-start`.
- Cursor-style hosts can use `hooks/hooks-cursor.json`.
- OpenCode can load `.opencode/plugins/sarathi.js`.

The hook walks upward from the session workspace and activates only when it
finds `policy-pack/`, `.sarathi/`, or `SARATHI.md`. When no Sarathi marker is
found, it returns an empty JSON object and injects nothing. When a marker is
found, it adds this Sarathi skill content to session context so the agent starts
aware of the Sarathi lifecycle and workspace policy pack.

The hook is context-only. It does not create files, start services, or mutate
the repository just because an agent session opened.

The hook resolves its own install location and includes it in the injected
context (as `Sarathi skill files live at: <path>`), so relative references
from this file — such as `skills/build-tdd.md` — resolve correctly no
matter where the skill was installed (repo-local, `~/.claude/skills/`, a
Cursor global path, etc.).

## GitHub Copilot integration

To add Sarathi to Copilot agent mode:
1. Install Sarathi from the `Sarathi/` folder in the environment Copilot uses.
2. Copy or symlink the whole `skill/` folder (not just `SKILL.md` — the phase
   detail files under `skill/skills/` are loaded on demand and must ship
   alongside it) into your Copilot skills directory, shared skill bundle, or
   global Copilot skills directory.
   - For repo-local use: place the skill under the repo's Copilot skills path.
   - For org-wide use: add the skill to your shared agent bundle.
   - For global Copilot use: symlink or copy `skill/` into your global Copilot skills directory.
3. Register the Sarathi agent in `AGENTS.md` using the repo-local entry or your Copilot agent registry.

Use `--ncp` when the task would benefit from NCP-backed context management.

### Global Copilot install example

```bash
git clone https://github.com/kulkarni2u/Sarathi.git
cd Sarathi
python3 -m pip install -e .
# symlink skill/ into your global Copilot skills directory
ln -s "$(pwd)/skill" "$HOME/.copilot/skills/sarathi"
```

Example agent entry
```yaml
- name: sarathi
  description: "Sarathi workflow orchestration for complex development tasks."
  trigger:
    when: "the task requires a structured planning, build, verify, review, and learn workflow"
  command: |
    cd /path/to/Sarathi
    sarathi run "{{task_description}}" --policy-pack ./policy-pack --dry-run [--ncp] [--ncp-mode direct|mcp] [--ncp-router]
```

3. **Know the split**: `sarathi run` drives the **orchestration graph**, persists tasks under `.sarathi/tasks/`, and emits phase artifacts. Phases whose artifacts include `"execution_surface": "host_agent"` are **checklists for the model in the IDE**—they are not hidden subprocesses. Optional live test execution: set `SARATHI_EXEC_COMMANDS=1` (see Sarathi `README.md`).
4. **Policy source of truth**: keep a single `policy-pack/` per repo (from `sarathi init .`). The duplicate `policy-pack/` in this skill folder is a **template** only; prefer the pack Sarathi generated in your project.

## When to Use

Use `/sarathi` when:
- Building features that need systematic execution
- Tasks require complex multi-phase workflows
- Need sub-agent orchestration with explore/execute dispatch
- Want learn-evolve to improve over time
- Need policy-driven complexity routing

## Quick Start

```bash
# Initialize a new project with policy pack
sarathi init ./my-project

# Validate existing policy pack
sarathi validate ./my-project/policy-pack

# Run a task through the lifecycle
sarathi run "Add user authentication" --policy-pack ./my-project/policy-pack

# Dry run to see phases without executing
sarathi run "Add user authentication" --policy-pack ./my-project/policy-pack --dry-run

# Specify complexity override
sarathi run "Fix critical bug" --policy-pack ./policy-pack --complexity high
```

## The 12-Phase Lifecycle

| Phase | Purpose | Gate | Skipped for |
|-------|---------|------|-------------|
| Route | Classify complexity (Low/Medium/High) | - | - |
| Brainstorm | Provider-driven dialogue → approved spec with self-review | Hard gate: spec approved | - |
| PlanningAdvisor | High-complexity only | - | LOW, MEDIUM |
| Plan | TDD-structured checkpoint list, no placeholders | 90% confidence | - |
| Build | TDD iron law: test-first, red-green-refactor | Hard TDD default | - |
| Verify | Auto-fix loop with systematic debugging escalation | Budget+severity | - |
| Review | Two-stage: spec compliance then code quality | 5-round hard stop (Stage 2) | - |
| TaskTracking | Blocked sub-agent protocol | Non-blocking siblings | - |
| RiskCheck | Devil's advocate | Non-blocking | - |
| Elegance | Pre-build clean | Auto-fix attempt | - |
| PhaseLog | Audit trail | Tabular | - |
| Learn | Post-flight introspection | >= 80% + >= best | - |

## Complexity Classification

### Low Complexity
- Single file change
- Bug fix with clear root cause
- Documentation update
- Simple refactor (rename, reformat)
- **Skips**: PlanningAdvisor phase

### Medium Complexity
- Multiple files (2-10)
- New feature with clear scope
- Dependency update
- **Skips**: PlanningAdvisor phase

### High Complexity
- Cross-cutting concern
- Architectural change
- Security-sensitive code
- Performance-critical code
- **Full lifecycle**: All phases executed

## Sub-Agent Dispatch

**Explore mode** (Brainstorm, PlanningAdvisor, RiskCheck):
- Mentor/apprentice model
- Rich Q&A interface
- Persistent context
- Can push clarifying questions back

**Execute mode** (Plan, Build, Verify, Review):
- Task-framing model
- Structured task objects (id, inputs, outputs, contextRef)
- Stateless-ish, returns artifacts
- Clear contracts

## Agent Role Names

Sarathi uses a concise Sanskrit-inspired naming system for agent roles and orchestration concepts:

| Role | Name |
|------|------|
| Orchestrator | Sarathi |
| Planner | Disha |
| Researcher | Vichara |
| Reasoner | Prajna |
| Executor | Pravaha |
| Reviewer/validator | Nirnaya |
| Coordinator | Samanvaya |
| Support | Sahayaka |
| Router | Marga |
| Workflow spine/message bus | Sutra |

## Policy Pack

Sarathi is driven by policy packs in the workspace:

```
policy-pack/
├── complexity.md      # Complexity triggers
├── conventions.md    # Coding standards + evidence requirements
├── commands.md       # Build/test commands
├── review.md         # Review criteria
├── escalation.md     # Budget + severity thresholds
├── model-routing.md  # Model selection
├── skills.md         # Skill routing
└── task-tracking.md  # Task manifest
```

### Initialize Policy Pack

```bash
sarathi init ./my-project
```

This creates a `policy-pack/` directory with template files for all required policies.

## Phase Log Format

CLI and JSON persistence use machine outcomes: `pass`, `skip`, `fail`, `escalate`. In prose you can describe those as "completed" when `pass` or non-blocking `escalate`.

```
| Phase              | Outcome (engine) | Iterations |
|--------------------|------------------|------------|
| Route              | pass             | 0          |
| Brainstorm         | pass             | 0          |
| Plan               | pass             | 0          |
| Build              | pass             | 0          |
| Verify             | pass             | 0          |
| Review             | pass             | 0          |
| TaskTracking       | pass             | 0          |
| RiskCheck          | pass             | 0          |
| Elegance           | pass             | 0          |
| PhaseLog           | pass             | 0          |
| Learn              | pass             | 0          |
```

## Phase Details

Each phase's full process, evidence weights, and gate criteria live in their
own file under `skills/`, loaded only when you're in that phase — read the
one you need rather than all of them upfront:

| Phase | Detail file |
|-------|-------------|
| Brainstorm | `skills/brainstorm.md` — dialogue process, spec self-review, evidence dimensions |
| Plan | `skills/plan.md` — checkpoint format, no-placeholders policy, plan gate |
| Build | `skills/build-tdd.md` — TDD iron law, red-green-refactor cycle |
| Verify | `skills/verify.md` — debugging escalation, verification-before-claiming-pass |
| Review | `skills/review-phase.md` — two-stage spec-compliance + quality gate |
| Provider dispatch | `skills/provider-contracts.md` — `brainstorm_turn` / `explore` / `execute` payload shapes |
| NCP handoff | `skills/ncp-handoff.md` — phase read/write contract, subagent dispatch protocol |

These paths are relative to the skill's own root (see "Session-start
auto-detection hook" above for how that resolves); with native skill loading
(Claude Code, Cursor) read them directly by path when you reach that phase.

## Error Handling

### Phase Fails
- Log failure in phase log
- Move to Learn phase
- Document failure patterns for evolution

### Review Hard Stop (after 5 rounds on Stage 2)
Post-hard-stop options presented to user:
1. **force_approve** - Accept current state
2. **request_changes** - Iterate with specific feedback
3. **abort** - Abandon task
4. **delegate_to_agent** - Let AI resolve remaining issues

### Task Blocked
Non-blocking siblings continue; blocked task presents options:
- Wait for block
- Skip task
- Substitute alternative
- Continue anyway

### Confidence Gate Not Met
- Log evidence gap
- Retry phase with guidance
- Escalate if repeated failures

## Learn-Evolve Loop

After every task:
1. Document patterns in `learnings.md`
2. skill-evolve detects recurring patterns
3. High-confidence evolutions auto-apply
4. Regression gate: >= 80% pass rate AND >= best seen

## Example Usage

### Example 1: Simple Bug Fix
```bash
sarathi run "Fix null pointer exception in user service" \
  --policy-pack ./my-project/policy-pack \
  --complexity low
```

Expected phases (LOW complexity):
1. Route
2. Brainstorm (+ spec self-review)
3. Plan (TDD-structured, no placeholders)
4. Build (TDD iron law)
5. Verify (with debugging escalation)
6. Review (two-stage)
7. TaskTracking
8. RiskCheck
9. Elegance
10. PhaseLog
11. Learn
*(PlanningAdvisor skipped)*

### Example 2: New Feature
```bash
sarathi run "Add OAuth2 authentication" \
  --policy-pack ./my-project/policy-pack \
  --complexity high
```

Expected phases (HIGH complexity):
1. Route
2. Brainstorm (+ spec self-review)
3. PlanningAdvisor *(executed for high)*
4. Plan (TDD-structured, no placeholders)
5. Build (TDD iron law)
6. Verify (with debugging escalation)
7. Review (two-stage)
8. TaskTracking
9. RiskCheck
10. Elegance
11. PhaseLog
12. Learn

### Example 3: Validate Policy Pack
```bash
# Quick check
sarathi validate ./my-project/policy-pack

# Detailed output
sarathi validate ./my-project/policy-pack --verbose
```

Output:
```
Summary: 8 PASS, 0 DRIFT, 2 TODO

Detailed Results:
------------------------------------------------------------
  ✓ [PASS] Route: complexity_triggers
      → complexity.md
  ✓ [PASS] Route: classification_thresholds
      → complexity.md
  ...
  ✗ [TODO] Learn: evolution_threshold
      → Not provided
```

## Key Principles

1. **Engine has zero domain knowledge** - Policy packs provide WHAT
2. **Sub-agent first** - Main thread available for communication
3. **Never skip build/test/review loops** - Even under pressure
4. **Non-blocking siblings** - Parallel tasks continue while one waits
5. **Evidence-weighted gates** - Explicit evidence, not subjective confidence
6. **Policy drives routing** - Complexity, skip, model selection
7. **Test-first always** - No production code without a failing test first
8. **Root cause before fix** - Never apply a 4th fix without root cause investigation
9. **Spec compliance before quality** - Review Stage 1 must pass before Stage 2 starts
10. **NCP as context spine** - Every subagent reads and writes NCP at turn boundaries
