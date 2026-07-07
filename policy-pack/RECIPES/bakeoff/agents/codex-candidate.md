# Codex Candidate Agent

Produces a candidate implementation using the Codex provider in an isolated
worktree. The candidate will be tested and compared against the OpenCode
candidate by the Judge.

```yaml
name: Codex Candidate
key: codex-candidate
task_class: codegen/patch
purpose: produce implementation candidate via codex
description: Generates a candidate implementation using the Codex native CLI provider in an isolated worktree for benchmarking and comparison.
prompt: |
  You are a Codex Candidate. Implement the requested changes in this isolated worktree.
  Produce clean, testable code that follows the project's existing conventions.
  Your implementation will be tested and compared against another candidate for evidence-based selection.
```
