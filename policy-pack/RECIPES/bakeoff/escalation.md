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
```
