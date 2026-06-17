# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,tui,mcp]"       # dev + optional extras
pip install -e ".[ncp]"               # optional: cross-session memory
```

## Commands

```bash
# Tests
pytest -q                             # all tests
pytest tests/test_engine.py -v        # single file
SARATHI_LIVE_TESTS=1 pytest tests/live -q   # live provider smoke tests (real API calls)

# Code quality
black src/ tests/
mypy src/ tests/

# CLI (after install)
sarathi --help
sarathi validate ./policy-pack/EXAMPLE --verbose
sarathi run "task description" --policy-pack ./policy-pack/EXAMPLE --dry-run
sarathi tui
sarathi-mcp                           # starts MCP stdio server
```

## Architecture

Sarathi is a **policy-backed workflow orchestration framework** for AI-assisted software delivery. The engine defines *how* to deliver (fixed phase lifecycle); domain knowledge lives entirely in **policy pack** markdown files, not in engine code.

### Core Concept: HarnessConfig

Before any model call, `src/harness.py` compiles a `HarnessConfig` that pre-declares the execution contract: context scope, permissions, assigned agent, quality targets, and budget. This "declare before dispatch" pattern is the central design invariant.

### 12-Phase Lifecycle (fixed order, policy-auditable)

```
ROUTE → BRAINSTORM → PLANNING_ADVISOR → PLAN → BUILD → VERIFY
      → REVIEW → TASK_TRACKING → RISK_CHECK → ELEGANCE → PHASE_LOG → LEARN
```

Each phase is a module under `src/phases/`. The engine in `src/engine.py` drives them sequentially; phases can override `next_phase` or set `pause_execution`. PLANNING_ADVISOR only runs for HIGH complexity tasks. All phase results are stored in SQLite (`.sarathi/sarathi.db`).

### Policy Packs

All domain-specific behavior lives in `policy-pack/<NAME>/`:
- `complexity.md` — rule-based + historical complexity classification
- `commands.md` — build/test/debug commands the engine runs
- `model-routing.md` — complexity-to-provider/model mapping
- `review.md` — review criteria and evidence requirements
- `escalation.md` — budget and severity thresholds
- `workflow-patterns.md` — enabled graph patterns (FANOUT, JUDGE loops, etc.)
- `permissions.md` — provider tool allowlists

The engine never hardcodes project-specific behavior. If you need to change how tasks are classified, reviewed, or built — edit the policy pack, not the engine.

### Task Classification (`src/task_class.py`)

12 classes organized into families: `QUERY`, `ANALYSIS`; `CODEGEN_*`; `MUTATION_*`; `ORCHESTRATION_*`; `EVOLUTION_*`. Classification drives harness rebuild mode: MUTATION/* and EVOLUTION/* always rebuild (DEEP), others use FAST/STANDARD cache.

### Graph Execution (`src/task_graph.py`, `src/runtime/graph_executor.py`)

Tasks can be broken into a DAG with node types: `CLASSIFY`, `FANOUT`, `SYNTHESIZE`, `JUDGE`, `EXECUTE`, `LOOP_GATE`. The graph executor in `src/runtime/` handles parallel fanout, synthesis, and adversarial JUDGE loops. Patterns are enabled per-policy-pack via `workflow-patterns.md`.

### Provider Bridges (`src/dispatch.py`, `src/runtime/contracts.py`)

Sarathi dispatches to native CLI providers: `claude`, `codex`, `gh copilot`, `opencode`. No SDK imports — all dispatch goes through subprocess bridges. Provider health tracking in `src/runtime/provider_health.py`. The MCP server (`src/mcp_server.py`) exposes Sarathi itself as an MCP tool for agent platforms.

### Quality Signals (measured, not asserted)

`test_pass_rate`, `blast_radius`, `accuracy`, `token_cost`, `latency_ms`, `rollback_triggered` — all measured from real phase outcomes and stored in the harness outcome. The learn-evolve loop in `src/evolve.py` generates policy proposals when signals deviate >10% from per-task-class baselines.

### TUI (`src/tui.py`, `src/tui_data.py`)

Built with Textual. Chat-first layout with a toggleable task panel. Entry point: `sarathi tui`. The `src/tui_data.py` holds data models that bridge the engine's SQLite state to the Textual reactive layer.

### Service Layer (`src/service/`)

HTTP service for workspace management, multi-worker scheduling, and policy proposal handling. Entry point: `sarathi-desktop`. The `app.py` is the largest file (~55K lines); most new workspace features land here.

### NCP Adapter (`src/ncp_adapter/`)

Optional integration with Neural Context Protocol for cross-session context and memory. Gated behind the `[ncp]` extra. The `trust_gate.py` arbitrates which context sources are trusted when NCP is active.

## Key Invariants

- **Engine is domain-agnostic**: Never put project-specific logic in `src/engine.py`, `src/phases/`, or `src/runtime/`. It belongs in a policy pack.
- **Harness first**: Any new phase or dispatch path must compile a `HarnessConfig` before running.
- **Measured quality**: Quality gates check stored harness outcomes, not inline assertions.
- **Policy-driven recovery**: Failure classification and retry guidance come from policy, not hardcoded conditionals in `src/runtime/recovery.py`.
