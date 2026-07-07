# Sarathi Implementation Plan — Dogfood Edition

**Context:** This plan sequences the findings from the platform review for a
local, single-developer dogfood setup where **OpenCode and Codex are the
primary providers** (Claude available but not the main player). That context
reorders priorities: gaps that only affect Claude polish drop; gaps that make
codex/opencode second-class citizens become blockers, because the dogfood
loop cannot generate honest quality signals if its main providers run
degraded.

Each item lists the finding it addresses, the files involved, acceptance
criteria, and a size (S ≈ hours, M ≈ 1–3 days, L ≈ 1–2 weeks).

**Status legend:** ☐ open · ☑ done

- ☑ Slack channel notifications (shipped: `src/notifications.py`, both
  execution paths, policy-gated via `notifications.md`)
- ☑ 0.1 Session resume for codex/opencode (`codex exec resume <id>`,
  `opencode --session <id>`, per-provider session tracking in the TUI)
- ☑ 0.2 Streaming for codex/opencode in TUI chat (`codex exec --json`
  JSONL deltas; opencode incremental stdout; dispatch-table refactor)
- ☑ 0.3 Real live tests for codex/opencode (assert dispatch, usage,
  permission writes, structured failure; still skip without CLIs)
- ☑ 0.4 Cross-provider cost model (`pricing:` in model-routing.md,
  `src/runtime/pricing.py`, `UsageRecord.cost_usd` at the dispatcher)
- ☑ 0.5 Auth detection (`codex login status` / `opencode auth list`
  probes; `auth: ok|needs_auth|unknown` + actionable degraded_reason)

> Phase 0 caveat: resume/streaming argv shapes follow documented CLI
> syntax and are unit-tested against fake CLIs; validate once against
> your locally installed codex/opencode versions
> (`SARATHI_LIVE_TESTS=1 pytest tests/live -q`).

- ☑ 1.1 Escalation approval on CLI (`sarathi approve`), TUI (`a` key),
  MCP (`approve_task`); resume gated on approval-flavored pauses only
- ☑ 1.2 Health-gated failover (calendar-decayed health scores, latency
  EWMA, health-ordered fallbacks, dispatch-level transient failover)
- ☑ 1.3 SSE end-to-end (web cockpit EventSource with polling fallback;
  `sarathi watch --follow` streams lifecycle events with Last-Event-ID)
- ☑ 1.4-A Dual-write (`src/engine_mirror.py`): engine runs mirrored into
  sarathi.db and visible through the web cockpit API when the DB exists
- ☑ 1.4-B Unified proposals (`src/proposal_sync.py` + migration 011):
  SQLite `proposal_decisions` + lifecycle events mirror every surface's
  accept/reject; JSON stays authoritative for the policy compiler
- 1.4-C (CLI/TUI as full service clients) remains open — see Phase 1
  section below.
- ☑ 2.2 Git worktree isolation per graph branch (`src/runtime/isolation.py`,
  `HarnessConfig.isolation_mode`; contributed via codex/opencode dogfood)
- ☑ 2.1 Bakeoff recipe (`policy-pack/RECIPES/bakeoff/`): codex vs opencode
  candidates in isolated worktrees with judged merge (`--recipe bakeoff`)
- ☑ 2.3 Measured JUDGE (`src/runtime/judge_scoring.py`): policy-driven
  scorecards from recorded evidence (cost/latency/blast-radius/test rate),
  `.sarathi/bakeoff_history.json` winner recording, and evolve proposals
  targeting model-routing.md at ≥5 wins / ≥70% win rate per task class
- ☑ 3.1 Declarative provider registry (`src/runtime/providers/registry.py`):
  one `NativeProviderSpec` per provider; dispatch, permissions, preflight,
  auth probes, TUI chat/streaming, and fallback order all registry-driven;
  fifth-provider proof test registers a provider via one spec
- ☑ 3.4 Copilot resolved: explicitly experimental — `gh copilot` has no
  non-interactive permission surface; reason recorded in the spec and
  surfaced as the service catalog's degraded_reason
- ☑ 3.5 Web cockpit JS tests: Vitest wired into vite.config.ts; 51 unit
  tests over the SSE/polling transport and API client
- ☑ 3.7 (part 1) `sarathi init --from <dir|recipe|git-url>` imports shared
  policy packs with default gap-filling and --force protection

---

## Phase 0 — Make codex/opencode first-class (dogfood blockers)

The review found streaming, session resume, and real cost capture are
**Claude-only**. Dogfooding on codex/opencode without these means every run
is batch-blind, forgetful, and unpriced.

### 0.1 Session resume for codex and opencode — **M**

*Finding:* only `claude` supports `--resume`; codex/opencode dispatches are
stateless (`cli_bridge.py:254-256` vs nothing for the others).

- Codex: capture the session id from `codex exec` output (newer CLIs emit it;
  `codex exec resume <SESSION_ID>` / `--last` resumes). Store it in dispatch
  artifacts as `codex_session_id`, thread it back through
  `request.constraints` the same way `claude_session_id` flows today.
- OpenCode: the bridge already passes `-c` (continue-last); switch to
  targeted resume with `--session <id>` when a stored `opencode_session_id`
  exists.
- **Verify flags against the installed CLI versions first** (`codex --help`,
  `opencode run --help`) — resume syntax has shifted between releases.

Files: `src/runtime/providers/cli_bridge.py` (`_run_codex`, `_run_opencode`,
envelope parsing), `src/tui_data.py` (session tracking currently
claude-only at :236, :374), `tests/test_provider_dispatch.py`.

Accept: a TUI chat or engine run with codex/opencode carries context across
two dispatches; session ids visible in dispatch artifacts.

### 0.2 Streaming for codex and opencode — **M**

*Finding:* streaming exists only for claude in the TUI
(`tui_data.py:334-357`); the opencode SSE client (`cli_bridge.py:422-479`)
is dead code on the dispatch path.

- Codex: `codex exec --json` emits JSONL events — parse incrementally.
- OpenCode: wire the existing `_opencode_send_and_wait` SSE client into the
  TUI `send_streaming` path instead of falling back to blocking `send`.

Files: `src/tui_data.py`, `src/runtime/providers/cli_bridge.py`,
`tests/test_tui_data.py`.

Accept: TUI chat streams tokens for all three of claude/codex/opencode.

### 0.3 Real live tests for codex/opencode — **S**

*Finding:* `tests/live/test_live_providers.py` codex/opencode tests are
explicitly "scaffolding with no real assertions yet" (docstring lines 9-11),
so multi-provider behavior is unverified end-to-end — unacceptable when
these are the dogfood mains.

Assert: JSON contract compliance, usage capture, session id capture (after
0.1), permission config files written before dispatch, non-zero exit
handling. Keep them opt-in behind `SARATHI_LIVE_TESTS=1`.

Accept: `SARATHI_LIVE_TESTS=1 pytest tests/live -q` meaningfully fails when
a codex/opencode bridge regresses.

### 0.4 Cross-provider cost model — **M**

*Finding:* only claude self-reports cost (`total_cost_usd`); codex/opencode
usage falls back to a chars÷4 token estimate with no dollar figure
(`contracts.py:214-218`). The learn-evolve loop can't optimize what it
can't price.

- Add a price table: `pricing:` block in `model-routing.md` (per provider ×
  model, $/1M input and output tokens) compiled like other policy — keeps the
  engine domain-agnostic.
- New `src/runtime/pricing.py`: resolve `UsageRecord` → `cost_usd`; prefer
  provider-self-reported cost when present.
- Record `cost_usd` into the harness outcome quality signals (`token_cost`
  already exists as a signal — feed it real dollars).

Files: `src/runtime/contracts.py`, new `src/runtime/pricing.py`,
`policy-pack/EXAMPLE/model-routing.md`, `src/harness.py`, tests.

Accept: after any codex/opencode run, `sarathi log <task>` shows a dollar
cost; usage-stats endpoint aggregates it.

### 0.5 Honest provider auth/health detection — **S**

*Finding:* an installed-but-logged-out CLI reads as `online` because only
`--version` is probed (`service/providers.py:796-897`).

Probe real login state per provider (`codex login status`,
`opencode auth list`, `claude` config presence), map failures to a
`needs_auth` health state surfaced in `GET /providers` and preflight.

Files: `src/service/providers.py`, `src/runtime/preflight.py`, tests.

Accept: logging out of codex flips its provider card to `needs_auth` and
preflight warns before a run wastes a dispatch.

---

## Phase 1 — Un-block the human loop and unify state

### 1.1 Escalation approval on CLI / TUI / MCP — **M**

*Finding:* only the HTTP API/Web can approve a paused escalation
(`app.py:1285-1316`); a run that pauses for approval is a **dead end** in
CLI, TUI, and MCP — the exact surfaces a terminal-first dogfood lives in.

- CLI: `sarathi approve <task-id> [--note]` → records approval artifact →
  invokes the existing resume path.
- TUI: `a` keybind on a paused task in TasksScreen.
- MCP: `approve_task` tool (mirrors `resume_task`).

Files: `src/cli.py`, `src/tui.py`, `src/mcp_server.py`, `src/engine.py`
(consume approval artifact on resume), tests per surface.

Accept: a HIGH-complexity run that pauses on `requires_human_approval`
can be approved and completed without ever opening the web cockpit.

### 1.2 Health-gated failover at dispatch time — **M**

*Finding:* health scores are computed but never consulted —
`_FALLBACK_PROVIDER_ORDER` is a static list (`harness.py:213`) and
`LocalDispatcher` only retries the *same* provider (`dispatch.py:211-244`).

- Order fallback agents by `health_score` at harness build.
- After the retry budget exhausts on transient errors, fail over to the next
  fallback agent instead of failing the phase.
- Upgrade `ProviderHealthStore`: rolling window with decay (a single ancient
  failure should not depress the ratio forever), record latency EWMA.

Files: `src/harness.py:205-278`, `src/dispatch.py`,
`src/runtime/provider_health.py`, `tests/test_dispatch_resilience.py`.

Accept: kill opencode auth mid-run → dispatch fails over to codex and the
run completes; `provider_health.json` shows decayed scores and latency.

### 1.3 Wire SSE end-to-end — **M**

*Finding:* the server has a real SSE stream (`app.py:282-290`) that **no
client consumes** — web polls JSON (`web/src/api/events.ts:1-12`), TUI
polls every 2s, CLI `watch` loops.

- Web: swap the polling transport for `EventSource` (the URL builder
  already exists at `events.ts:87`).
- CLI: `sarathi watch <task> --follow` consuming SSE via the service bridge.
- TUI: optional — keep the 2s poll (it's local SQLite/JSON reads; cheap).

Files: `web/src/api/events.ts`, `src/cli.py` (`handle_watch`), tests
(`test_sse_events.py` extension).

Accept: web TaskStudio updates without a poll interval; `watch --follow`
prints phase transitions as they happen.

### 1.4 Heal the split-brain — **L** (staged; highest architectural value)

*Finding:* CLI/TUI/MCP persist to `.sarathi/tasks/*.json` and run the
12-phase lifecycle engine; Web/Desktop persist to `.sarathi/sarathi.db` and
run a different subtask-graph engine. Tasks and even **policy proposals are
two disjoint systems** (`evolve.ProposalReviewStore` vs
`service/proposals.py`). The README's "one service owns state" is currently
aspirational.

Stage it — do not attempt a big-bang merge:

- **A. Dual-write engine runs into sarathi.db (S/M):** the engine gains an
  optional recorder that mirrors task snapshots + phase logs into the
  `lifecycle_events` / task tables when `.sarathi/sarathi.db` exists. CLI
  runs become *visible* (read-only) in the web cockpit immediately. This
  also makes engine runs flow through the same Slack listener namespace.
- **B. One proposal store (M):** pick SQLite as the source of truth; make
  `ProposalReviewStore` a thin adapter over it; migrate existing
  `.sarathi-proposals/*.json` on first touch. A proposal accepted in the TUI
  is the same proposal the web Proposals view shows.
- **C. CLI/TUI as service clients when the service runs (L, later):**
  the discovery plumbing already exists (`~/.sarathi/service.json`;
  `attach`/`fork`/`reuse` already do HTTP). Route `run`/`status`/`log`
  through the service when it's up, engine-in-process when it isn't.

Files: `src/engine.py` (recorder hook — mirror the notifications pattern),
`src/storage/__init__.py`, `src/evolve.py`, `src/service/proposals.py`,
migration in storage schema, tests.

Accept (A+B): a `sarathi run` task appears in web History with its phase
log; proposal accept/reject is consistent across TUI, CLI, MCP, and web.

---

## Phase 2 — The dogfood differentiator: codex vs opencode bake-off

This is the loop nobody else in the market closes, and a two-provider local
setup is the perfect lab for it.

### 2.1 Native-provider FANOUT bake-off recipe — **M**

*Finding:* FANOUT+JUDGE with provider round-robin is implemented and tested
(`graph_executor.py:590-645`), but the shipped recipes only exercise
`gateway` providers; the JUDGE is a vibe-based single dispatch.

- Ship a `policy-pack/RECIPES/bakeoff/` recipe: FANOUT the same task to
  `codex` and `opencode` native bridges, run VERIFY commands against each
  candidate, JUDGE with the *measured* results in its context.
- Ensure per-branch native-bridge dispatch works with worktree isolation
  (2.2) so candidates don't stomp each other.

Files: `policy-pack/RECIPES/bakeoff/*`, `src/runtime/graph_executor.py`
(branch → isolation), `tests/test_graph_executor_providers.py`.

Accept: `sarathi run "..." --recipe bakeoff` produces two candidate
implementations, a judged winner, and per-candidate test/cost evidence.

### 2.2 Git worktree isolation per EXECUTE branch — **M/L**

*Finding:* no isolation — parallel branches share the working tree; every
competitor (claude-squad, Vibe Kanban, Conductor, Sculptor) treats
isolation as table stakes.

- New `src/runtime/isolation.py`: create/cleanup `git worktree` per branch
  under `.sarathi/worktrees/<task>/<node>`; record `isolation_mode` in
  `HarnessConfig` (honoring the declare-before-dispatch invariant).
- Winner branch merge-back gated by the existing approval flow.
- Container isolation (Dagger `container-use` MCP) is a later upgrade path —
  design the interface so a `container` mode can slot in.

Files: new `src/runtime/isolation.py`, `src/harness.py`,
`src/runtime/graph_executor.py`, `src/runtime/providers/cli_bridge.py`
(`--dir`/`--add-dir` point at the worktree), tests.

Accept: bake-off runs two branches concurrently with zero cross-talk;
aborted runs leave no stray worktrees.

### 2.3 Measured JUDGE + routing feedback — **M**

*Finding:* quality signals exist but don't close the loop into routing;
complexity only gates phase-skipping (`harness.py:205-210`).

- JUDGE scoring policy in `review.md`: weight test_pass_rate, blast_radius,
  cost_usd (from 0.4), latency.
- Record winner-per-task-class into the learn loop; `evolve.py` emits
  `model-routing.md` proposals ("codex wins mutation/* 8:2 — propose
  routing mutation/* to codex").

Files: `src/runtime/graph_executor.py` (judge context), `src/evolve.py`,
`src/phases/learn.py`, `policy-pack/EXAMPLE/review.md`, tests.

Accept: after N bake-offs, `sarathi proposals` shows a data-backed routing
proposal; accepting it changes where the next task dispatches.

---

## Phase 3 — Platform hardening (post-dogfood-loop)

Ordered, but schedule opportunistically.

- **3.1 Provider registry refactor — L.** Collapse the ~10 hardcoded
  provider sites (`cli_bridge.py:122,132-145,924-934,1111-1326`;
  `service/providers.py:446-659`; `preflight.py:29`; `tui_data.py:229`;
  `harness.py:205-213`) into one declarative `ProviderSpec` (argv template,
  prompt transport, output parser, resume flag, permission writer, version
  probe). Not urgent while codex/opencode are the mains, but it converts
  "add Cursor/Gemini" from a 10-file surgery into one spec — do it before
  adding any third provider.
- **3.2 Diff review surface — M.** Hunk-level approve/reject in TUI +
  web TaskStudio, comments fed back into the REVIEW phase as evidence.
- **3.3 GitHub issue-as-queue — M.** Label an issue → 12-phase run → PR
  with the phase log + evidence as the audit-trail body. Intake endpoint
  exists (`app.py:1047`); add the trigger + PR assembly.
- **3.4 Copilot: promote or demote — S.** Either add permission
  enforcement + TUI chat support, or mark it experimental in
  `_provider_specs` and docs. Current half-state misleads.
- **3.5 Web cockpit JS tests — M.** The React SPA has zero runtime tests
  (only a Python test asserting on TSX source). Add Vitest + a few
  TaskStudio/NeedsYou smoke tests.
- **3.6 `sarathi chat` honesty — S.** It aliases the TUI (`cli.py:642`).
  Either implement a real inline CLI chat or rename/document.
- **3.7 Policy pack registry — M.** `sarathi init --from <pack-url>`;
  version packs; positions packs as shareable governance artifacts.
- **3.8 Inbound Slack — M/L.** Slash-command task intake pairing with 3.3
  (outbound shipped ☑).

---

## Suggested dogfood sequence

Week-by-week, assuming solo part-time effort and that each item is itself
run through Sarathi as a task:

1. **0.3 live tests** first (S — establishes the safety net), then **0.1
   resume** and **0.2 streaming** (the daily-driver pain).
2. **0.4 cost** + **0.5 auth** (S/M each — makes signals honest).
3. **1.1 approvals** (unblocks HIGH-complexity dogfood tasks in terminal).
4. **1.4-A dual-write** (see your CLI runs in the cockpit) then **1.4-B
   proposals**.
5. **1.2 failover**, **1.3 SSE** as convenient.
6. Phase 2 as one arc: **2.2 worktrees → 2.1 bake-off recipe → 2.3
   measured JUDGE**. This is the demo that differentiates Sarathi.
7. Phase 3 opportunistically; do **3.1 registry** before ever adding a
   third provider.

Every item above should land with tests and, where user-visible, a README
or policy-pack doc update — the same bar the Slack feature set.
