# Workflow Patterns

Enables the patterns this recipe pack relies on: fan-out-and-synthesize (for
the parallel branch work) and adversarial-verification (for the JUDGE node).

## Patterns

```yaml
patterns:

  # Classify-And-Act — always on; used by the Route phase.
  classify_and_act:
    enabled: true

  # Fanout-And-Synthesize — required: the recipe fans branch work across providers.
  fanout_and_synthesize:
    enabled: true
    max_branches: 2

  # Adversarial Verification — required: the JUDGE node reviews before merge.
  adversarial_verification:
    enabled: true
    verifier_count: 2
    pass_threshold: 2

  # Generate-And-Filter — off.
  generate_and_filter:
    enabled: false
    generator_count: 4
    min_score: 0.7

  # Tournament — off.
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
