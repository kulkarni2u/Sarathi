# Sarathi Minimal Context Compiler Architecture

Date: 2026-05-14
Status: Active

## Decision

Defer `S3`, `MCP`, `Redis`, `Postgres`, and vector infrastructure for now.

Build Sarathi's token-efficiency architecture first with:

- SQLite as canonical state
- workspace filesystem and Git as artifact storage
- SSE for live operator updates
- provider adapters as internal execution boundaries
- a first-class Context Compiler that builds compact, role-specific context packs

## Why

Sarathi's current bottleneck is not remote infrastructure.

It is:

- context bloat
- agents rediscovering task truth
- weakly standardized input/output contracts
- insufficiently explicit compiled context artifacts

## Current Foundation

Sarathi already has:

- durable tasks, subtasks, approvals, dispatches, evidence, reviews, handoffs, and lifecycle events
- compact task manifests
- task packets on subtasks
- provider-agnostic dispatch requests and responses
- token usage normalization

## Minimal Architecture

### Canonical state

- SQLite tables for orchestration truth
- lifecycle events as the transition log
- provider dispatch metadata as runtime trace

### Artifact storage

- workspace files
- Git diff and repository state
- local artifact URIs
- evidence references linked to tasks and subtasks

### Context Compiler

Input sources:

- task metadata
- subtask task packet
- acceptance criteria
- prior review summaries
- prior evidence summaries
- relevant file hints

Output:

- compact `agent_input`
- token-budget-aware compilation metadata
- source artifact references
- explicit exclusion of full chat history by default

### Retrieval

Keep retrieval local-first:

- task evidence
- review runs
- learnings
- workspace docs
- repository hints

No vector database until we can prove naive local retrieval is insufficient.

## Immediate Follow-On Work

1. Route more execution paths through the Context Compiler, not just service-backed subtask dispatch.
2. Add artifact indexing for `files_changed`, `tests_run`, `known_risks`, and `review_findings`.
3. Standardize `agent_output` persistence for implementor, reviewer, and QA-style roles.
4. Add context-pack inspection surfaces in Task Studio and CLI status.
5. Add stricter per-role token budgets in policy/config, with visible degradation when trimming occurs.
