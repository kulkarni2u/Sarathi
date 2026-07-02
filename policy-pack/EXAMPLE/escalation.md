# Escalation Policy

Retry budgets and auto-fix limits for Verify/Review quality loops.

When a task's accumulated token usage reaches `max_total_tokens`, the engine
pauses the task (resumable via `sarathi resume`) instead of letting it burn
through the remaining phases unchecked.

```yaml
retry_budgets:
  verify: 2
  review: 1

severity_thresholds:
  block_on: high
  warn_on: medium

auto_fix:
  attempts: 1
  allowed_phases:
    - Verify
    - Elegance

auto_fix_attempts: 1

auto_fix_policies:
  lint: auto
  formatting: auto
  logic: human_review

budget:
  max_total_tokens: 200000
  warn_ratio: 0.8
  on_exhausted: pause

# Tunes src/evolve.py's Evolver: how far a measured quality signal must
# deviate from its per-task-class baseline before a policy proposal fires
# (deviation_threshold), the pattern pass-rate required for promotion
# (pass_gate), and the minimum repeated-signal count before a
# repeated-failure/escalation/hotspot proposal is generated (proposal_gate).
# Values below reproduce Evolver's built-in defaults; override any subset to
# tune sensitivity per policy pack.
learn_evolve:
  deviation_threshold: 0.1
  pass_gate: 0.8
  proposal_gate: 2
```
