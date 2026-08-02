# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,tui,mcp]"       # dev + optional extras
                                      # NCP (cross-session memory) ships as a core dependency — no extra needed
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

Sarathi dispatches to native CLI providers: `claude`, `codex`, `gh copilot`, `opencode`. No SDK imports — all dispatch goes through subprocess bridges. Provider health tracking in `src/runtime/provider_health.py`. The MCP server (`src/mcp_server.py`) exposes Sarathi itself as an MCP tool for agent platforms. `_HarnessAwareDispatcher` (`src/engine.py`) threads each provider's own session-resume id (`claude_session_id`, `codex_session_id`, `opencode_session_id` — looked up from the provider registry's `session_constraint_key`) across phases within a task, so repeated dispatches to the same provider resume its session instead of replaying the full context pack from scratch.

### Quality Signals (measured, not asserted)

`test_pass_rate`, `blast_radius`, `accuracy`, `token_cost`, `latency_ms`, `rollback_triggered` — all measured from real phase outcomes and stored in the harness outcome. The learn-evolve loop in `src/evolve.py` generates policy proposals when signals deviate >10% from per-task-class baselines.

### TUI (`src/tui.py`, `src/tui_data.py`)

Built with Textual. Chat-first layout with a toggleable task panel. Entry point: `sarathi tui`. The `src/tui_data.py` holds data models that bridge the engine's SQLite state to the Textual reactive layer.

### Service Layer (`src/service/`)

HTTP service for workspace management, multi-worker scheduling, and policy proposal handling. Entry point: `sarathi-desktop`. `app.py` (~1.9K lines) is the ServiceApp router and is where most new workspace HTTP/service features land; `src/storage/__init__.py` (~2.6K lines) is actually the largest file in the repo, holding SQLite storage primitives and schema migrations.

### Repo Index (`src/repo_index/`)

Offline, IDE-style symbol index persisted under `.sarathi/index` (`symbols.json` + `manifest.json`), built/refreshed via `sarathi index` or automatically during `sarathi init`. Python files are parsed with `ast`; other languages use best-effort regex extraction. Incremental — only files whose (mtime, size) changed are reparsed. `ContextCompiler` (`src/runtime/context.py`) consults it through an optional `repo_index_root` argument, appending ranked `file:line symbol (kind)` hints to `relevant_files` so a dispatched agent can jump straight to likely-relevant code instead of re-discovering it with Glob/Grep every phase — a direct token-spend lever, since re-exploration is otherwise repeated per phase per graph node.

### NCP Adapter (`src/ncp_adapter/`)

Integration with Neural Context Protocol for cross-session context and memory. `neural-context-protocol` is a core dependency (installed with the base package) and ships its own `ncp` CLI on PATH. `sarathi init` bootstraps `.ncp/` **by default** (pass `--no-ncp` to opt out); a missing `ncp` binary degrades to a warning rather than failing init, since Sarathi's own sidecar files (`config.toml`, `run.py`) come from bundled templates independent of the CLI. Once `.ncp/config.toml` + an executable `.ncp/run.py` exist, `Engine` auto-detects and activates NCP adapters at runtime (`--no-ncp` on `sarathi run`, or a workspace's stored `ncp_enabled: false` metadata, force it back off). Bounding is what makes this a token-spend lever, not just a memory feature: `NCPContextAdapter` (`src/ncp_adapter/context_adapter.py`) returns bounded pidgin-format context chunks (`max_chunk_tokens = 400` in Sarathi's default config override) plus targeted whispers between graph nodes, instead of each phase/node replaying full context. `src/runtime/providers/cli_bridge.py`'s NCP handoff path (`_run_ncp_handoff_dispatch`) measures and reports the resulting token savings per dispatch. The `trust_gate.py` arbitrates which context sources are trusted when NCP is active, and degrades gracefully (PASS with a warning) if NCP is unreachable.

## Key Invariants

- **Engine is domain-agnostic**: Never put project-specific logic in `src/engine.py`, `src/phases/`, or `src/runtime/`. It belongs in a policy pack.
- **Harness first**: Any new phase or dispatch path must compile a `HarnessConfig` before running.
- **Measured quality**: Quality gates check stored harness outcomes, not inline assertions.
- **Policy-driven recovery**: Failure classification and retry guidance come from policy, not hardcoded conditionals in `src/runtime/recovery.py`.
