# Escalation Policy

## FastAPI Project Retry & Escalation Rules

---

## Retry Budgets by Phase

```yaml
phases:
  requirements:
    max_attempts: 2
    backoff_multiplier: 1.0
    examples:
      - "Clarifying API spec"
      - "Schema design iteration"

  implementation:
    max_attempts: 3
    backoff_multiplier: 1.5
    examples:
      - "Initial endpoint implementation"
      - "Service layer logic"

  testing:
    max_attempts: 2
    backoff_multiplier: 1.0
    examples:
      - "Unit test for service"
      - "Integration test for route"

  review:
    max_attempts: 3
    backoff_multiplier: 1.5
    examples:
      - "Review feedback iteration"
      - "Addressing comments"
```

---

## Severity Classification

### Minor Issues
- Stylistic concerns (Ruff violations)
- Docstring improvements
- Suggestion not implementation
- Test coverage below target (80%) but above minimum (70%)

### Major Issues
- Functional bug in handler
- Security concern (non-critical)
- Breaking schema change
- Performance regression (N+1 query)
- Test coverage below minimum (80%)
- Missing type hints

### Blocking Issues
- Security vulnerability (injection, auth bypass)
- Data loss risk
- Unhandled exception crashes app
- Complete spec deviation
- Secrets in code
- Migration causes data loss

---

## Token Budget

```yaml
token_budget:
  per_task:
    soft_limit: 80000
    hard_limit: 150000

  per_phase:
    requirements: 10000
    implementation: 40000
    testing: 20000
    review: 10000

  by_complexity:
    low: 20000
    medium: 60000
    high: 120000
```

---

## Time Budget

```yaml
time_budget:
  per_task:
    soft_limit_minutes: 25
    hard_limit_minutes: 45

  per_phase:
    requirements: 5
    implementation: 15
    testing: 8
    review: 5

  by_complexity:
    quick_fix: 10 min
    medium_effort: 25 min
    major_undertaking: 45 min
```

---

## Escalation Actions

### When Budget Exceeded (Soft Limit)
1. Pause and re-evaluate scope
2. Consider simplifying approach
3. Request human input on proceed/simplify

### When Budget Exceeded (Hard Limit)
1. Log the issue with context
2. Surface to human for decision
3. Options: continue_anyway / skip / substitute

### When Blocked
1. Document the block
2. Check for substitution options
3. Surface immediately (no waiting)

---

## Severity Response Matrix

| Severity | Retry Budget | Token Budget | Time Budget | Action |
|----------|--------------|--------------|-------------|--------|
| Minor | Full | Soft only | Soft only | Log & continue |
| Major | Full | Full | Soft only | Review at boundary |
| Blocking | N/A | N/A | N/A | Escalate immediately |

---

## Python/FastAPI-Specific Triggers

### Auto-Escalate Immediately
- Exception in `__init__.py` or core module
- Migration error
- Breaking change to shared schema
- Auth vulnerability detected
- Secrets committed

### Python-Specific Budget Adjustments
- Alembic migration: +50% time budget
- Pydantic schema changes: standard budget
- Async implementation: +25% complexity
- Database queries: track separately

---

## Human Escalation Triggers

- More than 3 attempts on same issue
- Token usage exceeds 70% with no working code
- Security issue discovered
- Breaking API change proposed
- Database migration with data transformation
- Complex async workflow changes