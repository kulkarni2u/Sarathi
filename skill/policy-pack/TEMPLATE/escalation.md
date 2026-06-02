# Escalation Policy

## [TEMPLATE] Retry & Escalation Rules

> Replace with your team's escalation policies.

---

## Retry Budgets by Phase

```yaml
phases:
  requirements:
    max_attempts: 2
    backoff_multiplier: 1.0

  implementation:
    max_attempts: 3
    backoff_multiplier: 1.5

  testing:
    max_attempts: 2
    backoff_multiplier: 1.0

  review:
    max_attempts: 3
    backoff_multiplier: 1.5
```

---

## Severity Classification

### Minor Issues
- Stylistic concerns
- Non-blocking suggestions
- Documentation gaps
- Test coverage below target (but above minimum)

### Major Issues
- Functional bugs
- Security concerns (non-critical)
- Breaking API changes
- Performance regressions
- Test coverage below minimum

### Blocking Issues
- Security vulnerabilities
- Data loss risks
- Critical bugs
- Complete spec deviation

---

## Token Budget

```yaml
token_budget:
  per_task:
    soft_limit: 100000
    hard_limit: 200000

  per_phase:
    requirements: 15000
    implementation: 50000
    testing: 25000
    review: 10000
```

---

## Time Budget

```yaml
time_budget:
  per_task:
    soft_limit_minutes: 30
    hard_limit_minutes: 60

  per_phase:
    requirements: 5
    implementation: 20
    testing: 10
    review: 5
```

---

## Escalation Actions

### When Budget Exceeded (Soft Limit)
1. Pause and re-evaluate scope
2. Consider simplifying approach
3. Request human input

### When Budget Exceeded (Hard Limit)
1. Log the issue
2. Surface to human for decision
3. Options: continue_anyway / skip / substitute

### When Blocked
1. Document the block
2. Check for substitution options
3. Surface immediately

---

## Severity Response Matrix

| Severity | Retry Budget | Token Budget | Time Budget | Action |
|----------|--------------|--------------|-------------|--------|
| Minor | Full | Soft only | Soft only | Log & continue |
| Major | Full | Full | Soft only | Review at boundary |
| Blocking | N/A | N/A | N/A | Escalate immediately |

---

## Human Escalation Triggers

[TEMPLATE: Define explicit triggers for human escalation]

- More than X attempts on same issue
- Token usage exceeds Y% with no progress
- Security issue discovered
- [TEMPLATE: Add more triggers]