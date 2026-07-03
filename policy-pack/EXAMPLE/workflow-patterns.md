# Workflow Patterns

Declares which of the six dynamic workflow patterns are active for this
policy pack. EXAMPLE is a conservative reference pack: only the always-on
classification pattern is enabled here. Enable additional patterns as a
project's task mix grows — see `skill/policy-pack/TEMPLATE/workflow-patterns.md`
for the full pattern reference and NCP interaction notes, or
`policy-pack/RECIPES/*/workflow-patterns.md` for pattern combinations tuned
to specific graph shapes (fan-out, adversarial JUDGE loops, etc.).

## Patterns

```yaml
patterns:

  # Classify-And-Act — always on; used by the Route phase.
  classify_and_act:
    enabled: true

  # Fanout-And-Synthesize — off; enable to spawn parallel workers for HIGH complexity tasks.
  fanout_and_synthesize:
    enabled: false
    max_branches: 4          # Maximum parallel branches to spawn

  # Adversarial Verification — off; enable for independent-verifier review before shipping.
  adversarial_verification:
    enabled: false
    verifier_count: 3        # Number of independent verifiers
    pass_threshold: 2        # Minimum verifiers that must pass

  # Generate-And-Filter — off; enable for creative / design tasks.
  generate_and_filter:
    enabled: false
    generator_count: 4       # Number of candidates to generate
    min_score: 0.7           # Minimum quality score to keep a candidate

  # Tournament — off; enable when you want best-of-N selection.
  tournament:
    enabled: false
    attempts: 4              # Number of competing attempts
    judge_rounds: 2          # Rounds of pairwise judgment

  # Loop-Until-Done — off; enable for auto-recovery retry loops (e.g. Verify).
  loop_until_done:
    enabled: false
    max_iterations: 5        # Hard cap on loop iterations
    condition_key: new_findings  # Output key checked for loop continuation
```
