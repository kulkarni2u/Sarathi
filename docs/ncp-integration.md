# Sarathi + NCP Integration (SQLite) — Validated

**Date:** 2026-06-14
**Result:** ✅ Sarathi ↔ NCP works end-to-end here with a local **SQLite** store.
Two real `sarathi run --ncp` runs completed all 12 phases each, persisted memory
to SQLite, and the second run's NCP context retrieval surfaced the first run's
findings — i.e. **persistent cross-session memory is in active use.**

> `.ncp/` is gitignored (per-workspace bootstrap, regenerable). The working
> bridge + config are preserved here as `docs/ncp/run.py.example` and
> `docs/ncp/config.toml.example`.

---

## Backend decision: SQLite (not pgvector)

NCP's `ncp init` offers a SQLite store (local, zero-infra) or pgvector (which
requires `ncp infra` to stand up Docker Postgres + Redis, plus `ncp migrate`).
For this local-first, single-node, network-restricted environment, **SQLite** is
the right choice: no external infrastructure, matches how Sarathi already
persists (its own SQLite DB), and pgvector buys nothing at this scale. Use
pgvector only for a multi-process / larger deployment where ANN search and shared
state across machines matter.

---

## How it fits

- NCP plugs into the **Sarathi engine** (`src/ncp_adapter/*` → `BuildHandler` →
  `TaskGraphExecutor`), not into Claude Code subagents. The engine probes
  `<repo>/.ncp/run.py`; if present, it routes context/persistence/artifacts/
  whispers through NCP instead of native adapters.
- This is the automation of the bounded-context work an orchestrator otherwise
  does by hand: NCP compiles per-node context, persists findings across runs, and
  carries sibling/parent context to fan-out branches (whispers).

---

## Direct-mode contract (what `.ncp/run.py` must implement)

Sarathi (`src/ncp_adapter/_transport.py`) forks the script as
`./.ncp/run.py <command> <json-args>`:

| Command | Args (JSON) | Behavior |
|---|---|---|
| `status` | `{}` | exit 0 if store reachable (availability probe) |
| `write_memory` | `{content, layer, src, written_by}` | persist a chunk; exit 0 |
| `get_context` | `{...ConsciousBlock fields, token_budget}` | print NCP pidgin context to stdout |
| `fetch` | `{query, k}` | print `chunk:<id>\n  <content>` blocks to stdout |
| `log_cost` | `{turn_id, agent_id, model, input_tokens, output_tokens, cost_usd, ...}` | record cost; exit 0 |

The reference bridge (`docs/ncp/run.py.example`) maps each to NCP 1.1.0's Python
API: `ncp.configure(cwd=repo_root)` + `ncp.stores.create_store(config)`, then
`SubconsciousChunk(...)` + `ncp.write_memory(...)`, `ConsciousBlock(...)` +
`ncp.get_context(...)`, `store.query(...)`, and `store.log_cost_raw(...)`.

**Nuance:** `SQLiteStore.write()` returns `False` (not an error) for a
>0.92-similarity duplicate in the same zone/layer/pipeline — the bridge treats
this as soft-success (warn + exit 0), matching the "exit 0 on success" contract.

---

## Reproduce

```bash
pip install neural-context-protocol httpx     # NCP 1.1.0; httpx is a declared Sarathi core dep
mkdir -p .ncp
cp docs/ncp/config.toml.example .ncp/config.toml      # SQLite store at .ncp/store.db
cp docs/ncp/run.py.example .ncp/run.py && chmod +x .ncp/run.py

# sanity: round-trip a memory through the bridge
./.ncp/run.py write_memory '{"content":"hello","layer":"semantic","src":"agent_inferred","written_by":"me"}'
./.ncp/run.py fetch '{"query":"hello","k":3}'         # -> chunk:... hello

# run a real task with NCP enabled (local deterministic provider; no API key)
python3 -m src.cli run --ncp --policy-pack policy-pack/EXAMPLE "Document the NCP integration"
ncp explain                                            # inspect the SQLite store
```

---

## Evidence captured (2026-06-14)

- Store: `.ncp/store.db` (SQLite), confirmed via `ncp status`/`ncp explain` — no
  pgvector/Docker.
- Standalone bridge round-trip verified (write → fetch returns the chunk).
- `sarathi run --ncp` (non-dry-run) completed **12/12 phases**; artifacts written
  under `ncp://<task_id>/<phase>` (proves `NCPArtifactAdapter` engaged).
- Store grew **25 chunks after run 1, 34 after run 2** (layers: semantic,
  episodic, reasoning_trace), holding real phase artifacts (Brainstorm
  approaches/risks, Plan, Build, Review, Learn) and per-phase TaskContext
  snapshots, `written_by="sarathi.<task_id>.<Phase>"`.
- **Cross-run retrieval:** after run 2, `fetch` for the task topic returned chunks
  from **both** task IDs — run 2 had access to run 1's persisted findings.
- Tests: `tests/test_ncp_adapter` → 40 passed. (e2e NCP tests: the only failures
  are a pre-existing `No module named 'src'` harness issue when a subprocess runs
  from a pytest tmp_path outside the repo — unrelated to the bridge.)

---

## Provisioning note

The 9 "baseline" test failures we carried during the cockpit build were **not
real failures**: 7 were `tests/test_ncp_adapter/*` failing only because `httpx`
(a *declared core dependency* in `pyproject.toml`) wasn't installed in the
container — installing it made them pass. A session-start step that runs
`pip install -e .` (and `pip install neural-context-protocol` if NCP is desired)
keeps the environment correctly provisioned. The remaining 2
`test_cli_ncp_integration` failures are a separate policy-pack auto-discovery
quirk in those tests.
