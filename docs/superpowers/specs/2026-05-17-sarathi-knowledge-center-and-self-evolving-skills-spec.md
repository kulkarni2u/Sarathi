# Sarathi Knowledge Center And Self-Evolving Skills Spec

Date: 2026-05-17

Owner role: Product Owner

Status: Proposed correction to roadmap emphasis

## 1. Why This Exists

Sarathi's original product intent included four tightly related ideas:

- portable skills
- workspace memory
- workspace wiki and vault
- self-evolving learn/evolve loops

In the push to make Sarathi product-ready, the team correctly prioritized the organized orchestrator path:

- control tower
- PRD-to-handoff delivery spine
- governance depth
- reusable views and templates

That made Sarathi trustworthy, but it left the knowledge system under-productized.

This spec corrects that sequencing drift.

## 2. Strategic Position

Sarathi should compete with:

- Hermes Agent on memory, skills, learning loops, and operator continuity
- AgentField on typed runtime discipline, control-plane clarity, and observable agent infrastructure

Sarathi should not copy either product directly.

Sarathi should combine:

- governed delivery orchestration
- workspace knowledge as durable operating context
- reusable skill packs tied to policy and evidence
- self-improving behavior through reviewable proposals

### Winning position

Hermes is strongest as a self-improving persistent agent.

AgentField is strongest as an AI backend and execution control plane.

Sarathi should be strongest as the governed workspace intelligence layer that turns knowledge, skills, learnings, and delivery into one inspectable operating model.

## 3. Product Thesis

Sarathi should become the place where a serious team's AI operating knowledge lives.

The user should be able to:

- attach repositories and create a workspace
- generate and curate a workspace wiki
- inspect and edit AI-readable workspace guidance
- manage skill packs and role instructions
- see what knowledge the next agent will actually receive
- review self-learning proposals before they mutate wiki, skills, or policy
- reuse accepted knowledge and skill improvements across future work

## 4. Principles

- Knowledge is a first-class workspace asset, not hidden prompt residue.
- Memory must be inspectable, attributable, and scoped.
- Skills are durable behavior packs, not ad hoc prompt snippets.
- Self-improvement must be proposal-driven and reviewable.
- The wiki, skill pack, and policy pack are separate but linked products.
- Context sent to agents must be explicit and budgeted.
- Vault files remain portable and AI-readable.

## 5. New Product Pillars

### Pillar A: Workspace Knowledge Center

Create a first-class workspace knowledge home that unifies:

- SARATHI.md
- workspace wiki
- learnings.md
- architecture and coding standards
- repository summaries
- accepted decisions
- exported task and handoff references

This is not a generic docs browser. It is the source of reusable workspace intelligence.

### Pillar B: Skills Pack Studio

Create a product surface for:

- installed workspace skills
- global and workspace-local skill packs
- skill provenance
- role mappings
- skill evolution proposals
- policy constraints affecting skill use

This should make Sarathi's skills feel like governed product assets.

### Pillar C: Reviewable Self-Evolution

Use accepted learnings to generate proposals for:

- wiki updates
- skills updates
- policy annotations
- routing hints
- context-pack improvements

No automatic mutation of trusted workspace assets without visible diff and approval.

### Pillar D: Knowledge-Aware Context Compiler

Extend the context compiler so it can retrieve from:

- wiki pages
- SARATHI.md
- learnings
- accepted handoffs
- skill instructions
- repository summaries

The compiler should explain what it selected and why.

## 6. Canonical Objects To Add Or Deepen

- `knowledge_document`
- `wiki_page`
- `workspace_guide`
- `skill_pack`
- `skill_version`
- `skill_proposal`
- `learning_proposal`
- `knowledge_snippet`
- `context_bundle`
- `retrieval_hit`

## 7. Core User Flows

### 7.1 Knowledge Center Home

The user opens a workspace and sees:

- workspace guide health
- wiki coverage
- accepted learnings
- pending proposals
- installed skill packs
- most-used context sources

### 7.2 Wiki And Workspace Guide

The user can:

- browse wiki sections
- edit approved workspace knowledge
- inspect provenance for generated content
- review diffs before apply when content is system-proposed

### 7.3 Skills Pack Studio

The user can:

- see which skills are available in the workspace
- inspect what each skill influences
- compare versions
- review proposed updates
- approve or reject skill evolution

### 7.4 Proposal Inbox

The user can review all self-evolution proposals in one place:

- wiki proposal
- skill proposal
- policy note proposal
- routing hint proposal

Each proposal must show:

- source learnings
- evidence refs
- impacted assets
- diff preview
- risk level

### 7.5 Context Pack Inspector

Before or after dispatch, the user can inspect:

- objective
- selected knowledge sources
- selected snippets
- selected skill guidance
- token budget
- what was omitted

## 8. Product Surfaces

New or expanded desktop surfaces:

- Knowledge Center
- Wiki
- Skills
- Proposals
- Context Inspector

Expanded CLI surfaces:

- `sarathi workspace knowledge`
- `sarathi skills`
- `sarathi proposals`
- `sarathi context`

Expanded vault structure:

```text
.sarathi/
  workspace.json
  SARATHI.md
  wiki/
    overview.md
    architecture.md
    repositories.md
    coding-standards.md
    guidelines.md
    decisions.md
    skills.md
  skills/
    registry.json
    proposals/
  learnings.md
  proposals/
    wiki/
    skills/
    policy/
  context/
    bundles/
```

## 9. Competitive Response

### Match Hermes On

- skills as a durable system
- long-lived workspace memory
- cross-session context continuity
- self-improvement loop

### Match AgentField On

- typed objects
- clear runtime contracts
- observable execution and provenance
- explicit control-plane semantics

### Differentiate Beyond Both

- PRD-to-handoff traceability
- policy-backed review of evolving knowledge
- workspace wiki and skills tied directly to delivery history
- evidence-backed context compilation for real engineering work

## 10. Release Sequence

### Release K1: Knowledge Foundation

- knowledge center home
- workspace guide and wiki browser
- vault sync hardening
- read-only context retrieval visibility

### Release K2: Skills Pack Studio

- skill registry
- installed skill inspection
- workspace-local skill pack management
- role/skill mapping views

### Release K3: Proposal-Driven Evolution

- learning proposals
- wiki diffs
- skill diffs
- approval and rejection flows

### Release K4: Knowledge-Aware Dispatch

- context compiler retrieval from knowledge sources
- context-bundle inspector
- token-budget-aware source selection

## 11. Acceptance Criteria

- A workspace has a first-class knowledge center surface.
- A user can inspect and edit AI-readable workspace guidance without leaving Sarathi.
- Accepted learnings can generate reviewable wiki and skill proposals.
- Skills are visible as versioned workspace assets, not only files on disk.
- The user can inspect which knowledge and skill sources shaped a context bundle.
- No self-evolving change applies silently to trusted workspace assets.

## 12. Out Of Scope For This Slice

- hosted multi-tenant knowledge sync
- fully autonomous self-modifying skills without review
- vector database expansion as a prerequisite
- generic public marketplace for third-party skill packs
- replacing the existing control-tower roadmap with a chat-first memory product
