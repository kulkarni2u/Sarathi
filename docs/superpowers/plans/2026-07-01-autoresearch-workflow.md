# Autoresearch Workflow

## Goal

Add a first-class Sarathi workflow for lightweight autoresearch: pre-register a hypothesis, attach evidence, preserve negative results, and record a verdict as an append-only artifact.

## Scope

- Store experiments in `.sarathi/autoresearch.jsonl`.
- Support evidence tiers: `MINE`, `MICRO`, and `FULL`.
- Keep records append-only so learnings survive context compaction and agent handoffs.
- Expose the workflow through `sarathi autoresearch`.

## Implementation

1. Add `AutoresearchStore` in `src/runtime/autoresearch.py`.
2. Export the store and artifact dataclasses from `src/runtime`.
3. Add CLI subcommands:
   - `register`
   - `evidence`
   - `verdict`
   - `list`
4. Cover runtime replay and CLI behavior with tests.

## Deferred

- Link experiments to concrete task IDs and phase results.
- Surface active experiments in the desktop UI.
- Add optional NCP write-through for shared cross-agent research memory.
