You are the primary orchestrator and implementor for one bounded Sarathi slice.

Repo:
- /Users/sweethome/Work/Skills/Sarathi

Goal:
Implement a real `Learnings` section inside `Knowledge Center` so Sarathi's memory and self-learning loop are visible in-product.

Primary product model:
- `Knowledge Center` = what the workspace knows
- `Skills` = how Sarathi acts
- `Learnings` should connect accepted learnings to proposals, promoted playbooks, and provenance

Scope:
- Add a live `Learnings` section inside Knowledge Center
- Keep the current Knowledge Center IA intact
- Keep changes localized
- Do not redesign unrelated surfaces
- Do not use Claude

Inspect first:
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/KnowledgeCenter.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/apiClient.ts
- /Users/sweethome/Work/Skills/Sarathi/src/service/__init__.py
- /Users/sweethome/Work/Skills/Sarathi/tests/test_reuse_kit.py
- /Users/sweethome/Work/Skills/Sarathi/tests/test_service_api.py
- /Users/sweethome/Work/Skills/Sarathi/docs/superpowers/tasks/2026-05-10-sarathi-desktop-next.md

Important current context:
- Knowledge Center currently has real sections for `Wiki`, `Context`, and `Proposals`
- `Learnings` exists only as an overview/status card right now
- The backend already has:
  - learnings status in the knowledge-center payload
  - accepted-learning promotion into reuse playbooks
  - playbook provenance
- Prefer using existing persisted learning/reuse/provenance data before inventing a new storage model

Acceptance criteria:
1. Knowledge Center has a real `Learnings` section, not only overview copy.
2. The section shows accepted learnings with useful summary fields where available:
   - title or summary
   - source task or event provenance
   - impacted or related assets if derivable
   - promoted playbook/template/view linkage when available
3. Empty state is clear when no learnings are present.
4. The UI is scan-friendly and consistent with the current Sarathi summary-first style.
5. Update the rolling task log with the completed slice and verification lines.

Implementation guidance:
- Extend the knowledge-center payload minimally if needed.
- If adding a new section id is necessary, keep the current Knowledge Center routing model consistent.
- Prefer concise cards/lists over dense prose.
- Avoid broad refactors.

Verification required:
- Run focused tests first if you add or adjust service behavior
- Then run:
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

Deliver in your response:
- changed files
- concise summary
- verification results
- any blockers
