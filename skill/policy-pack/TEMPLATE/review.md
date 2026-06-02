# Code Review Policy

## [TEMPLATE] Review Configuration

> Replace with your team's review policies.

---

## Spec Compliance Checklist

### Requirements Traceability
- [ ] Each requirement has a test
- [ ] API contracts match spec
- [ ] Error responses match spec
- [ ] Edge cases handled

### Functional Correctness
- [ ] Code implements described behavior
- [ ] No TODO or FIXME without tracking
- [ ] Error handling is complete
- [ ] Logging is appropriate

---

## Code Quality Checklist

### Readability
- [ ] Variable/function names are clear
- [ ] No hidden magic
- [ ] Comments explain why, not what
- [ ] Functions are reasonably sized (<50 lines)

### Maintainability
- [ ] No duplicated logic
- [ ] Dependencies are explicit
- [ ] Configuration is externalized
- [ ] No hardcoded values

### Performance
- [ ] No N+1 queries
- [ ] Caching where appropriate
- [ ] Lazy loading for expensive resources

### Security
- [ ] Input validation present
- [ ] No SQL injection vectors
- [ ] Secrets not in code
- [ ] Proper auth/authz checks

---

## Quality Thresholds

| Metric | Minimum | Target |
|--------|---------|--------|
| Test Coverage | 80% | 90% |
| Cyclomatic Complexity | <15 | <10 |
| Files per PR | <10 | <5 |
| Lines per PR | <500 | <200 |

---

## Review Rounds Configuration

```yaml
max_rounds: 3
round_timeout_minutes: 30
auto_approve_after: 2
require_approval_count: 1
blocking_labels: ["breaking", "security"]
```

---

## Review Output Format

```yaml
review_output:
  format: "structured"

  sections:
    - "Spec Compliance"
    - "Code Quality"
    - "Security"
    - "Performance"
    - "Comments"

  verdict:
    - "APPROVED"
    - "REQUEST_CHANGES"
    - "BLOCKING"

  blocking_issues:
    - "Security vulnerability"
    - "Breaking API change"
    - "Test coverage below threshold"
```

---

## Reviewer Assignment

[TEMPLATE: Define how reviewers are assigned]

Example:
- Primary: Module owner
- Secondary: Architecture reviewer for cross-cutting
- Auto-assign: Forroutine changes

---

## Fast-Track Rules

[TEMPLATE: When to skip review]

- Documentation only changes
- [TEMPLATE: Add more fast-track criteria]