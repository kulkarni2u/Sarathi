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

`test_pass_rate`, `blast_radius`, `accuracy`, `token_cost`, `latency_ms`, `rollback_triggered` — all measured from real phase outcomes and stored in the harness outcome. The learn-evolve loop in `src/evolve.py` generates policy proposals when signals deviate >10% from per-task-class baselines. A baseline is the mean of the last `baseline_window` (20) values per task class and signal, persisted in `<state dir>/.sarathi/evolve_baselines.json` (LearnHandler's `state_dir`, the engine's provider-health directory) so it survives across `sarathi run` processes; deviation is relative to the baseline's magnitude (`delta / max(|baseline|, 1)`, so rates compare absolutely and token/latency counts as a fraction), and `token_cost`, `latency*`, `blast_radius`, `rollback_triggered` count a rise as degradation. Window, `baseline_min_samples` and `failure_outcomes` (phase outcomes that make a task a failure for NCP feedback and the post-accept check; default `fail`, `escalate`) live in `escalation.md`'s `learn_evolve` block.

### TUI (`src/tui.py`, `src/tui_data.py`)

Built with Textual. Chat-first layout with a toggleable task panel. Entry point: `sarathi tui`. The `src/tui_data.py` holds data models that bridge the engine's SQLite state to the Textual reactive layer.

### Service Layer (`src/service/`)

HTTP service for workspace management, multi-worker scheduling, and policy proposal handling. Entry point: `sarathi-desktop`. `app.py` (~1.9K lines) is the ServiceApp router and is where most new workspace HTTP/service features land; `src/storage/__init__.py` (~2.6K lines) is actually the largest file in the repo, holding SQLite storage primitives and schema migrations.

### Repo Index (`src/repo_index/`)

Offline, IDE-style symbol index persisted under `.sarathi/index` (`symbols.json` + `manifest.json`), built/refreshed via `sarathi index` or automatically during `sarathi init`. Python files are parsed with `ast`; other languages use best-effort regex extraction. Incremental — only files whose (mtime, size) changed are reparsed. `ContextCompiler` (`src/runtime/context.py`) consults it through an optional `repo_index_root` argument, appending ranked `file:line symbol (kind)` hints to `relevant_files` so a dispatched agent can jump straight to likely-relevant code instead of re-discovering it with Glob/Grep every phase — a direct token-spend lever, since re-exploration is otherwise repeated per phase per graph node.

### NCP Adapter (`src/ncp_adapter/`)

Integration with Neural Context Protocol for cross-session context and memory. `neural-context-protocol` is a core dependency (installed with the base package) and ships its own `ncp` CLI on PATH. `sarathi init` bootstraps `.ncp/` **by default** (pass `--no-ncp` to opt out); a missing `ncp` binary degrades to a warning rather than failing init, since Sarathi's own sidecar files (`config.toml`, `run.py`) come from bundled templates independent of the CLI. Once `.ncp/config.toml` + an executable `.ncp/run.py` exist, `Engine` auto-detects and activates NCP adapters at runtime (`--no-ncp` on `sarathi run`, or a workspace's stored `ncp_enabled: false` metadata, force it back off). Bounding is what makes this a token-spend lever, not just a memory feature: `NCPContextAdapter` (`src/ncp_adapter/context_adapter.py`) returns pidgin-format context bounded by NCP's `[budget] context_token_budget` plus targeted whispers between graph nodes, instead of each phase/node replaying full context. NCP has no per-chunk size setting (`max_chunk_tokens` was never read and was removed in NCP 1.9.6). `sarathi init` writes its NCP overrides (`[pipeline] default_ttl_hours = 168`, `[tools] profile = "standard"`) into the right TOML tables via `_apply_ncp_config_overrides` (`src/cli.py`); `ncp doctor` must report no unknown keys. `src/runtime/providers/cli_bridge.py`'s NCP handoff path (`_run_ncp_handoff_dispatch`) emits a `share` whisper whose payload must validate as NCP's `HandoffPayload` JSON (`ask`, `slice`, `files`), runs `ncp handoff <provider> --return full` (NCP ≥ 1.9.6 otherwise returns a ≤2,000-char summary), and measures and reports the resulting token savings per dispatch. Outcome feedback (`src/ncp_adapter/outcome.py`): an `NCPOutcomeLedger` shared by every NCP adapter collects the chunk ids a task read (`fetch`/`get_context`) and wrote (Sarathi names chunks itself and credits a write only when the bridge prints `written:<id>` or MCP returns `written: true`); LEARN passes the measured `HarnessOutcome` to `NCPOutcomeReporter`, which calls `record_outcome` crediting those chunks, so NCP recalibrates their trust. Success/weight come only from measured data (`derive_ncp_outcome`): any phase ending in a `failure_outcomes` outcome (default `fail` or `escalate`), a rollback or a failed VERIFY command is a failure; a real VERIFY command makes it `eval_source: verifier` at weight 1.0, otherwise `self_report` at 0.5. It never fails LEARN. The direct bridge (`docs/ncp/run.py.example`, `SARATHI_NCP_BRIDGE_VERSION = 4`) runs NCP's feedback calibration itself after `record_outcome`, since only NCP's MCP handler does that automatically; `sarathi init` upgrades an older Sarathi-generated bridge (backup in `run.py.bak`). Improvement records (`src/ncp_adapter/improvement.py`, direct mode only): `NCPImprovementTracker` files each LEARN proposal as an NCP improvement attempt (kind `manual`, problem = proposal title, scope = policy file; a recurring proposal reuses its open attempt) and annotates the proposal artifact with the problem's prior attempts; `ProposalReviewStore` accept/reject/rollback (`src/evolve.py`, `_record_ncp_decision`) set the attempt's status. Its post-accept check compares the weighted success rate of the proposal's task class before vs after acceptance from `.sarathi/ncp_outcomes.jsonl` (thresholds `post_accept_min_outcomes`/`post_accept_gate_ratio` in `escalation.md`'s `learn_evolve`), writes observed numbers to the attempt, and reports regressions with a rollback command — it never rolls back by itself. State lives under `<policy pack parent>/.sarathi/` (`ncp_improvements.json`), the same root `ProposalReviewStore` uses. NCP's `ncp refine` gate is deliberately not used: it judges shorter rewrites of one procedure chunk, not notes appended to policy files. Bridge version 3 adds `improvement_record`/`improvement_update`. Graph-node signals (`src/ncp_adapter/whisper_router.py`, bridge version 4 `emit_whisper`/`peek_whispers`/`ack_whispers`): FANOUT/CLASSIFY/JUDGE context is a real NCP `nudge` whisper (Sarathi's kind is the payload's `kind`) targeted at `s.<node_id>` inside pipeline `sarathi_<task_id>` (`pipeline_for_task`; node ids like `n1-branch-1` repeat across tasks). A node reads only whispers queued for it in its task's pipeline (`NCPContextAdapter._fetch_node_whispers`, never a memory search — that used to hand every branch other tasks' signals and unrelated memory), the executor tracks whispered targets so non-branch targets such as a JUDGE's `-winner` node read theirs, and whispers are acknowledged only after the node's dispatch succeeds (a retry sees them again). MCP mode emits whispers but does not read them back (NCP's MCP surface returns payloads only in `ncp_get_context`'s display block). NCP's task ledger and push wake-ups are not used: graph nodes run in DAG order in one process (nothing polls), and the service has its own SQLite scheduler. In MCP mode, cost goes through `ncp_post_turn` with empty `ack_whisper_ids`/`retrieved_chunk_ids` (NCP has no `ncp_log_cost`, and omitting those lists would acknowledge the session's pending whispers), and `ncp_fetch`/`ncp_get_context` results are decoded from their JSON envelopes (`result` / `context`). The `trust_gate.py` arbitrates which context sources are trusted when NCP is active, and degrades gracefully (PASS with a warning) if NCP is unreachable.

## Key Invariants

- **Engine is domain-agnostic**: Never put project-specific logic in `src/engine.py`, `src/phases/`, or `src/runtime/`. It belongs in a policy pack.
- **Harness first**: Any new phase or dispatch path must compile a `HarnessConfig` before running.
- **Measured quality**: Quality gates check stored harness outcomes, not inline assertions.
- **Policy-driven recovery**: Failure classification and retry guidance come from policy, not hardcoded conditionals in `src/runtime/recovery.py`.
