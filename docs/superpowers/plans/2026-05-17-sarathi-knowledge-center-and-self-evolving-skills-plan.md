# Sarathi Knowledge Center And Self-Evolving Skills Plan

Date: 2026-05-17

Status: Proposed implementation plan

Related spec:

- `../specs/2026-05-17-sarathi-knowledge-center-and-self-evolving-skills-spec.md`

## 1. Objective

Recover the original Sarathi direction around skills, workspace memory, wiki, and self-learning without sacrificing the organized-orchestrator gains already shipped.

## 2. Workstreams

### Workstream A: Product And UX

Owner skills:

- `product-owner`
- `product-designer`
- `ui-dev`

Deliverables:

- knowledge center IA
- screen inventory
- proposal inbox flows
- context inspector UX
- skill pack studio UX

### Workstream B: Python Runtime And Service

Owner skill:

- `python-architect`

Deliverables:

- schema additions
- service routes
- vault sync projections
- retrieval and context-bundle plumbing
- proposal generation pipeline

### Workstream C: Desktop And Node Surfaces

Owner skill:

- `nodejs-architect`

Deliverables:

- new routes and pages
- editors and diff viewers
- context-bundle inspector
- skill registry UI
- browser QA coverage

### Workstream D: JVM And Enterprise Repo Support

Owner skill:

- `java-architect`

Deliverables:

- JVM repository ingestion strategy
- Gradle/Maven metadata extraction plan
- future sidecar/export seam for enterprise environments

## 3. Recommended Milestones

### Milestone 1: Knowledge Foundation

Goal:

Make workspace knowledge visible and durable before introducing self-evolution.

Backend:

- add `knowledge_documents` table
- add `skill_packs` table
- add `knowledge_sources` projection metadata
- add service endpoints for knowledge center summary and wiki listing

Frontend:

- add `Knowledge Center` route
- show workspace guide health, wiki coverage, learnings, skill count, proposal count
- add read-only wiki browser

Vault:

- ensure `.sarathi/` structure exists consistently
- project `SARATHI.md`, wiki pages, and learnings into the knowledge center

Acceptance criteria:

- knowledge center home loads for every workspace
- user can open workspace guide and wiki pages
- provenance for generated knowledge is visible

### Milestone 2: Skills Pack Studio

Goal:

Turn skills into governed workspace assets instead of loose files.

Backend:

- add `skill_versions` and `skill_proposals`
- index installed local skill packs and workspace-local skill packs
- expose role-to-skill mappings

Frontend:

- add `Skills` route
- skill list, detail view, version info, provenance, usage hints
- show policy impact and linked roles

Acceptance criteria:

- user can inspect installed skill packs from Sarathi
- workspace-local skills are distinguishable from global/shared skills
- role mappings are visible

### Milestone 3: Proposal-Driven Evolution

Goal:

Make self-learning real without making it unsafe.

Backend:

- add `learning_proposals`
- generate wiki and skill proposals from accepted learnings
- persist diffs and evidence refs
- approval and rejection endpoints

Frontend:

- add `Proposals` route
- proposal inbox with filters
- diff review for wiki and skills
- approve/reject actions with audit trail

Acceptance criteria:

- accepted learnings can create proposals
- no wiki or skill mutation applies silently
- every proposal shows evidence refs and impacted assets

### Milestone 4: Knowledge-Aware Context Compiler

Goal:

Feed agents better context without transcript bloat.

Backend:

- extend `ContextCompiler` to retrieve from wiki, SARATHI.md, learnings, skill packs, and approved artifacts
- emit `context_bundle` artifacts with source summaries and token posture

Frontend:

- add `Context Inspector` route or panel
- show what sources were used, why, and what was omitted

Acceptance criteria:

- user can inspect context bundles before or after dispatch
- retrieval sources are visible and attributable
- token budget usage is understandable

## 4. Suggested File Targets

Python and service:

- `src/service/__init__.py`
- `src/storage/__init__.py`
- `src/runtime/context.py`
- `src/runtime/output_index.py`
- `src/runtime/learning.py`
- `src/policy/compiler.py`

Desktop and Node:

- `desktop/src/App.tsx`
- `desktop/src/apiClient.ts`
- `desktop/src/pages/KnowledgeCenter.tsx`
- `desktop/src/pages/Wiki.tsx`
- `desktop/src/pages/Skills.tsx`
- `desktop/src/pages/Proposals.tsx`
- `desktop/src/pages/ContextInspector.tsx`
- `desktop/scripts/validate-task-panel.mjs`

Vault projections:

- `.sarathi/SARATHI.md`
- `.sarathi/wiki/*`
- `.sarathi/skills/registry.json`
- `.sarathi/proposals/*`
- `.sarathi/context/bundles/*`

## 5. Schema Additions

Recommended new tables:

- `knowledge_documents`
- `knowledge_document_versions`
- `skill_packs`
- `skill_versions`
- `skill_proposals`
- `learning_proposals`
- `context_bundles`
- `retrieval_hits`

## 6. Testing Strategy

Python:

- retrieval selection tests
- proposal generation tests
- vault sync tests
- approval flow tests
- context bundle regression tests

Desktop:

- knowledge center browser flow
- skill library inspection flow
- proposal review flow
- context inspector flow

End-to-end:

- workspace -> knowledge center -> proposal -> approval -> dispatch with compiled context

## 7. Teaming Model

Recommended delegation:

- Product definition: `product-owner`
- UX and IA: `product-designer`
- visual implementation: `ui-dev`
- backend/runtime: `python-architect`
- desktop/tooling: `nodejs-architect`
- JVM enterprise adapters: `java-architect`

## 8. First Slice To Build

Build this first:

1. read-only `Knowledge Center`
2. read-only `Wiki browser`
3. `Skills registry` read path
4. `Context bundle` persistence and inspector skeleton

Why:

- it makes the missing product direction visible immediately
- it creates the object model before mutation flows
- it gives a clean base for later self-evolution

## 9. Risks

- overbuilding a docs product instead of a governed knowledge system
- mixing editable wiki content with generated projections too early
- introducing self-evolution before proposal review is solid
- creating too many routes without a clear navigation model
- letting skills remain file-only even after adding a UI

## 10. Decision

Sarathi should proceed as:

- orchestrator first
- knowledge center second
- self-evolving skills third

That preserves the product trust already earned while bringing the original vision back into the roadmap in a deliberate way.
