# Review Policy

What the Review phase checks and when it hard-stops.

```yaml
max_rounds: 3
min_coverage: 80
hard_stop_rounds: 5
devil_advocate_depth: 1

review_criteria:
  - spec_met
  - code_quality_acceptable
  - no_blocking_issues

evidence_requirements:
  - tests_pass
  - no_regressions

# Confidence-gate configuration for Brainstorm/Plan evidence checks
# (see src/runtime/quality_policy.py:GateEvidencePolicy). Any key omitted
# here falls back to the default shown — these are also the engine's
# built-in defaults, so leaving this whole block out is equivalent to
# what's spelled out below.
gate_thresholds:
  Brainstorm: 0.80
  Plan: 0.90

# Phases (by Phase.value) eligible for the bounded single-retry gate loop.
gate_retry_phases:
  - Brainstorm
  - Plan

# Remediation guidance surfaced to providers when a gate fails on a
# specific missing-evidence key. Keys not listed here get no remediation
# text attached to the gate_result artifact.
gate_remediation:
  alternative_approaches_considered: >-
    Brainstorm did not evaluate multiple approaches; ask the provider to set
    evidence.alternative_approaches_considered after considering at least three alternatives.
  risks_identified: >-
    Brainstorm did not identify risks; ask the provider to set evidence.risks_identified
    after enumerating potential failure modes or concerns.
  success_criteria_defined: >-
    Brainstorm has no explicit success criteria; ask the provider to set
    evidence.success_criteria_defined after articulating measurable acceptance conditions.
  reversibility_assessed: >-
    Brainstorm did not assess how the change could be rolled back; ask the provider to set
    evidence.reversibility_assessed after considering reversibility.
  checkpoint_list: >-
    Plan has no checkpoint list; the provider should return a sequenced step list and set
    evidence.checkpoint_list.
  dependency_map: >-
    Plan has no dependency map; the provider should return outputs.checkpoints/dependencies
    and set evidence.dependency_map.
  rollback_plan: >-
    Plan has no rollback plan; the provider should document a recovery procedure and set
    evidence.rollback_plan.
```

## Measured JUDGE scoring (FANOUT bake-offs)

When a JUDGE node runs after a FANOUT (see `src/runtime/graph_executor.py`'s
`NodeType.JUDGE` handling and `src/runtime/judge_scoring.py`), it can be
handed a deterministic per-branch scorecard alongside the branch outputs it
already sees — measured signals, not vibes. `weights` says how much each
measured signal counts (must sum to ~1.0, same convention as
`conventions.md`'s `confidence_weights`); `prefer` says whether a bigger
(`high`) or smaller (`low`) raw value is better for that signal. Signals are
min-max normalized *within one bake-off* (across that JUDGE's branches only),
so weights stay meaningful across dollars, milliseconds, and 0..1 rates alike.

Leaving this whole block out disables scoring entirely: no scorecard is
assembled, no bake-off outcome is recorded, and JUDGE dispatch is
byte-for-byte what it is without this section.

```yaml
judge_scoring:
  weights:
    test_pass_rate: 0.4  # did the branch's own verification succeed?
    blast_radius: 0.2    # workspace_delta.change_count — smaller diffs score higher
    cost_usd: 0.2        # UsageRecord.cost_usd for the branch's dispatch
    latency_ms: 0.2      # provider_duration_ms for the branch's dispatch
  prefer:
    test_pass_rate: high
    blast_radius: low
    cost_usd: low
    latency_ms: low
  # Opt-in: when local verification already leaves exactly one candidate
  # with test_pass_rate == 1.0 and every other candidate at 0.0 (no
  # ambiguity, no missing signals), skip the JUDGE dispatch entirely and
  # declare that candidate the winner deterministically — see
  # lone_verified_survivor() in src/runtime/judge_scoring.py. Any tie, any
  # branch with an unmeasured test_pass_rate, or more than one passing
  # branch still gets a real JUDGE dispatch.
  auto_select_lone_survivor: true
```

Every judged bake-off's winner (provider, task_class, weighted_score) is
appended to `.sarathi/bakeoff_history.json` in the workspace root (atomic
writes, same pattern as `provider_health.json`). Once one provider
accumulates enough judged wins for a task class (`Evolver.BAKEOFF_MIN_WINS`
judged bake-offs at or above `Evolver.BAKEOFF_MIN_WIN_RATE` win rate —
defaults 5 wins / 70%, configurable via `escalation.md`'s `learn_evolve`
block: `bakeoff_min_wins`, `bakeoff_min_win_rate`), `src/evolve.py` proposes
routing that task class to the winning provider in `model-routing.md`.
