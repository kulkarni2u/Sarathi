# Sarathi + NCP: Experience Report & Follow-up Proposals

**Date:** 2026-06-15
**Scope:** Reflections from integrating the [Neural Context Protocol](https://pypi.org/project/neural-context-protocol/)
(NCP) into Sarathi's engine (`src/ncp_adapter/*`), validating it end-to-end with a
local SQLite store (`docs/ncp-integration.md`), and building on top of it through
M1–M5 of `docs/IMPLEMENTATION_PLAN.md` (whisper-routed FANOUT, session forking,
recipe packs). This is a retrospective, written to capture what to keep doing and
what to fix — the proposals at the end are scoped for a **future session**, not
this one.

---

## 1. The good

### 1.1 The adapter seam is the right abstraction
`src/ncp_adapter/__init__.py` gives the engine four narrow adapters
(`NCPContextAdapter`, `NCPPersistenceAdapter`, `NCPArtifactAdapter`,
`NCPWhisperRouter`) behind a single `NCPAdapterConfig`. The engine probes
`<repo>/.ncp/run.py` and, if present, swaps native context/persistence/artifact
behavior for NCP-backed behavior with no changes to `TaskGraphExecutor` call
sites beyond constructor wiring. This made every downstream feature (whispers,
session forking, recipes) composable on top without re-litigating "how do we talk
to NCP."

### 1.2 SQLite-first was the right call
Choosing SQLite over pgvector (`docs/ncp-integration.md` §"Backend decision") kept
the integration zero-infrastructure: no Docker, no `ncp infra`/`ncp migrate` step,
and it mirrors how Sarathi already persists its own state. For a local-first,
single-node tool this was clearly correct and avoided weeks of infra yak-shaving.

### 1.3 The direct-mode bridge contract is small and testable
The `.ncp/run.py <command> <json-args>` contract (`status`, `write_memory`,
`get_context`, `fetch`, `log_cost`) is five verbs, each independently
scriptable and testable via subprocess. `tests/test_ncp_adapter/` (40/40 passing)
cover each adapter against a fake bridge without needing a real NCP install for
unit tests — only the e2e/CLI integration tests need the real package.

### 1.4 End-to-end validation produced real evidence, not just green tests
`docs/ncp-integration.md` records actual runs: 12/12 phases completed with `--ncp`,
the SQLite store grew from 25 → 34 chunks across two runs, and **cross-run
retrieval worked** — run 2's `fetch` returned chunks written by run 1. That's the
core NCP value proposition (persistent cross-session memory) demonstrated with
real data, not mocked.

### 1.5 Whisper routing is already wired into the graph executor
`src/runtime/graph_executor.py` calls `_ncp_emit_fanout_whispers`,
`_ncp_emit_judge_whisper`, and `_ncp_emit_classify_whisper` at the natural points
in FANOUT/JUDGE/CLASSIFY execution, each guarded by `if self.ncp_whisper_router is
None: return` so the feature is fully optional and degrades to a no-op without
NCP. `tests/test_ncp_adapter/test_whisper_router.py` covers the router itself.

### 1.6 Graceful, auto-detecting defaults
The `--ncp` / `--no-ncp` CLI flags plus auto-detect-with-fallback
(`c7d2e70`, `d708e36`) mean a workspace with no `.ncp/` directory behaves exactly
as before — NCP is additive. The workspace `ncp_enabled` metadata + Settings UI
toggle (`6fbe1f1`, `686ce75`, `d568777`) extends this to the web UI without forcing
every workspace to opt in.

### 1.7 Session forking got a warm-start for free
T4.2 (`d9ca5c6`, "session forking with NCP warm-start seed") shows the adapter
abstraction paying compounding dividends — a feature built two milestones later
could reuse `NCPPersistenceAdapter` to seed a forked session's context without any
new transport code.

### 1.8 Honest documentation of caveats
`docs/ncp-integration.md` doesn't hide the rough edges: it explicitly calls out
the `SQLiteStore.write()` returns-`False`-on-duplicate nuance (handled as soft
success) and the `httpx` provisioning issue (below). That made this retrospective
much faster to write — the "bad" list below is mostly a continuation of notes
already started there.

---

## 2. The bad / friction points

### 2.1 `httpx` is a "declared but not always installed" dependency
`docs/ncp-integration.md` §"Provisioning note" records that 7 of the 9
baseline-failure tests during the cockpit build were `tests/test_ncp_adapter/*`
failing purely because `httpx` (declared in `pyproject.toml`) wasn't actually
installed in the container. This is a recurring tax: every fresh environment needs
`pip install -e .` to actually pick up `httpx`, and if that step is skipped the
failure signature ("40 NCP adapter tests fail") looks like a real regression and
costs investigation time to rule out.

### 2.2 Two CLI/e2e NCP tests fail for a mundane reason, every time
Confirmed again this session:
```
FAILED tests/test_cli_ncp_integration.py::test_cli_run_ncp_dry_run
FAILED tests/test_cli_ncp_integration.py::test_cli_run_without_ncp_uses_native_adapters
FAILED tests/test_e2e_ncp_integration.py::test_e2e_ncp_init_creates_dot_ncp
FAILED tests/test_e2e_ncp_integration.py::test_e2e_ncp_init_sarathi_optimized_config
FAILED tests/test_e2e_ncp_integration.py::test_e2e_ncp_auto_detect_uses_ncp_when_available
FAILED tests/test_e2e_ncp_integration.py::test_e2e_ncp_explicit_flag
FAILED tests/test_e2e_ncp_integration.py::test_e2e_ncp_opt_out_flag
```
The actual error is:
```
/usr/local/bin/python: Error while finding module specification for 'src.cli'
(ModuleNotFoundError: No module named 'src')
```
These tests `subprocess.run([sys.executable, "-m", "src.cli", ...], cwd=str(tmp_path))`
— running `python -m src.cli` from a `tmp_path` that has no `src` package on its
`sys.path`. This isn't an NCP bug or a "policy-pack auto-discovery quirk" (the
earlier docs' working theory) — it's a module-resolution issue in the test harness
itself. It's been a stable "7 pre-existing failures" baseline for multiple
sessions, which is fine for now, but it means **this corner of NCP CLI behavior has
zero CI coverage** despite looking covered.

### 2.3 The working bridge is a "copy these example files" ritual
`docs/ncp-integration.md`'s "Reproduce" section requires:
```bash
pip install neural-context-protocol httpx
mkdir -p .ncp
cp docs/ncp/config.toml.example .ncp/config.toml
cp docs/ncp/run.py.example .ncp/run.py && chmod +x .ncp/run.py
```
`.ncp/` is gitignored by design (it's per-workspace, regenerable), but there's no
`sarathi` command that performs this scaffolding — a new workspace that wants NCP
has to know these four manual steps exist and find them in a markdown doc. The
auto-detect default (2.6 above) means a workspace silently runs *without* NCP
until someone does this ritual, with no in-product nudge.

### 2.4 NCP provenance is invisible in the web UI
T5.4 (this session) built the Knowledge Center's **Context Inspector**, which
shows selected/omitted sources and token posture for a context bundle — but that
view has no way to indicate *which* of those sources came from NCP's
`get_context`/`fetch` versus native adapters, or to show the SQLite store's size,
chunk count, or last-write time. When NCP is enabled, its main visible effect
(cross-run memory) is currently undiscoverable from the UI — you'd have to run
`ncp explain` from a shell.

### 2.5 Whisper routing has no recipe-level story yet
T5.3 (this session) shipped FANOUT-across-providers recipes
(`policy-pack/RECIPES/orchestrator`, `.../debate`) with `pattern_config.providers`
round-robin. The graph executor already emits fanout/judge/classify whispers when
`ncp_whisper_router` is set (§1.5), but the recipes don't document or test the
combination — "does a FANOUT branch on `provider-b` actually receive the sibling
context whisper emitted from a branch dispatched to `provider-a`?" is plausible by
construction but unverified end-to-end.

### 2.6 Documentation is spread across four places
NCP material currently lives in `docs/ncp-integration.md`,
`docs/ncp/*.example`, `docs/orchestration-learnings.md` (the "How this validates
Sarathi + NCP" section), and scattered docstrings in `src/ncp_adapter/__init__.py`.
There's no single index a new contributor would land on first.

---

## 3. Proposals for a future session

These are intentionally **not implemented now** — they're scoped for a follow-up.

1. **Fix the module-resolution bug in `test_cli_ncp_integration.py` /
   `test_e2e_ncp_integration.py`** (§2.2). Likely fix: pass
   `env={**os.environ, "PYTHONPATH": str(REPO_ROOT)}` (or run via
   `sys.executable, "-c", "import sys; sys.path.insert(0, ...)"`, or invoke the
   installed `sarathi` console script instead of `-m src.cli`) so these 7 tests
   actually exercise the CLI's NCP flag handling. This would shrink the "known
   failures" baseline from 7 to 0 and give real coverage to `--ncp`/`--no-ncp`.

2. **Add a `sarathi ncp init` (or `sarathi init --ncp`) scaffolding command** that
   performs the four-step ritual in §2.3 programmatically: `pip`-check for
   `neural-context-protocol`, create `.ncp/`, copy/render
   `config.toml.example`/`run.py.example` from package data, `chmod +x`. Pair with
   a one-line note in the Settings NCP toggle UI ("not yet configured — run
   `sarathi ncp init`") so the auto-detect default (§2.3) is discoverable rather
   than silent.

3. **Surface NCP provenance + store health in the Knowledge Center / Context
   Inspector (T5.4 follow-up)**. Extend the context-bundle data the inspector
   already renders with an `ncp` block: store backend, chunk count, last write
   timestamp, and per-source `origin: "ncp" | "native"` tagging so users can see
   cross-run memory working from the UI, closing the gap from §2.4.

4. **End-to-end test for whisper-routed FANOUT across providers** (§2.5): a test
   that runs the `orchestrator` recipe with `NCPWhisperRouter` wired to a fake
   bridge, and asserts that a branch dispatched to `provider-b` received a
   `fanout_context` whisper emitted on behalf of `provider-a`'s branch — proving
   T5.3 (provider fan-out) and the whisper router (§1.5) compose correctly.

5. **Consolidate NCP docs into one entry point** (§2.6): make
   `docs/ncp-integration.md` the index, with `docs/ncp/*.example` and the
   "How this validates Sarathi + NCP" section of `docs/orchestration-learnings.md`
   linked from it (or merged in), so a new contributor has one starting page.

6. **Document the pgvector migration path** (mentioned but not detailed in
   `docs/ncp-integration.md`): a short "when to switch from SQLite to pgvector and
   how" section for users who outgrow single-node/local usage — even a stub
   pointing at `ncp infra`/`ncp migrate` with the prerequisites would close an open
   question raised at integration time.

7. **Add a session-start provisioning check** (§2.1): a `scripts/` or `make`
   target (or a `pytest` collection-time check with a clear skip message) that
   verifies `httpx` and, optionally, `neural-context-protocol` are installed before
   running the NCP test suites — turning "40 tests mysteriously fail" into a single
   actionable message.
