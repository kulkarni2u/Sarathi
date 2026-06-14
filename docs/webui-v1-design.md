# Sarathi WebUI & Surfaces — v1 Design (working draft)

**Status:** Brainstorm in progress — some decisions OPEN (see §6).
**Date:** 2026-06-14
**Relationship:** Expands Workstream B of `docs/omnigent-parity-design.md`.
Consolidates the operator's vision + the attached `sarathi-webui-requirements.md`.

---

## 1. North star

Sarathi ships as **one installable, local-first app** that exposes the **same
governed work** through **three thin clients over a single local service**:

```
                ┌──────────────────────────┐
                │  Local Sarathi service    │   ← single source of truth
                │  (HTTP API + SQLite DB)   │      src/service/, src/storage/
                └────────────┬─────────────┘
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
        CLI (sarathi)   TUI (textual)    Web UI (Vite SPA)
                                         └─ wrapped as the installable
                                            desktop app via sarathi-desktop
```

Principle: **clients render projections; the service owns truth.** No client
re-derives business logic. CLI status, TUI labels, and WebUI labels use the same
queue vocabulary (requirements §6, Interoperability NFR).

This mirrors omnigent's "same session from terminal, browser, and phone," but
every surface stays governed and measured — Sarathi's differentiator.

---

## 2. What already exists vs. what's new

| Piece | State today | Source |
|-------|-------------|--------|
| Local service (HTTP + SQLite) | Exists | `src/service/`, `src/storage/` |
| CLI surface | Exists | `sarathi = src.cli:main` |
| TUI surface | Exists, rebuilt in PR #8 | `src/tui.py`, `textual` extra |
| Desktop app launcher | Exists — spawns service + Vite UI, writes runtime config (base_url+token), `--ui-only` mode | `sarathi-desktop = src.service.desktop:main` |
| **Web UI bundle (Vite SPA)** | **MISSING** — launcher expects it at `vite_port` (5173); prior attempt was local-only, not in repo | new `web/` |
| Queue-state projection contract | Partial | needs §9-style fields on task summaries |
| `tasks.project_id` link | **MISSING** — tasks are workspace-scoped, not project-scoped | new migration |
| Multi-workspace API | Exists | `GET/POST /workspaces`, `/workspaces/{id}` |

**Takeaway:** the installable-app + three-surface architecture is already
scaffolded. v1 is mostly (a) building the missing Vite web UI bundle, (b) adding
the project link + projection contract, (c) packaging the launcher as a
distributable app.

---

## 3. Object hierarchy (navigation model)

Backed by the existing schema, plus one addition:

```
Workspace                      (workspaces)                 ← global switcher
 ├─ Repositories (1+)          (workspace_repositories)
 └─ Projects (1+)              (projects)
       └─ Tasks                (tasks)        ← ADD nullable project_id
             ├─ Task Graph     (task_graph nodes/edges)
             │    └─ Execution Units / subtasks
             ├─ Messages/Chat  (messages)
             ├─ Approvals      (approval_gates)
             ├─ Evidence       (evidence_artifacts, dispatches)
             ├─ Reviews        (review_runs)
             └─ Handoff        (handoffs)
```

Required migration: `ALTER TABLE tasks ADD COLUMN project_id TEXT` (nullable) +
a per-workspace default project so existing tasks keep working.

---

## 4. Proposed v1 information architecture

Deliberately leaner than the requirements doc's 7-surface IA (which the doc
itself flags as having drifted to "too many tabs"). Four top-level surfaces +
a contextual Task Studio, scoped by a global workspace switcher.

```
┌───────────────────────────────────────────────────────────────┐
│ [▾ Workspace: payments-platform]   Dashboard · Wiki ·           │
│                                     Outcomes · Settings   [Needs you ●3] │
└───────────────────────────────────────────────────────────────┘
        │  switcher → list workspaces (+ health) + "＋ New workspace"
        │            → "manage workspace" opens the Workspace page
        ▼
  Dashboard (Kanban, grouped by project)
        │  click task ▼
  Task Studio:   DAG / list view   ┃   Chat + inline approvals
```

### 4.1 Dashboard (Kanban)
- Board grouped by **project**, cards = tasks.
- ~5 lanes derived from the 11 queue states (requirements §6), raw state as a
  card chip:

  | Lane | Queue states folded in |
  |------|------------------------|
  | Intake/Planning | `intake`, `planning` |
  | Active | `ready`, `running` |
  | Needs You | `awaiting_approval`, `blocked`, `waiting_human`, `failed` |
  | Review | `under_review` |
  | Done/Handoff | `handoff_ready`, `done` |

- Absorbs the requirements doc's **Inbox** role via the "Needs You" lane + a
  global "Needs you (N)" badge — preserves the governance/HITL story without a
  separate nav item.
- Filters: queue, approval, provider, blocked, review, saved view.

### 4.2 Task Studio
- Two-pane: **DAG/list** (left) + **chat thread** (right, user ↔ Sarathi ↔ agents).
- State header: queue state, phase, providers, approval posture, blocker reason,
  next safe action.
- Inline actions in Sarathi messages: Approve, Reject, View evidence, Change
  provider, Resume, Rerun, Create handoff.
- Tabs behind the two-pane default: Evidence, Review, History, Handoff.
- Live updates via SSE (Workstream A, Task A2).

### 4.3 Wiki
- Page browse + view; approved/proposal-backed editing.
- v1 top-level; **built as the first tab of a future "Knowledge" surface** so
  Context/Proposals/Learnings can join later without rework. (OPEN — §6.1)

### 4.4 Outcomes & Usage
- The strategic differentiator vs omnigent: not just token/cost, but **measured
  quality signals** from `HarnessOutcome` / `measure_outcome()` —
  `test_pass_rate`, `blast_radius`, latency, agent used, and policy proposals
  generated. Per-workspace and per-task. (Framing OPEN — §6.3)

### 4.5 Settings
- Provider config (secrets via safe local mechanisms, never rendered),
  policy-pack status + validation, governance/override history,
  repository-action audit.

### 4.6 Workspace page (not a permanent tab)
- Reached from the switcher's "manage workspace." Health, repos, provider
  readiness, policy posture, repo preview/attach/initialize (approval-gated).
  This is requirements §8.1 demoted from top-nav to a managed page.

---

## 5. Service prerequisites for v1

1. **Queue-state projection contract** (requirements §9): task summaries must
   carry `status`, `phase`, `queue_state`, `approval_state`, `graph_state`,
   `next_gate`, `blocked_count`, `review_needed_count`, `checkpoint_state`,
   `handoff_state`, `updated_at`. One projection consumed by CLI, TUI, and Web UI.
2. **`tasks.project_id` migration** + default project (see §3).
3. **OpenAPI spec + SSE stream** (parity-design Tasks A1, A2) — the contract and
   live channel the web UI consumes. The prior UI's likely instability came from
   talking to an undocumented service; v1 hard-depends on these.
4. **Web UI bundle** under `web/` that `sarathi-desktop` launches at `vite_port`.

---

## 6. OPEN decisions (to confirm before finalizing)

1. **Wiki placement** — top-level for v1 (recommended), or inside a "Knowledge"
   surface from day one?
2. **Inbox/approvals** — fold into Dashboard "Needs You" lane (recommended), or
   keep a dedicated attention surface?
3. **Surface #4 framing** — "Outcomes & Usage" = quality signals + cost
   (recommended), or pure usage/cost for v1?
4. **Multi-workspace** — global top-bar switcher + Workspace-as-managed-page
   (recommended), or a permanent "Workspaces home" landing?

---

## 7. Confirmed requirements (captured)

- Multi-workspace support (operator with several workspaces; switcher in UI).
- Installable app + Web UI + TUI/CLI, all thin clients over one local service.
- Dashboard is Kanban, grouped by project, across the active workspace.
- Task panel = DAG/list + chat on the right; chat thread is persistent.
- Settings, Usage/Outcomes, and Wiki are first-class surfaces.
- Hierarchy: Workspace → (Repos, Projects) → Tasks → units.

---

## 8. Packaging (installable app)

- v1 distribution: one-line installer + Homebrew (parity-design Task E1) gives
  `sarathi`, `sarathi-desktop`, `sarathi-mcp`. `sarathi-desktop` is the app entry.
- Native desktop wrapper (later): wrap the launcher + web bundle in a thin shell
  (Tauri preferred for size, or `pywebview`) so it installs like omnigent's
  desktop app. Service + DB stay local; the shell just hosts the web UI and
  manages the service lifecycle that `desktop.py` already implements.
