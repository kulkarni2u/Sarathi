# Workflow Patterns

Enables the three most useful patterns for a general-purpose software project.

## Patterns

```yaml
patterns:

  # Classify-And-Act — always on; used by the Route phase.
  classify_and_act:
    enabled: true

  # Fanout-And-Synthesize — on for HIGH complexity tasks.
  fanout_and_synthesize:
    enabled: true
    max_branches: 3

  # Adversarial Verification — independent review before shipping.
  adversarial_verification:
    enabled: true
    verifier_count: 2
    pass_threshold: 2

  # Generate-And-Filter — off; enable for creative / design tasks.
  generate_and_filter:
    enabled: false
    generator_count: 4
    min_score: 0.7

  # Tournament — off; enable when you want best-of-N selection.
  tournament:
    enabled: false
    attempts: 4
    judge_rounds: 2

  # Loop-Until-Done — on; used by the Verify phase auto-recovery.
  loop_until_done:
    enabled: true
    max_iterations: 5
    condition_key: new_findings
```
