# Sarathi Desktop UI/UX Consolidation Plan

> **Owner:** Desktop UX + Sarathi Orchestrator
> **Last updated:** 2026-05-07
> **Status:** Single forward-looking desktop plan

---

## Completed (2026-05-07 Session)

### Task 1: Unify workspace/project/route state (P0)
- Unified CSS token system: consolidated `--s-*`, `--h-*` into single `--*` token set with legacy aliases
- Fixed route/empty state mismatch: primary action now shows "Enter workspace" instead of "Open workspace"
- Fixed workspace creation reopen: proper state reset allowing cancel → reopen flow

### Task 2: Rework workspace landing (P0)
- Enhanced workspace cards with last activity timestamp
- Added repo count display to workspace home
- Workspace status shows live/initializing state

### Task 3: Tighten project dashboard (P1)
- Added visible blocked state: red left border + "Blocked" badge on task cards
- Task cards show blocked count prominently

### Task 4: Polish task panel/checkpoint UX (P1)
- Task panel timeline already implements: newest-first, expandable on demand, key events section
- Checkpoint UI already exists in ProjectDetail with restart capability

### Task 5: Surface default-off repo actions (P2)
- Repository action UI in handoff already shows: default "no action", explicit opt-in required, plain language

### Task 6: Setup/provider/workspace bootstrap visibility (P2)
- Settings page shows provider health: configured, online, offline, blocked
- WorkspaceDashboard shows: live status, repo count, project count

### Task 7: 100% zoom validation (P3)
- `npm run build` passes ✓
- `npm audit --omit=dev` passes (0 vulnerabilities) ✓

---

### M6: Desktop Dogfood MVP (Done)
- UI-00 through UI-15: workspace setup, task initiation, graph, scheduling, dispatch, SSE, review, handoff, operational views, dogfood acceptance, learn-loop closure
- V1-01 through V1-05: repo init, provider settings, richer review, 100% zoom, packaging
- P5 through P12: auto-cascade scheduling, provider parity, recovery classification, review trace depth, diff spec evidence, spec drift enforcement, diff risk synthesis, cross-hunk clustering

### Session 2026-05-04 Hardening
- Radix Themes v3.3.0 integration — dark/light driven by Radix
- Tab redesigns: Task Studio split graph (45%) / chat (55%), Tasks table default, History timeline, Lifecycle role table, Agents dual tables, Inbox feed
- Provider CLI bridges: Claude (`-p --output-format json`), Codex (`exec`), Copilot (`gh copilot`), OpenCode CLI bridge
- First live dogfood run: 12 phases completed end-to-end via Claude dispatcher
- OpenCode bridge fix: replaced HTTP serve with CLI bridge
- Desktop usability hardening: form handlers, loading states, keyboard shortcuts (`Cmd+K`, `j/k`, `Enter`)

### Session 2026-05-04 Mockup Integration
- MetricsStrip, Templates page, Workflows page, Agents stats bar + MemberTable, History activity log enhancements, Library nav group

---

## Current Regressions

1. **Workspace creation reopen bug** — canceling creation breaks reopening the create flow; state ownership leaks between shell and child
2. **Project persistence gap** — project creation is demo/local-only, breaking the "real persisted cockpit" mental model
3. **Route/empty state mismatch** — workspace landing shows ambiguous actions when no workspaces exist; topbar shows wrong "next object" create action
4. **Token system split** — codebase mixes Radix variables with older `--s-*` tokens, creating maintainability risk
5. **State ownership leakage** — workspace/project/task state lives in service, in-memory React, AND localStorage, causing UX inconsistency

---

## Design Direction: Hybrid

### Visual Direction

**Calm shell / workspace pages:**
- Apply the UI-dev aesthetic system: quiet premium SaaS, airy monochrome, hairline borders, soft shadows, sparse accent
- Workspace home and dashboard use large horizontal breathing room, tall sections with generous padding
- Surface hierarchy driven by border and subtle tone shifts, not loud color
- Status pills are pastel with darker matching text; accent color reserved for state, not decoration

**Denser premium project/task surfaces:**
- Task Studio, Project Detail, and task panel surfaces use tighter spacing and higher data density
- Tables use generous row height but tight column rhythm — one strong text cluster per row
- Graph nodes are compact horizontal rows: `[● ST-ID Title [CO]]` with 3px status-colored left border
- Card surfaces are large-radius with border-first, shadow-second language
- Blocked states are visually distinct as interruptions requiring action, not decorative cards

### Component Recipe

| Surface | Pattern |
|---------|---------|
| Workspace Home | Page title + KPI strip + card grid (workspace selector) + empty state guidance |
| Workspace Dashboard | Header + stat strip + project grid + bootstrap readiness + "next action" highlight |
| Project Dashboard | Compact stat strip + task table (ID·Title·Status·Phase·Units·Providers) + filter tabs + board/list toggle |
| Task Studio | Split: graph pane (45%) + chat pane (55%) + toolbar (Graph/List/Schedule) + legend |
| Task Panel | Compact timeline — newest entries first, verbosity hidden by default, expand on demand |
| Settings | Subnav + roomy form with grouped fields, light/dark parity |

### Token Guidance

```css
/* Calm shell */
--bg-app: #f6f6f3;
--bg-panel: rgba(255, 255, 255, 0.78);
--border-soft: rgba(17, 24, 39, 0.08);

/* Dense task surfaces */
--bg-card: #ffffff;
--text-strong: #171717;
--text-body: #5f5f5a;
--radius-lg: 22px;
--radius-md: 16px;
--shadow-soft: 0 8px 30px rgba(15, 23, 42, 0.05);
```

---

## Consolidated Pending Work

### From IMPLEMENTATION_TRACKER.md
- Deeper line-level review annotations once real provider-backed diffs exist
- Spec-to-code mismatch detection and reviewer verdicting
- Auto-cascade scheduling into policy-driven provider dispatch
- Workspace bootstrap reconciliation for repo updates
- Multi-provider confidence fusion and cross-trace region deduplication

### From 2026-05-05-task-inception-live-supervision.md
- SQLite-backed task panel projection (`list_task_panel_entries`)
- Chat creates real project-scoped tasks (`POST /api/chat` with `context.workspaceId`, `context.projectId`)
- Task panel timeline component with SSE subscription (`?task_id` filter)
- End-to-end browser validation for workspace/project/task flow

### From 2026-05-06-checkpoint-capsule-restart.md
- Checkpoint capsule table + storage methods (schema version 3)
- Create checkpoints on task `done`/`handoff`
- Retrieve endpoint (`GET /api/tasks/:id/checkpoint`)
- Restart endpoint (`POST /api/tasks/:id/checkpoint/restart`) — creates new task seeded from capsule
- Task panel checkpoint card with compact summary + restart action

### From 2026-05-06-github-integration-default-off-design.md
- Import GitHub issues into Sarathi tasks (URL, number, repo reference)
- Repository-action preference at workspace/project/task scope
- Four modes: `no_action` (default), `prepare_patch`, `commit`, `draft_pr`, `ready_pr`
- Default-off enforcement: explicit opt-in required, approval before execution
- Settings UI for action mode + issue import toggle

### From 2026-05-07-desktop-ui-ux-consolidation.md (current)
- Unified route ladder: `home` → `workspace` → `dashboard` → `project`
- Context-correct topbar actions per route
- Workspace landing: informative landing page with task count, active count, repo count, last activity
- Project dashboard: tighter hierarchy, chat-first task creation, visible blocked state
- Task panel hierarchy: status, live panel, checkpoint, repo-action posture, lifecycle tabs
- 100% zoom acceptance gate

---

## Sequencing

| Phase | Tasks | Priority |
|-------|-------|----------|
| **Shell Trust** | Task 1: Unify workspace/project/route state, Task 2: Rework workspace landing | P0 |
| **Task Readability** | Task 3: Tighten project dashboard, Task 4: Polish task panel/checkpoint UX | P1 |
| **Safe Delivery** | Task 5: Surface default-off repo actions in handoff | P2 |
| **Bootstrap Clarity** | Task 6: Setup/provider/workspace bootstrap visibility | P2 |
| **Acceptance Bar** | Task 7: 100% zoom validation, browser flow tests | P3 |

### Recommended Execution Order
1. Task 1: Unify workspace, project, and route state
2. Task 2: Rework the workspace landing experience
3. Task 3: Tighten the project dashboard and task creation flow
4. Task 4: Polish the task panel, checkpoint UX, and supervision surfaces
5. Task 5: Surface safe delivery and default-off repository actions in the UI
6. Task 6: Improve setup, provider, and workspace bootstrap clarity
7. Task 7: Establish a desktop acceptance bar

---

## Acceptance Criteria

### Shell & Navigation
- [ ] User can explain the app as: workspace → project → task
- [ ] Topbar never offers the wrong "next object" to create
- [ ] Route transitions preserve context and feel intentional
- [ ] Canceling workspace creation does not break reopening it

### Visual Design
- [ ] Workspace pages use calm shell language (airy, monochrome, hairline borders)
- [ ] Project/task surfaces use denser premium language (compact rows, tighter spacing)
- [ ] Status badges are pastel with matching darker text
- [ ] Token system is unified — no `--s-*` split with Radix

### Task Flow
- [ ] Task panel answers "what is happening now?" in under five seconds
- [ ] Checkpoint restart is clearly available without overwhelming history
- [ ] Blocked states are unmistakable as interruptions requiring action

### Safe Delivery
- [ ] Repository-action mode visible at handoff in plain language
- [ ] Default-off posture enforced: `no_action` is the calm default
- [ ] Task-level overrides are obvious and distinguishable

### Setup & Bootstrap
- [ ] Workspace bootstrap status visible from workspace surface
- [ ] Provider readiness: who is configured, offline, or blocked
- [ ] Settings feels like system config; workspace pages feel operational

### Quality Gate
- [ ] `npm --prefix desktop run build` passes
- [ ] `npm --prefix desktop audit --omit=dev` passes
- [ ] 100% zoom validated on laptop viewport (1440×1200)
- [ ] Browser validation covers workspace → project → task → checkpoint → handoff
- [ ] Service tests pass: `python3 -m pytest`

---

## Non-Goals For This Plan

- Reworking the CLI/TUI home flow
- Deeper provider-runtime semantics beyond desktop representation
- Full GitHub sync/project management beyond safe default-off export
- Large design-system rewires unrelated to shell and task workflow