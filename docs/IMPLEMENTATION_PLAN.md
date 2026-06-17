# Sarathi — Master Implementation Plan

**Status:** Approved for execution
**Date:** 2026-06-14
**Branch:** `claude/sarathi-webui-cockpit-511ubm`
**Companion docs:** `docs/omnigent-parity-design.md` (parity roadmap),
`docs/webui-v1-design.md` (UI surface design).

This is the executable plan that unifies the omnigent-parity roadmap and the
WebUI v1 design into sequenced, independently-shippable tasks. Each task is sized
for a single worker subagent and carries its own files, approach, acceptance
criteria, tests, and dependencies.

---

## Current implementation status (branch `claude/sarathi-webui-cockpit-511ubm`)

Verified on 2026-06-15 against the current branch contents, commit history, and
targeted test suites.

- **M0 — Foundations:** delivered. Queue-state projections, project grouping,
  OpenAPI 3.1, and SSE stream plumbing are present and covered by targeted tests.
- **M1 — Web cockpit (read):** delivered. The Vite web cockpit includes the
  shell, workspace/theme plumbing, Dashboard, Task Studio, History, Agents,
  Usage Stats, Wiki, Settings, typed API helpers, and SSE client hooks.
- **M2 — Governed actions:** delivered. Approvals, transition/dispatch/schedule
  controls, chat broadcast, delivery spine, handoff, and repo-action governance
  are wired through the service and web Task Studio. NCP prior-findings fetch and
  memory/cost persistence are wired into subtask dispatch behind the workspace
  `.ncp/` bridge and remain inert when the bridge is absent.
- **M3 — Model & execution breadth:** delivered.
  - **T3.1 Gateway provider:** pure-Python `GatewayProviderAdapter` for
    OpenAI-compatible endpoints (Ollama/vLLM/OpenRouter/Azure) over `httpx`,
    with env-var API keys, keyless support, routing, validation, docs, and tests.
  - **T3.2 Sandbox executor:** opt-in Docker-compatible `SandboxExecutor` for
    VERIFY with workspace bind mounting and evidence flow-back. Docker remains
    the default runtime; Podman is supported via `SARATHI_SANDBOX=podman` or
    `{"sandbox": "docker", "runtime": "podman"}`. Machine-local runtime paths
    are supplied through `SARATHI_SANDBOX_RUNTIME`, not hardcoded in source or
    policy. Fake-executor, argv-shape, factory, and environment-resolution tests
    pass; real Docker and Podman container tests were verified locally on
    2026-06-15. Docker/Podman tests still skip cleanly on hosts where the
    matching runtime daemon is unavailable.
- **M4 — Collaboration & distribution:** delivered with one verification caveat.
  - **T4.1 Session model (sharing & co-drive):** delivered. `sessions` and
    `session_participants` storage, share/attach/participant/message endpoints,
    observer read-only behavior, lifecycle audit logging, and `sarathi attach`
    CLI are implemented.
  - **T4.2 Session forking:** delivered. `POST /sessions/{id}/fork` and
    `sarathi fork` clone context into an independent task/session with NCP
    warm-start lineage when an NCP SQLite bridge exists.
  - **T4.3 Optional auth / multi-user:** delivered. `SARATHI_AUTH_ENABLED=1`
    enables user storage, Principal resolution, admin-only user provisioning,
    token enforcement, and role checks; auth-off behavior stays unchanged. OIDC
    remains a future follow-up.
  - **T4.4 One-line installer + Homebrew:** delivered. `scripts/install.sh` and
    `Formula/sarathi.rb` exist and were verified with a real temporary-prefix
    install producing working `sarathi` and `sarathi-desktop` commands.
  - **T4.5 Electron packaging:** scaffold delivered. `desktop/` starts the
    service, polls `/api/health`, opens the cockpit, and manages service child
    lifecycle. Syntax/package validation is done; the actual `electron-builder`
    packaged build remains unverified on a macOS/Electron toolchain host.
- **M5 — Governance depth & ecosystem:** partially delivered.
  - **T5.1 Three-tier policy layering:** delivered in commit `9f7509b`.
  - **T5.2 Declarative user agents + function-tools:** delivered in commit
    `e64d9f3`.
  - **T5.3 Reference recipes:** delivered in commit `910bb0a`.
  - **T5.4 Knowledge Center & Skills depth:** still pending as the main remaining
    planned implementation slice. Proposal/knowledge pieces exist, but the full
    T5.4 scope (unified proposal review, context inspector, skills registry,
    routing/roles/evolution, and proposal-backed wiki edits) is not yet complete.

**Verification snapshot:** plan-area targeted tests passed with `125 passed, 3
skipped`; M5 targeted tests passed with `102 passed, 2 warnings`.

---

## 0. Goal & guardrails

**Goal:** reach omnigent's surface area (web cockpit, collaboration, model
breadth, easy install, declarative agents) while every feature stays **governed
and measured** — Sarathi's differentiator.

**Non-negotiable guardrails for every task:**
1. The local **service owns truth**; CLI, TUI, and Web UI are thin clients over
   it. No client re-derives business logic.
2. New model/execution backends arrive as `ProviderAdapter`s so they inherit
   `HarnessConfig` routing, permission scopes, and `HarnessOutcome` measurement.
3. Sensitive mutations stay **approval-gated** and **audited** (`approval_gates`,
   `lifecycle_events`).
4. No external network deps in the web bundle that break offline/local use.
5. Tests-first where the engine is touched; `python3 -m pytest -q` stays green.

**Resolved open decisions** (per the Orchestrator reference screenshot; revisit
if needed):
- **D-1 Wiki** → lives under a **Knowledge** nav group (with Usage Stats).
- **D-2 Approvals** → folded into the Dashboard **"Needs you"** lane + badge;
  no separate Inbox nav in v1. History view carries the audit trail.
- **D-3 Surface #4** → named **"Usage Stats"**, but keeps the richer Outcomes
  content (quality signals + cost).
- **D-4 Multi-workspace** → global **org-style switcher**; the Workspace page is
  reached from the switcher ("Manage workspace"), not a permanent tab.

---

## 1. Architecture anchors (where code lands)

| Subsystem | Location | Used by |
|-----------|----------|---------|
| HTTP router | `src/service/app.py` (`ServiceApp._route`) | M0 contracts, all endpoints |
| HTTP server / auth / CORS | `src/service/http.py` | SSE, auth |
| Storage + migrations | `src/storage/__init__.py` (`run_migrations`) | project_id, sessions, auth tables |
| Provider ABC | `src/runtime/providers/base.py` | gateway, sandbox |
| OpenAI adapter (`base_url`) | `src/runtime/providers/openai_sdk.py` | gateway |
| Provider config/validation | `src/runtime/providers/configured.py` | provider registration |
| Policy compiler/validator | `src/policy/` | policy layering |
| Agent roles | `src/runtime/agent_roles.py` | declarative agents |
| Desktop launcher (service + Vite) | `src/service/desktop.py` | web bundle, packaging |
| Outcome measurement | `src/harness.py` (`measure_outcome`) | Usage Stats |
| Web bundle (new) | `web/` | all UI |

---

## 2. Milestones & critical path

```
M0 Foundations ──► M1 Web cockpit (read) ──► M2 Governed actions
   │                                              │
   ├──► M3 Model & execution breadth (parallel)   │
   │                                              ▼
   └──► M4 Collaboration & distribution ──► M5 Governance depth & ecosystem
```

**Critical path to a convincing demo ("prove the point"):**
`T0.3 OpenAPI` + `T0.4 SSE` + `T0.1 projection` → `T1.1 shell` → `T1.2 Dashboard`
→ `T1.3 Task Studio` → `T2.1 Approvals` → `T3.1 Gateway`. That yields a live,
governed, multi-provider cockpit with measured outcomes.

---

## 3. Milestone M0 — Foundations (service contracts)

> Everything else depends on these. Ship first. No UI yet.

### T0.1 — Queue-state projection contract
- **Goal:** one normalized task-summary projection consumed by CLI/TUI/Web.
- **Fields:** `status, phase, queue_state, approval_state, graph_state,
  next_gate, blocked_count, review_needed_count, checkpoint_state,
  handoff_state, updated_at, project_id`.
- **Files:** `src/service/views.py` (or new `projections.py`), `src/service/app.py`
  (task list + dashboard routes), reuse `lifecycle_events`/`approval_gates`.
- **Queue vocabulary (canonical, 11):** `intake, planning, awaiting_approval,
  ready, running, under_review, blocked, waiting_human, failed, handoff_ready,
  done`.
- **Acceptance:** `GET /workspaces/{id}/task-dashboard` returns every field for
  every task; CLI `sarathi status` reads the same projection.
- **Tests:** extend `tests/test_task_dashboard.py`.
- **Deps:** none (do alongside T0.2). **Effort:** M.

### T0.2 — `tasks.project_id` + project CRUD
- **Goal:** make Projects a real grouping layer for tasks.
- **Files:** `src/storage/__init__.py` (new `_MIGRATION_*`: `ALTER TABLE tasks
  ADD COLUMN project_id TEXT` + per-workspace default project + backfill),
  `src/service/app.py` (project list/create/assign), `src/service/intake.py`.
- **Acceptance:** existing tasks migrate to a default project; new tasks accept a
  `project_id`; dashboard can group by project.
- **Tests:** `tests/test_migrations.py`, `tests/test_task_creation.py`.
- **Deps:** none. **Effort:** S–M.

### T0.3 — OpenAPI 3.1 spec + docs
- **Goal:** published contract for all clients.
- **Files:** `src/service/openapi.py` (route registry + generator), `app.py`
  (`GET /openapi.json`, `GET /docs` serving a static Redoc/Swagger page),
  `docs/openapi.json` (committed snapshot).
- **Approach:** a small decorator/registry over the existing `_route` ladder so
  the spec is generated from one source (Sarathi "dual-source" ethos).
- **Acceptance:** spec validates (`openapi-spec-validator`); a generated client
  calls `/health` and `/workspaces`.
- **Tests:** new `tests/test_openapi.py` (schema lints, all routes present).
- **Deps:** none. **Effort:** S–M.

### T0.4 — SSE event stream
- **Goal:** push phase/lifecycle/message events to live clients.
- **Files:** `src/service/events.py` (new), `src/service/http.py` (streaming
  response), `app.py` (`GET /workspaces/{id}/tasks/{tid}/events`).
- **Approach:** replay from `lifecycle_events`, then tail; support
  `Last-Event-ID` for gap-free reconnect; polling fallback documented.
- **Acceptance:** client sees a transition within ~1s; reconnect resumes.
- **Tests:** new `tests/test_sse_events.py`.
- **Deps:** none. **Effort:** M.

**M0 exit criteria:** OpenAPI published; SSE live; one projection contract;
projects group tasks. All clients can be built against documented contracts.

---

## 4. Milestone M1 — Web cockpit (read surfaces)

> Builds the installable web UI as a thin client over M0. Read-mostly.

### T1.1 — Web app scaffold + shell
- **Goal:** Vite SPA under `web/`, served by `sarathi-desktop` at `vite_port`.
- **Scope:** build tooling; typed API client generated from `openapi.json`;
  SSE hook; **light/dark theme system**; app shell (sidebar + topbar) matching
  `docs/mockups/sarathi-webui-mockup.html`; **workspace switcher**; grouped nav
  (Workspace: Dashboard/Needs you/History/Agents · Knowledge: Wiki/Usage Stats ·
  System: Settings); "Connected · Live" presence from SSE.
- **Files:** `web/` (package.json, vite config, src), `src/service/http.py`
  (static serving of built bundle), `src/service/desktop.py` (already launches it).
- **Acceptance:** `sarathi-desktop` opens the shell; switching workspace rescopes
  all surfaces; theme toggle persists.
- **Deps:** T0.3. **Effort:** L.

### T1.2 — Dashboard (Kanban)
- **Scope:** board grouped by project; **5 lanes** folding the 11 queue states
  (Intake/Planning · Active · Needs you · Review · Done/Handoff); card chips for
  raw state, provider, AC coverage; filters (project/provider/saved view);
  board/list toggle; "+ New project"; global "Needs you (N)".
- **Files:** `web/src/views/Dashboard`.
- **Acceptance:** lanes render from the projection; blocked/waiting/failed are
  visually distinct; clicking a card opens Task Studio.
- **Deps:** T1.1, T0.1, T0.2. **Effort:** M.

### T1.3 — Task Studio (read) + live chat thread
- **Scope:** two-pane — **DAG/list** (vertical, status-colored nodes, provider
  badges, dashed future edges, legend) + **chat thread** (user/Sarathi/agent),
  live via SSE; state header (queue/phase/class/provider/AC/next-safe-action);
  tabs Evidence/Review/History/Handoff (read).
- **Files:** `web/src/views/TaskStudio`, a small DAG renderer (SVG, no heavy dep).
- **Acceptance:** opening a task loads one snapshot (graph + messages + lifecycle
  + evidence + reviews + handoff) and updates live.
- **Deps:** T1.1, T0.4. **Effort:** L.

### T1.4 — History, Agents, Usage Stats, Wiki, Settings (read)
- **Scope:** History (phase/governance log); Agents (provider health + transport
  posture + active dispatches + Sarathi roles); **Usage Stats** (quality signals
  from `measure_outcome` + per-task table); Wiki (browse, gen-vs-human, provenance);
  Settings (providers, policy status, governance history — read only).
- **Files:** `web/src/views/*`; service endpoints already exist for most
  (`operational-views`, `task-dashboard`, `wiki`, providers); add a
  `usage-stats` projection from `HarnessOutcome` if missing.
- **Acceptance:** each surface renders live service data; mock data, if any, is
  labeled.
- **Deps:** T1.1; Usage Stats may need a small service projection. **Effort:** M.

**M1 exit:** a usable, live, read-only cockpit across all v1 surfaces, installable
via `sarathi-desktop`.

---

## 5. Milestone M2 — Governed actions (write paths)

### T2.1 — Approvals
- **Scope:** approve/reject `approval_gates` inline in chat + "Needs you";
  decisions write to `lifecycle_events` with actor/rationale.
- **Files:** `app.py` (gate decision endpoints if missing), `web/.../approvals`.
- **Acceptance:** approving an irreversible mutation gate dispatches the unit;
  rejecting requeues; audit visible in History.
- **Deps:** T1.3. **Effort:** M.

### T2.2 — Transition & dispatch controls
- **Scope:** schedule-ready-nodes, resume, rerun, reroute provider, retry failed;
  respect permission scopes.
- **Files:** `app.py` (`scheduling`), `web/.../TaskStudio`.
- **Acceptance:** a ready unit can be dispatched/transitioned per policy; a
  blocked task surfaces the next safe recovery action.
- **Deps:** T1.3, T2.1. **Effort:** M.

### T2.3 — Chat input → agent broadcast
- **Scope:** composer with sender selector; message persists to `messages` and
  is "visible to all agents on the task"; triggers dispatch where applicable.
- **Files:** `app.py` (message post), `web/.../chat`.
- **Acceptance:** posting a message appears live for all attached clients.
- **Deps:** T1.3. **Effort:** S–M.

### T2.4 — Delivery spine & handoff
- **Scope:** PRD/AC coverage, missing requirements, final handoff dossier;
  repo-action approval (commit/PR/export) preserving audit; failed repo action
  preserves handoff + recovery.
- **Files:** `app.py` (handoff/repo-action), `web/.../Handoff`.
- **Acceptance:** no task shows "done" without review evidence + AC coverage;
  repo actions are approval-recorded.
- **Deps:** T2.1. **Effort:** M.

**M2 exit:** the cockpit can drive a task end-to-end under governance.

---

## 6. Milestone M3 — Model & execution breadth (parallel with M1/M2)

### T3.1 — OpenAI-compatible gateway provider
- **Scope:** expose `base_url` as a first-class `gateway` provider type
  (OpenRouter/Ollama/vLLM/Azure) in `model-routing.md` + `providers` table;
  `api_key_env`, `model`, capabilities; validation.
- **Files:** `src/runtime/providers/configured.py`, `openai_sdk.py` (minor),
  `providers/__init__.py`, policy-pack docs.
- **Acceptance:** `provider: gateway` → local Ollama completes a dispatch; token
  usage recorded in `HarnessOutcome`.
- **Tests:** `tests/test_provider_dispatch.py`. **Deps:** none. **Effort:** S–M.

### T3.2 — Sandbox executor (Docker first)
- **Scope:** `SandboxExecutor` so a unit's build/test runs in an isolated
  container; interface designed for Modal/Daytona later; evidence still flows back.
- **Files:** `src/runtime/sandbox/` (new), `commands.py`, `workspace_evidence.py`,
  `dispatch.py`.
- **Acceptance:** `execution.sandbox: docker` runs tests in a container; VERIFY
  measures real pass/fail; no host FS mutation outside the mounted workspace.
- **Tests:** new `tests/test_sandbox.py` (skip if no Docker). **Deps:** none.
  **Effort:** L.

---

## 7. Milestone M4 — Collaboration & distribution

### T4.1 — Session model: sharing & co-drive
- **Scope:** tables `sessions` (task_id, owner, share_token, visibility) +
  `session_participants` (user, role owner|driver|observer); endpoints to create
  share link, join (`attach`), list participants, leave; scope `messages` to a
  session. Driver actions still go through gates; participation logged.
- **Files:** `src/storage/__init__.py`, `src/service/sessions.py` (new), `app.py`,
  CLI `sarathi attach`.
- **Acceptance:** two clients attach to one task; same live stream; observers are
  read-only; participation in `lifecycle_events`.
- **Deps:** T0.4, T1.3, T4.3 (auth for non-local). **Effort:** L.

### T4.2 — Session forking
- **Scope:** `POST /sessions/{id}/fork` clones context/history to a checkpoint
  (reuse `checkpoint_capsules`) into a new task/session, measured separately.
- **Files:** `sessions.py`, storage, CLI `sarathi fork`.
- **Acceptance:** fork yields an independent task with its own LEARN.
- **Deps:** T4.1. **Effort:** M.

### T4.3 — Optional auth / multi-user
- **Scope:** opt-in `SARATHI_AUTH_ENABLED=1`; token/session auth + user table;
  OIDC (Google/GitHub) as a follow-up sub-task. Default stays single-user local.
- **Files:** `src/service/auth.py` (new), `http.py`, storage.
- **Acceptance:** auth off = unchanged; auth on = endpoints require a principal
  and enforce participant roles.
- **Deps:** none; required by non-local T4.1. **Effort:** M–L.

### T4.4 — One-line installer + Homebrew
- **Scope:** `scripts/install.sh` (detect Python, venv, pip install, smoke test)
  for `curl … | sh`; Homebrew formula.
- **Files:** `scripts/install.sh`, `Formula/sarathi.rb`, README.
- **Acceptance:** clean machine → working `sarathi --help` and `sarathi-desktop`.
- **Deps:** none. **Effort:** S.

### T4.5 — Desktop app packaging (Electron)
- **Scope:** wrap `sarathi-desktop` (service + web bundle) in an Electron shell
  (original mock intent) producing installable artifacts (macOS first). Service +
  DB stay local; shell manages lifecycle already in `desktop.py`.
- **Files:** `desktop/` (Electron), build config; reuse `desktop.py` orchestration.
- **Acceptance:** a packaged app launches the cockpit with no terminal.
- **Deps:** T1.1 (web bundle). **Effort:** L.

---

## 8. Milestone M5 — Governance depth & ecosystem

### T5.1 — Three-tier policy layering
- **Scope:** resolve effective policy server → workspace → session,
  **strictest-wins** for caps (cost budget, max tool calls, approval reqs);
  resolved policy is a diffable artifact.
- **Files:** `src/policy/compiler.py`, `validator.py`, `service/preferences.py`.
- **Acceptance:** a session can only tighten, never loosen, a workspace cap;
  `sarathi validate` reports the layered resolution.
- **Deps:** T4.1 for session scope (server↔workspace can ship first). **Effort:** M.

### T5.2 — Declarative user agents + function-tools
- **Scope:** agent spec file (prompt + harness + TaskClass + Python function-tools
  with auto schema + sub-agents); loader registers into `agent_roles`; compiles to
  `HarnessConfig` so it's measured.
- **Files:** `src/runtime/agent_spec.py` (new), `agent_roles.py`, `harness.py`.
- **Acceptance:** `sarathi run --agent <name>` dispatches a user agent with a
  custom tool; run shows measured signals.
- **Deps:** T3.1 (model choice helpful). **Effort:** L.

### T5.3 — Reference recipes (Polly / Debby parity)
- **Scope:** ship two example policy-packs — orchestrator (plan → FANOUT across
  providers → cross-provider JUDGE) and debate (dual-provider + adversarial JUDGE).
- **Files:** `policy-pack/RECIPES/`, `skill/policy-pack/`, docs.
- **Acceptance:** orchestrator recipe fans out across ≥2 providers and produces a
  judged, merged, **measured** result.
- **Deps:** T3.1, T5.2. **Effort:** M.

### T5.4 — Knowledge Center & Skills depth
- **Scope:** unified proposal review (diff, risk, source evidence, decision audit);
  context inspector (selected/omitted sources, token posture); skills registry/
  routing/roles/evolution; proposal-backed wiki edits.
- **Files:** `app.py` (proposals/knowledge/skills), `web/.../Knowledge`,`/Skills`.
- **Acceptance:** no self-evolving change applies silently; accepted proposals are
  fully auditable.
- **Deps:** T1.4, T2.1. **Effort:** L.

---

## 9. Delegation matrix (worker subagents)

Independent tracks that can run in parallel once M0 lands:

| Track | Tasks | Skill profile |
|-------|-------|---------------|
| Service/contracts | T0.1–T0.4, T2.x endpoints | Python, SQLite, HTTP |
| Web cockpit | T1.1–T1.4, web side of M2 | TypeScript/Vite, SVG |
| Providers/runtime | T3.1, T3.2 | Python, subprocess/Docker, SDKs |
| Collaboration | T4.1–T4.3 | Python, auth, storage |
| Distribution | T4.4, T4.5 | shell, Electron, packaging |
| Governance/ecosystem | T5.1–T5.4 | Python, policy, web |

**Orchestration rule:** the brain assigns one task per worker with this plan's
section as the spec, reviews the diff against the task's acceptance criteria, runs
tests, then commits. Workers do not commit.

---

## 10. Testing & definition of done

- **Engine tasks:** unit tests added/updated; `python3 -m pytest -q` green.
- **Service tasks:** route tests + projection-contract tests; OpenAPI stays valid.
- **Web tasks:** a Playwright smoke (load shell, switch workspace, open a task,
  approve a gate) running against the live local service (not mock-only) — mirrors
  the requirements' "live validation" rule.
- **DoD per task:** acceptance criteria met, tests green, docs/OpenAPI updated,
  no guardrail (§0) violated, committed to the branch with a descriptive message.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Web UI drifts from service truth (the prior failure) | Generated API client from OpenAPI; live Playwright smoke; no mock in primary surfaces |
| Scope creep back to "too many tabs" | v1 IA locked to 7 grouped nav items; Knowledge/Skills depth deferred to M5 |
| Sandbox infra flakiness | Docker backend first, behind a capability flag; skip tests without Docker |
| Auth complexity | Opt-in; single-user local default unchanged |
| Provider transport churn | All providers behind `ProviderAdapter`; capabilities reported, not assumed |

---

## 12. Sequencing summary

1. **M0** foundations (parallel: T0.1–T0.4).
2. **M1** web cockpit (T1.1 → T1.2/T1.3/T1.4).
3. **M3** breadth in parallel (T3.1 early — fast win).
4. **M2** governed actions.
5. **M4** collaboration & distribution.
6. **M5** governance depth & ecosystem.

**Definition of "prove the point":** a packaged Sarathi app where an operator
drives a multi-provider task from the browser, approves a gate, and sees measured
quality signals in Usage Stats — reach matched, rigor retained.
