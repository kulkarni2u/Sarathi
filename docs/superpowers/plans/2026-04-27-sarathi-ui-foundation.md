# Sarathi UI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first real Sarathi Desktop UI shell from the v2 prototype so Sarathi can dogfood its own app development.

**Architecture:** Add a new `desktop/` Vite React app that is UI-only for this slice, backed by typed mock data shaped like the future local service API. Keep orchestration authority in Python; the UI presents workspace, task, graph, evidence, review, and handoff state without duplicating runtime logic.

**Tech Stack:** Vite, React, TypeScript, CSS modules-by-convention through one focused stylesheet, local mock data.

---

## File Structure

- Create `desktop/package.json`: npm scripts and UI dependencies.
- Create `desktop/index.html`: Vite HTML entry.
- Create `desktop/tsconfig.json`: TypeScript config.
- Create `desktop/vite.config.ts`: Vite React config.
- Create `desktop/src/main.tsx`: React entrypoint.
- Create `desktop/src/App.tsx`: route shell and Sarathi UI components.
- Create `desktop/src/mockData.ts`: typed dogfood data contract.
- Create `desktop/src/styles.css`: visual system and layout.
- Create `desktop/.gitignore`: ignore UI build artifacts and dependencies.

## Task 1: Scaffold Desktop UI Package

- [x] Create `desktop/package.json`, `index.html`, TypeScript config, and Vite config.
- [x] Add `desktop/src/main.tsx` to mount React.
- [x] Add `desktop/.gitignore` for `node_modules` and `dist`.
- [x] Run `npm --prefix desktop install`.
- [x] Run `npm --prefix desktop run build`.

## Task 2: Add Typed Sarathi Mock Data

- [x] Create TypeScript entities for workspace, repo, provider, role, task, subtask, approval gate, evidence, review, event, and message.
- [x] Add `Sarathi App` dogfood workspace data.
- [x] Ensure approval/evidence/review/history entries cross-link through IDs.
- [x] Run `npm --prefix desktop run build`.

## Task 3: Build Workspace-First Shell

- [x] Add transparent left nav grouped by Workspace, Agents, and Operate.
- [x] Add top command bar with `Cmd+K` affordance.
- [x] Add status strip for sessions, SQLite, SSE, provider health, workspace, and repo dirty state.
- [x] Add routes for Workspace, Orchestrator, Inbox, Tasks, Views, Task Studio, Agents, Lifecycle, History, Diagrams, Usage, and Settings.
- [x] Run `npm --prefix desktop run build`.

## Task 4: Build Task Studio Truth Surface

- [x] Add graph/list toggle for subtasks.
- [x] Add selected unit packet inspector.
- [x] Add named approval gates from data.
- [x] Add Messages, Evidence, Review, History, and Handoff tabs.
- [x] Add repository action choices without executing them.
- [x] Run `npm --prefix desktop run build`.

## Task 5: Dogfood Evidence Update

- [x] Update tracker/docs to point at the new UI foundation and plan.
- [x] Record this as the first Sarathi App dogfood slice.
- [ ] Run Python tests if no unrelated failures block them.
- [x] Run UI build.

## Verification Evidence

- `npm --prefix desktop run build` passed on 2026-04-28.
- `npm --prefix desktop audit --omit=dev` passed with `0 vulnerabilities` on 2026-04-28.
- Python tests were not rerun for this UI-only tracker update; run `python -m pytest` before closing any runtime/service tranche.

## Next Task Graph

Canonical follow-up tracker: `docs/superpowers/tasks/2026-04-28-sarathi-ui-task-graph.md`.
