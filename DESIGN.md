# Sarathi - Design Specification

**Version:** 0.1.0
**Date:** 2026-04-14
**Status:** Draft

---

## Overview

Sarathi is a generic, tool-agnostic workflow orchestration framework for AI-powered development agents. It defines a canonical delivery model that any policy-backed workflow inherits, enabling portable, high-quality agent harness across OpenCode, Claude, Copilot, Cursor, and future platforms.

**Core Philosophy:**
- Engine has zero domain knowledge - defines HOW to deliver, not what to build
- Policy packs supply all domain-specific behavior
- Learn-evolve loop makes the system operationally expert over time

---

## Architecture

### Engine Core

The engine is delivered as:
- `workflow.md` - canonical phase lifecycle with gates
- `required-list.md` - contract specifying required policy inputs per phase
- `config.md` - engine configuration

The engine is reusable across all domains. Zero domain knowledge.

### Policy Pack

A directory of markdown files, each named by concern:

| File | Purpose |
|------|---------|
| `complexity.md` | Complexity triggers and classification rules |
| `conventions.md` | Coding standards, style guides |
| `commands.md` | Build, test, and debug commands |
| `review.md` | Review criteria, evidence requirements |
| `escalation.md` | Budget and severity thresholds |
| `model-routing.md` | Complexity-to-model mapping table |
| `skills.md` | Skill registry and routing rules |
| `task-tracking.md` | Task tracking configuration |
| `permissions.md` | Provider tool allowlists; `sarathi init` writes these as native config files |
| `learnings.md` | Project-specific learnings (per-workspace) |

### Learn-Evolve Loop

Hybrid propagation model:

**Per-workspace:**
- Each project has its own `learnings.md`
- Tracks patterns, failures, validated approaches with confidence ratings
- Pass rates stored as weighted rolling averages

**Global:**
- Central `evolve-baseline.md` accumulates global best across projects
- Aggregates smoothed trends, not raw peaks

**Regression gate (for skill evolution):**
- Local trend >= local best
- AND global trend >= global best
- >= 80% pass rate

---

## Lifecycle Phases

### Phase 1: Route

**Purpose:** Classify task complexity (Low / Medium / High)

**Method:** Hybrid rule-based + historical comparison
- Policy defines complexity triggers (file count, change scope, risk indicators)
- Historical comparison handles edge cases (compares to past tasks in learnings.md)
- Rules catch obvious cases; history handles nuanced ones

**Outputs:**
- Complexity classification
- Route-to-phase mapping

### Phase 2: Brainstorm

**Purpose:** Exploration and confidence building before commitment

**Method:** Explore dispatch (mentor/apprentice model)
- Rich Q&A interface with sub-agent
- Sub-agent has persistent context, can push clarifying questions

**Gate:** Evidence-weighted confidence (90% required)
- Policy defines required evidence types per gate
- Agent provides evidence from each category:

```
Evidence types (updated weights for quality):
  - problem_understanding: 0.25 (clear problem statement + context)
  - alternative_approaches_considered: 0.25 (3+ approaches with pros/cons)
  - technical_feasibility: 0.15 (constraints, dependencies assessment)
  - risks_identified: 0.15 (impact/severity + mitigation strategies)
  - success_criteria_defined: 0.10 (measurable acceptance criteria)
  - reversibility_assessed: 0.10 (rollback plan + impact assessment)
```

**Quality Controls:**
- 10-point quality checklist covering scope, stakeholders, constraints, alternatives, risks
- Anti-pattern detection: solution jumping, feature creep, over-engineering, groupthink
- Structured 6-section template for comprehensive analysis
- Model selection: Claude 3.5 Sonnet for Medium/High complexity (was Haiku)
- Extended time budget: 15 minutes (was 10) for deeper analysis

**Outputs:**
- Confidence score
- Evidence package

### Phase 3: Planning Advisor (High Complexity Only)

**Purpose:** Additional planning scaffolding for high-complexity tasks

**Trigger:** Route phase classifies as High complexity

**Method:** Interactive advisory loop
- Main thread probes for gaps
- Sub-agent provides recommendations
- Policy defines advisor depth

### Phase 4: Plan

**Purpose:** Establish execution roadmap with checkpoints

**Method:** Execute dispatch (task-framing model)
- Structured task objects with clear inputs/outputs
- Checkpoint list with dependencies

**Gate:** Evidence-weighted confidence (90% required)
- Required evidence: checkpoint list, dependency map, rollback plan

**Outputs:**
- Checkpoint list
- Dependency manifest (cross-phase dependencies declared)
- Rollback plan

### Phase 5: Build

**Purpose:** Implementation with TDD discipline

**Method:** Execute dispatch per checkpoint
- Hard TDD by default (red-green-refactor strictly enforced)
- Policy can override to soft TDD with justification recording
- Parallel sub-agents for independent checkpoints

**Pre-build gate:** Elegance check
- Auto-fix attempt on style/convention violations
- Blocks only if auto-fix fails

**Outputs:**
- Implementation artifacts
- Test suite

### Phase 6: Verify

**Purpose:** Build/test/debug loop with auto-recovery

**Method:** Auto-fix loop with escalation bounds
- Escalation model: Budget + Severity hybrid
  - Budget for recoverable errors (policy-defined retry counts)
  - Severity for blockers (major issues escalate immediately)
- Evidence artifacts generated per iteration

**Escalation bounds:**
- Policy defines budget (token/time) and severity thresholds
- Major severity breaches trigger immediate escalation
- Minor errors exhaust budget before escalation

**Outputs:**
- Verified artifacts
- Evidence package

### Phase 7: Review

**Purpose:** Per-unit parallel spec compliance and code review

**Method:** Parallel sub-agents per unit
- Spec compliance review
- Code quality review
- 5-round hard stop

**Post-hard-stop behavior:** Non-blocking escalation bundle
- Generates evidence package (review artifacts, failed assertions, code diffs, context)
- Presents options menu: force-approve | request-changes | abort | delegate-to-agent
- Task waits (blocking), sibling tasks continue (non-blocking)
- Structured summary for human decision

**Outputs:**
- Review verdict
- Escalation bundle (if applicable)

### Phase 8: Task Tracking

**Purpose:** Task model management with blocked sub-agent protocol

**Method:** Task manifest with cross-phase dependency awareness

**Blocked sub-agent protocol:** C+D hybrid
- Sub-agent signals blocked with context and options
- Main thread marks task "pending-unblock"
- Presents options to user (non-blocking): wait | skip | substitute | continue-anyway
- Background process attempts unblock via most-likely path
- Sibling tasks continue
- Timeout auto-proceeds with best-guess option
- If background unblock fails after N retries, escalate to blocking human decision

**Outputs:**
- Updated task manifest
- Block resolution decision

### Phase 9: Risk Check

**Purpose:** Non-blocking risk assessment

**Method:** Devil's advocate dispatch
- Flags concerns
- Does NOT block

**Outputs:**
- Risk flag report

### Phase 10: Elegance

**Purpose:** Pre-build clean code checks

**Method:** Auto-fix attempt
- Runs before build loop entry
- Policy defines elegance criteria

**Outputs:**
- Cleaned artifacts (if fixable)
- Block report (if unfixable)

### Phase 11: Phase Log

**Purpose:** Audit trail for phase transitions

**Format:** Minimal tabular

| Timestamp | From | To | Outcome | Iter | Key Decisions |
|-----------|------|----|---------|------|---------------|
| 2026-04-14 09:15:32 | Route | Brainstorm | pass | - | complexity=medium, skip_planning_advisor=true |
| 2026-04-14 09:22:48 | Build | Verify | fail | 3 | test_suite=2/5, auto_fix=attempted, escalation=bounds_exceeded |

**Verbosity:** Minimal by default (timestamp, phase, outcome, decisions)
- Policy can adjust verbosity level

### Phase 12: Learn

**Purpose:** Post-flight introspection and policy hardening

**Method:** Multi-step loop
1. Task completes (fires end of every task regardless of complexity)
2. Learnings.md documents patterns, failures, missed edge cases, validated approaches with confidence ratings
3. skill-evolve detects recurring patterns across learnings.md
4. High-confidence evolutions auto-apply to policy
5. Policy references tighten

**Outputs:**
- Updated learnings.md
- Policy updates (auto-applied or flagged for review)
- Skill creation (if missing skill detected)

---

## Sub-Agent Dispatch Model

### Dual Dispatch: Explore vs Execute

**Explore mode** (mentor/apprentice):
- Rich Q&A interface
- Persistent context
- Can push clarifying questions back to main
- Used for: Brainstorm, Planning Advisor, Risk Check

**Execute mode** (task-framing):
- Structured task objects: id, description, inputs, expectedOutputs, contextRef, escalationPolicy
- Stateless-ish, returns artifacts
- Clear contracts for input/output
- Used for: Plan, Build, Verify, Review

---

## Model Selection

Hybrid approach (B + C + D + policy-driven routing):

| Input | Source | Description |
|-------|--------|-------------|
| Effort Bucket | B | quick_fix / medium_effort / major_undertaking |
| Token Budget | C | estimated tokens for task completion |
| Time Budget | C | allowed elapsed time before timeout |
| Complexity Score | D | composite: uncertainty × scope × risk |
| Model Routing | Policy (A) | maps (bucket + budgets + score) → model selection |

Engine computes B/C/D inputs. Policy defines the routing table.

---

## Policy Validation (`--init`)

### Dual-Source Truth

1. Engine generates expected `core-policy-interface-mapping.md`
2. Policy pack includes its claimed mapping
3. `--init` diffs them and reports:
   - PASS: claimed satisfies expected
   - DRIFT: mismatch between claimed and expected
   - TODO: missing required inputs

### `--init` Flow

1. **Inspect:** Scan target repo(s), detect language/framework/build tools, devil's advocate on ambiguity
2. **Interview:** Ask only high-value questions (policy keys, task tracking, domain constraints)
3. **Generate:** Create policy-pack withdevil's advocate fill for most questions
4. **Validate:** Run dual-source comparison, report PASS/DRIFT/TODO
5. **Evolve:** learning loop + skill-evolve runs after every task completion

---

## Skill Routing

### Hybrid Registry + Discovery

**Registry:**
- Policy defines skill families and routing rules

**Discovery:**
- Engine scans workspace for skills at startup
- Routes based on what it finds

**Creation:**
- If no skill exists for needed capability, skill-evolve generates one
- New skill baked into policy-pack
- Future tasks route to it

---

## File Structure

```
Sarathi/
├── engine/
│   ├── workflow.md          # Canonical phase lifecycle
│   ├── required-list.md     # Required policy inputs per phase
│   └── config.md            # Engine configuration
├── policy-pack/             # Domain-specific policies
│   ├── complexity.md
│   ├── conventions.md
│   ├── commands.md
│   ├── review.md
│   ├── escalation.md
│   ├── model-routing.md
│   ├── skills.md
│   ├── task-tracking.md
│   └── permissions.md
├── docs/
│   └── specs/
│       └── 2026-04-14-sarathi-design.md
└── learnings/              # Evolved over time
    ├── evolve-baseline.md   # Global best
    └── [workspace-specific]/
        └── learnings.md
```

---

## Dynamic Workflow Patterns

Sarathi supports six Anthropic-inspired dynamic workflow patterns where the task
graph changes shape at runtime based on agent outputs, rather than being fixed at
plan time.

### Node types

| NodeType | Role |
|----------|------|
| `execute` | Default: single work unit dispatched to a provider |
| `fanout` | Spawns N parallel `execute` branches + a `synthesize` fan-in node |
| `synthesize` | Merges outputs from N upstream branches into one result |
| `judge` | Evaluates competing outputs and injects a `winner` execute node |
| `loop_gate` | Re-runs until a condition key is falsy or max iterations is reached |
| `classify` | Reads a classification output and injects the matching branch node |

### Graph mutation

`inject_nodes(graph, parent_id, new_nodes)` is a pure function that appends nodes
to a live graph and updates the parent's `injected_children` list. All pattern
injection runs through this function in `_post_execute_inject`, called after every
successful node completion in `TaskGraphExecutor`.

### Policy gate

`WorkflowPatternsPolicy` (parsed from `policy-pack/workflow-patterns.md`) gates
whether each pattern is allowed to inject at runtime. If no policy is set, all
patterns run. This lets teams disable specific patterns in production without
removing node declarations from the graph.

---

## NCP Integration

NCP (Neural Context Protocol) is an optional sidecar that replaces Sarathi's
native context compilation, persistence, and artifact storage with persistent,
cross-session NCP-backed services.

**Package:** `pip install neural-context-protocol` (or `pip install sarathi[ncp]`)
**Repo:** https://github.com/kulkarni2u/neural-context-protocol

### Transport

Two modes, configured via `--ncp-mode`:

| Mode | Mechanism |
|------|-----------|
| `direct` | Sarathi forks `.ncp/run.py` as a subprocess |
| `mcp` | Sarathi sends JSON-RPC to an NCP HTTP server via `httpx` |

`NCPTransportMixin` provides the shared `_call_write_memory`, `_call_fetch`,
`_call_get_context`, and `_call_log_cost` transport primitives. All NCP adapter
classes inherit from it.

### Adapter roles

| Adapter | Replaces | NCP primitive used |
|---------|----------|--------------------|
| `NCPContextAdapter` | `ContextCompiler` | `get_context`, `fetch` |
| `NCPArtifactAdapter` | `ArtifactStore` | `write_memory` (semantic layer) |
| `NCPPersistenceAdapter` | `PersistenceManager` | `write_memory` (episodic layer) |
| `NCPWhisperRouter` | — (new capability) | `emit` whispers |

### NCP + dynamic workflow patterns

The two subsystems are designed to work together:

- After each node completes, `_ncp_post_node_complete` writes its outputs to NCP
  semantic memory under the key `sarathi_node:{id}`.
- When a `synthesize` or `judge` node is dispatched, `compile_typed_node_context`
  fetches each source/competitor node's saved output and injects it into
  `prior_findings`.
- After a `fanout` or `classify` node completes, whispers are emitted to each
  branch agent (`fanout_context` / `classify_context` / `judge_context`) so they
  know their role in the broader workflow.
- `loop_gate` nodes write iteration findings to NCP episodic memory
  (`sarathi_loop:{parent_id}`) so the next iteration starts with prior context.

### Auto-detection

`Engine.__init__` probes for `.ncp/run.py` at startup. If found, all four NCP
adapters are instantiated and wired into `BuildHandler` → `TaskGraphExecutor`.
If not found, native adapters are used with no change to behaviour. The
`--ncp` / `--no-ncp` CLI flags override auto-detection.

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sub-agent model | A + B hybrid | Task-framing for predictable, mentor/apprentice for exploration |
| Policy structure | File-based, markdown-native | Accessible, human-editable, no special tooling |
| Learn propagation | Global + per-workspace hybrid | Knowledge compounds, local overrides prevent weirdness |
| Phase sequencing | Strict linear with policy-gated skipping | Auditability + flexibility |
| Parallelization | Phase-gated parallel | Within phase parallel, between phases sequential |
| Model selection | B+C+D + policy-driven | Captures effort, budget, and complexity scoring |
| Policy validation | Dual-source truth (C) | Explicit drift detection, not implicit |
| Elegance check | Auto-fix attempt (C) | Tries to clean, blocks only if fails |
| Blocked sub-agent | C+D hybrid | Options menu + background unblock, non-blocking for siblings |
| Skill routing | Registry + discovery + creation | Structure with flexibility, missing skills get created |
| Complexity routing | Rules + history (D) | Rules catch obvious, history handles edge cases |
| Confidence gates | Evidence-weighted (D) | Traceable, policy-weighted, explicit evidence checklist |
| Escalation model | Budget + severity (D) | Predictable for normal cases, adaptive for complex ones |
| TDD discipline | Hard by default, policy overridable | Quality default, flexibility justified |
| Phase log | Minimal tabular | Lightweight but reconstructable |
| Dynamic workflow | Runtime graph mutation via inject_nodes | Graph shape driven by agent outputs, not fixed at plan time |
| NCP integration | Sidecar, not embedded | Any NCP implementation works; zero import coupling |
| Pattern context | NCP fetch on typed nodes only | Avoids NCP roundtrips for plain execute nodes |
| Pattern policy gate | WorkflowPatternsPolicy at runtime | Disable patterns in production without touching graph declarations |
| Provider permissions | Policy-declared, written at init | No runtime bypass flags; explicit allowlist per provider, auditable in policy-pack |