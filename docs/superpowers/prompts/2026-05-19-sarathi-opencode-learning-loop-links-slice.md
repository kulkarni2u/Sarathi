You are the primary orchestrator and implementor for one bounded Sarathi slice.

Repo:
- /Users/sweethome/Work/Skills/Sarathi

Goal:
Close the next learning-loop gap by linking Learnings back into Task Studio and Proposals.

This slice should do two things:
1. Show `related learnings` on the task surface when a task has a matching accepted learning.
2. Show lightweight learning-source linkage on proposals when a proposal can be traced back to accepted learning context.

Primary intent:
- Learnings should not be a dead library.
- Operators should be able to see that a task or proposal is connected to durable prior learning without reconstructing it manually.

Inspect first:
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/ProjectDetail.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/Proposals.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/pages/KnowledgeCenter.tsx
- /Users/sweethome/Work/Skills/Sarathi/desktop/src/apiClient.ts
- /Users/sweethome/Work/Skills/Sarathi/src/service/__init__.py
- /Users/sweethome/Work/Skills/Sarathi/tests/test_reuse_kit.py
- /Users/sweethome/Work/Skills/Sarathi/tests/test_service_api.py
- /Users/sweethome/Work/Skills/Sarathi/docs/superpowers/tasks/2026-05-10-sarathi-desktop-next.md

Scope constraints:
- Keep changes localized.
- Prefer using existing accepted-learning data and evidence refs before inventing new persistence.
- Do not redesign unrelated surfaces.
- Do not use Claude.

Acceptance criteria:
1. Task Studio shows a compact `Related learnings` surface when the selected task matches accepted learning context.
2. The related-learning surface is summary-first and clearly secondary to the main task work.
3. Proposals show lightweight learning-source linkage when derivable from existing data.
4. Empty-state behavior remains clean when no matches exist.
5. Update the rolling task log with the completed slice and verification lines.

Implementation guidance:
- A simple and valid matching strategy is acceptable, for example matching accepted-learnings `task_id` or evidence/task refs already present in proposal data.
- Prefer one compact task-side card and one small proposal-side annotation over a broad redesign.
- Keep the language operator-friendly and provenance-aware.

Verification required:
- Run focused tests first if you change service behavior
- Then run:
  - `npm --prefix desktop run build`
  - `BASE_URL=http://127.0.0.1:5173 CLEANUP_DB_PATH=true node desktop/scripts/validate-task-panel.mjs`

Deliver in your response:
- changed files
- concise summary
- verification results
- any blockers
