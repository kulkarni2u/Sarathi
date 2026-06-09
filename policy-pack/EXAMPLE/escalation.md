# Escalation Policy

Retry budgets and auto-fix limits for Verify/Review quality loops.

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
```
