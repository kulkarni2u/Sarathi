# Sarathi Reach Roadmap — Design & Task Breakdown

**Status:** Draft
**Date:** 2026-06-14
**Goal:** Close the "reach" gap with omnigent (collaboration, UX, deployment,
model breadth, declarative agents) **without diluting Sarathi's differentiator** —
the governed, measured, self-improving delivery lifecycle.

---

## 1. Guiding principle

Omnigent wins on *reach*; Sarathi wins on *rigor*. Every feature below is
designed so that the new "reach" capability flows **through** Sarathi's existing
spine rather than around it:

- Collaboration sits on top of the existing `tasks` / `messages` / `approval_gates`
  tables and the 12-phase lifecycle — every shared session is still an auditable,
  policy-gated task.
- New model backends arrive as `ProviderAdapter` implementations, so they
  inherit `HarnessConfig` routing, permission scopes, and outcome measurement
  for free.
- Declarative user agents compile down to the same `TaskClass` / `HarnessConfig`
  machinery — a user-defined agent is still measured and can still emit
  `PolicyProposal`s.

This is how we "prove the point": Sarathi reaches omnigent's surface area while
every feature remains measurable and auditable, which omnigent's freeform
orchestration cannot claim.

---

## 2. Current architecture anchors (what we build on)

| Subsystem | Location | Reuse for this roadmap |
|-----------|----------|------------------------|
| HTTP service router | `src/service/app.py` (`ServiceApp._route`) | OpenAPI spec, web UI backend, sharing endpoints |
| HTTP server + auth + CORS | `src/service/http.py` | SSE streaming, multi-user auth |
| SQLite storage + migrations | `src/storage/__init__.py` (`run_migrations`, `schema_version`) | New tables: `sessions`, `session_participants`, policy layers |
| Provider ABC | `src/runtime/providers/base.py` (`ProviderAdapter`, `ProviderCapabilities`) | Gateway adapter, sandbox executor |
| OpenAI adapter w/ `base_url` | `src/runtime/providers/openai_sdk.py` | Gateway adapter is mostly config exposure |
| Provider config + validation | `src/runtime/providers/configured.py` | Register new adapters |
| Policy compiler/validator | `src/policy/compiler.py`, `src/policy/validator.py` | Three-tier policy layering |
| Agent role registry | `src/runtime/agent_roles.py` | Declarative user agents |
| Desktop launcher | `src/service/desktop.py` | Serve the web UI bundle |
| Workflow patterns (FANOUT/JUDGE/LOOP) | `src/runtime/workflow_patterns.py` | Reference recipe agents |

---

## 3. Workstreams → independently achievable tasks

Each task below is scoped to be shippable on its own branch with its own tests.
Dependencies are explicit; everything else can proceed in parallel.

### Workstream A — API surface (foundation for clients)

#### Task A1 — Publish an OpenAPI 3.1 spec
- **Why:** Every external client (web, mobile, IDE) needs a contract. The routes
  already exist in `ServiceApp._route`; today they're undocumented.
- **Scope:** Add `docs/openapi.json` (or generate it). Add a `GET /openapi.json`
  and a `GET /docs` (Swagger/Redoc static page) route to `ServiceApp`. Cover the
  existing `/health`, `/workspaces*`, `/tasks*`, `/providers*` routes.
- **Approach:** Introduce a lightweight route-registry so each handler declares
  `method`, `path`, `summary`, request/response schema. Generate the spec from
  the registry (single source of truth — mirrors Sarathi's "dual-source" ethos).
  Avoid a heavy framework; a small decorator over the current `_route` ladder.
- **Files:** `src/service/openapi.py` (new), `src/service/app.py`, `docs/openapi.json`.
- **Acceptance:** `GET /openapi.json` returns a valid 3.1 doc that lints clean
  (e.g. `openapi-spec-validator`); a generated client can call `/health`.
- **Effort:** S–M. **Depends on:** none. **Unlocks:** A2, B1.

#### Task A2 — Server-Sent Events (SSE) task event stream
- **Why:** Live UIs and co-drive need push, not polling. `lifecycle_events`
  already records transitions.
- **Scope:** `GET /workspaces/{id}/tasks/{tid}/events` streaming `text/event-stream`,
  replaying from `lifecycle_events` then tailing new ones. Reuse the existing
  threading HTTP server.
- **Files:** `src/service/http.py`, `src/service/app.py`, `src/service/events.py` (new).
- **Acceptance:** A client receives a phase-transition event within ~1s of it
  being written; reconnect with `Last-Event-ID` resumes without gaps.
- **Effort:** M. **Depends on:** none (A1 recommended first). **Unlocks:** B1, C2.

---

### Workstream B — Web UI & collaboration (the headline gap)

#### Task B1 — Minimal web UI (read + run)
- **Why:** Omnigent's biggest visible advantage is the browser experience.
- **Scope:** A small TypeScript SPA (Vite) served by the desktop launcher /
  service. Screens: workspace list, task list + dashboard, task detail with live
  phase timeline (via A2 SSE), "new task" form, approval-gate prompts.
- **Approach:** Keep it a static bundle under `web/`; service serves it from
  `127.0.0.1`. No SSR. Talks only to the documented API (A1).
- **Files:** `web/` (new), `src/service/desktop.py`, `src/service/http.py` (static serving).
- **Acceptance:** From a browser a user can create a task, watch phases advance
  live, and approve a gate.
- **Effort:** L. **Depends on:** A1, A2.

#### Task B2 — Session model: sharing & co-drive
- **Why:** Omnigent's `attach` / share / fork. This is the collaboration core.
- **Scope:** New tables `sessions` (id, task_id, owner, created_at, share_token,
  visibility) and `session_participants` (session_id, user, role: owner|driver|observer,
  joined_at). Endpoints: create share link, join (`attach`), list participants,
  leave. Messages already exist in `messages` — scope them to a session.
- **Approach:** A "session" is a collaboration view over an existing task; it does
  **not** bypass the lifecycle. Driver actions still go through approval gates and
  permission scopes. Add migrations following the existing `run_migrations` pattern.
- **Files:** `src/storage/__init__.py` (migrations), `src/service/sessions.py` (new),
  `src/service/app.py`, CLI `sarathi attach <session>`.
- **Acceptance:** Two clients attach to one task; both see the same live event
  stream; only `driver`/`owner` can submit input; observers are read-only;
  participation is recorded in `lifecycle_events` (auditable).
- **Effort:** L. **Depends on:** A2 (stream), B1 (to be usable). **Pairs with:** D1 (auth).

#### Task B3 — Session forking
- **Why:** Omnigent's `run --fork` — branch a conversation/task for independent
  exploration.
- **Scope:** `POST /sessions/{id}/fork` clones the task context + message history
  up to a checkpoint into a new task/session. Reuse `checkpoint_capsules`.
- **Files:** `src/service/sessions.py`, `src/storage/__init__.py`, CLI `sarathi fork`.
- **Acceptance:** Forking produces an independent task whose LEARN/measurement is
  tracked separately from the parent.
- **Effort:** M. **Depends on:** B2.

---

### Workstream C — Model & execution breadth

#### Task C1 — OpenAI-compatible gateway provider
- **Why:** Unlocks OpenRouter, Ollama, vLLM, LM Studio, etc. with one adapter.
- **Scope:** `OpenAISdkProviderAdapter` already takes `base_url`; expose it as a
  first-class `gateway` provider type in `model-routing.md` and the `providers`
  table, with `base_url` + `api_key_env` + `model` config and capability
  reporting. Add validation in `configured.py`.
- **Files:** `src/runtime/providers/configured.py`, `src/runtime/providers/openai_sdk.py`
  (minor), `policy-pack/*/model-routing.md` docs, `src/runtime/providers/__init__.py`.
- **Acceptance:** A policy pack pointing `provider: gateway` at a local Ollama
  endpoint completes a dry-run dispatch; outcome measurement records token usage.
- **Effort:** S–M. **Depends on:** none. **High ROI, low risk.**

#### Task C2 — Sandbox execution backend
- **Why:** Omnigent runs in Modal/Daytona sandboxes; Sarathi is local-FS bound.
- **Scope:** A `SandboxExecutor` abstraction behind dispatch so a work unit's
  shell/build/test runs in an isolated container instead of the local workspace.
  First backend: Docker (local), with the interface designed for Modal/Daytona later.
- **Approach:** Wrap command execution (the `SARATHI_EXEC_COMMANDS` path) and
  workspace snapshot/delta so evidence still flows back. Keep it a capability flag
  (`supports_workspace_execution`) so non-sandbox providers are unaffected.
- **Files:** `src/runtime/sandbox/` (new), `src/runtime/commands.py`,
  `src/runtime/workspace_evidence.py`, `src/dispatch.py`.
- **Acceptance:** A task with `execution.sandbox: docker` runs its test command
  inside a container; VERIFY measures real pass/fail; no host FS mutation outside
  the mounted workspace.
- **Effort:** L. **Depends on:** none (independent backend). **Risk:** medium (infra).

---

### Workstream D — Governance & multi-user (org readiness)

#### Task D1 — Optional auth & multi-user
- **Why:** Sharing (B2) and any non-localhost deployment need identity. Mirrors
  omnigent's `OMNIGENT_AUTH_ENABLED` / OIDC.
- **Scope:** Opt-in (`SARATHI_AUTH_ENABLED=1`). Token/session auth layer in
  `http.py`; user table; pluggable OIDC (Google/GitHub) as a later sub-task.
  Default stays single-user localhost so nothing breaks.
- **Files:** `src/service/auth.py` (new), `src/service/http.py`, `src/storage/__init__.py`.
- **Acceptance:** With auth off, behavior is unchanged. With auth on, endpoints
  require a valid principal and participant roles (B2) are enforced.
- **Effort:** M–L. **Depends on:** none; **required by** non-local B2.

#### Task D2 — Three-tier policy layering (server → workspace → session)
- **Why:** Omnigent's strictest-first governance. Sarathi has the richest single
  policy engine of the two — layering makes it deployable for orgs and is a clean
  extension, not a rewrite.
- **Scope:** Resolve effective policy by overlaying server defaults → workspace
  policy-pack → session overrides, with **strictest-wins** for caps
  (cost budget, max tool calls, approval requirements). Surface the resolved,
  layered policy as an artifact (diffable — consistent with `HarnessConfig` ethos).
- **Files:** `src/policy/compiler.py`, `src/policy/validator.py`,
  `src/service/preferences.py`, new `policy-pack` reference docs.
- **Acceptance:** A session cannot *loosen* a workspace cap; it can only tighten.
  `sarathi validate` reports the layered resolution and any conflicts.
- **Effort:** M. **Depends on:** B2 (for session scope) but server↔workspace layer
  can ship first independently.

---

### Workstream E — Distribution & onboarding

#### Task E1 — One-line installer + Homebrew
- **Why:** Omnigent has `curl … | sh`; Sarathi needs clone+venv+pip.
- **Scope:** `scripts/install.sh` (detect Python, create venv, pip install, smoke
  test, print next steps) hosted for `curl … | sh`. A Homebrew formula.
- **Files:** `scripts/install.sh` (new), `Formula/sarathi.rb` (new), README.
- **Acceptance:** A clean machine runs the one-liner and ends with a working
  `sarathi --help`.
- **Effort:** S. **Depends on:** none.

---

### Workstream F — Declarative agents & reference recipes

#### Task F1 — Declarative user-defined agents + function-tools
- **Why:** Omnigent's YAML agents (prompt + harness + Python callable tools +
  sub-agents) are its ergonomic core. Sarathi's agents are fixed Sanskrit roles.
- **Scope:** An agent spec file (`agents/<name>.md`/`.yaml`) declaring: prompt,
  provider/harness, `TaskClass` mapping, tools (Python dotted-path callables with
  auto-generated schemas), and optional sub-agents. A loader registers them in the
  `agent_roles` registry and resolves them in `HarnessConfig` assembly.
- **Approach:** Compile a user agent down to existing primitives so it is still
  measured (`HarnessOutcome`) and policy-gated. Tools become typed graph nodes.
- **Files:** `src/runtime/agent_roles.py`, `src/runtime/agent_spec.py` (new),
  `src/harness.py`, `policy-pack` docs.
- **Acceptance:** A user defines an agent with one custom function-tool in a file;
  `sarathi run --agent <name>` dispatches through it; the run shows up in history
  with measured signals.
- **Effort:** L. **Depends on:** none (C1 nice-to-have for model choice).

#### Task F2 — Reference recipe agents (Polly / Debby parity)
- **Why:** Omnigent ships flagship example agents that demonstrate value
  instantly. Sarathi has the *primitives* (FANOUT, JUDGE, adversarial
  verification) but no ready recipes.
- **Scope:** Ship two example policy-packs/agents:
  - **Orchestrator recipe** (Polly-style): plan → FANOUT to multiple providers in
    parallel worktrees → cross-provider JUDGE review before merge. Built from
    existing `workflow-patterns.md` knobs.
  - **Debate recipe** (Debby-style): dual-provider generate + adversarial
    `JUDGE`/`/debate` refinement.
- **Files:** `policy-pack/RECIPES/` (new), `skill/policy-pack/`, docs.
- **Acceptance:** `sarathi run --policy-pack policy-pack/RECIPES/orchestrator …`
  fans out across ≥2 providers and produces a judged, merged result — with full
  measurement, which omnigent's equivalents do not capture.
- **Effort:** M. **Depends on:** C1 (multi-provider), ideally F1.

---

## 4. Dependency graph & suggested sequencing

```
Phase 1 (parallel, no deps):   A1  C1  E1  D2(server↔workspace)
Phase 2:                       A2 (after A1)   F1   C2   D1
Phase 3:                       B1 (A1,A2)      F2 (C1,F1)
Phase 4:                       B2 (A2,B1,D1)   D2(session layer, after B2)
Phase 5:                       B3 (after B2)
```

**Fast "prove the point" path (minimum to demo parity + rigor):**
`C1` (model breadth) → `A1`+`A2` (API) → `B1` (web UI) → `F2` (a flashy
multi-agent recipe that is *also* measured). That sequence demonstrates
omnigent-class reach with Sarathi-only measurement on top.

---

## 5. Effort summary

| Task | Effort | Risk | Parallelizable |
|------|--------|------|----------------|
| A1 OpenAPI | S–M | Low | Yes |
| A2 SSE stream | M | Low | Yes |
| B1 Web UI | L | Med | After A1/A2 |
| B2 Sharing/co-drive | L | Med | After A2/B1/D1 |
| B3 Forking | M | Low | After B2 |
| C1 Gateway provider | S–M | Low | Yes |
| C2 Sandbox executor | L | Med | Yes |
| D1 Auth/multi-user | M–L | Med | Yes |
| D2 Policy layering | M | Low | Partly |
| E1 Installer/Homebrew | S | Low | Yes |
| F1 Declarative agents | L | Med | Yes |
| F2 Reference recipes | M | Low | After C1/F1 |

---

## 6. How each task reinforces the differentiation

| Reach feature (omnigent parity) | Rigor hook Sarathi keeps |
|---------------------------------|--------------------------|
| Web UI / live sessions | Phase timeline = auditable lifecycle, not a chat log |
| Sharing / co-drive | Participation + driver actions logged to `lifecycle_events`; gates still enforced |
| Gateway / sandbox backends | Arrive as `ProviderAdapter`s → measured by `HarnessOutcome` |
| Declarative agents | Compile to `TaskClass`/`HarnessConfig` → still emit `PolicyProposal`s |
| Layered governance | Resolved policy is a diffable artifact (HarnessConfig ethos) |
| Recipe agents | Same FANOUT/JUDGE patterns, but with measured quality signals |
