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
