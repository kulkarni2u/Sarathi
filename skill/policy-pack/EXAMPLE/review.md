# Code Review Policy

## FastAPI Project Review Configuration

---

## Spec Compliance Checklist

### Requirements Traceability
- [ ] Each OpenAPI parameter has a Pydantic schema
- [ ] Route path matches API spec
- [ ] HTTP methods correct (GET/POST/PUT/DELETE)
- [ ] Status codes match spec (200/201/400/401/404/500)
- [ ] Error responses have detail field
- [ ] Request/response schemas match spec

### Functional Correctness
- [ ] Handler implements described behavior
- [ ] Edge cases return appropriate errors
- [ ] No TODO or FIXME without issue reference
- [ ] Error handling with custom exceptions
- [ ] Logging at entry/exit points
- [ ] Async handlers for async operations

---

## Code Quality Checklist

### FastAPI Conventions
- [ ] Proper route decorator usage
- [ ] Dependency injection for services
- [ ] Pydantic schemas for validation
- [ ] Type hints on all functions
- [ ] Response models defined
- [ ] Status codes explicit

### Readability
- [ ] Variable/function names are clear
- [ ] No hidden magic
- [ ] Comments explain why, not what
- [ ] Functions < 50 lines
- [ ] Docstrings on public interfaces
- [ ] Type hints (not Any)

### Maintainability
- [ ] No duplicated logic
- [ ] Services depend on abstractions
- [ ] Configuration from settings
- [ ] No hardcoded values
- [ ] Proper error hierarchy
- [ ] Separation of concerns

### Performance
- [ ] No N+1 queries (use selectinload/joinedload)
- [ ] Pagination on list endpoints
- [ ] Indexes on queried columns
- [ ] Async for I/O operations
- [ ] Background tasks for long operations

### Security
- [ ] Input validation (Pydantic)
- [ ] SQL injection prevention (SQLAlchemy ORM)
- [ ] No secrets in code (use env vars)
- [ ] Auth on protected routes
- [ ] Rate limiting where appropriate
- [ ] CORS configuration

---

## Quality Thresholds

| Metric | Minimum | Target |
|--------|---------|--------|
| Test Coverage | 80% | 90% |
| Cyclomatic Complexity | <15 | <10 |
| Files per PR | <10 | <5 |
| Lines per PR | <500 | <200 |
| Route handler lines | <30 | <20 |
| Schema fields | <20 | <10 |

---

## Review Rounds Configuration

```yaml
max_rounds: 3
round_timeout_minutes: 30
auto_approve_after: 2
require_approval_count: 1
blocking_labels:
  - "breaking"
  - "security"
  - "performance"
```

---

## Review Output Format

```yaml
review_output:
  format: "structured"

  sections:
    - "Spec Compliance"
    - "Code Quality"
    - "FastAPI Patterns"
    - "Security"
    - "Performance"
    - "Testing"
    - "Comments"

  verdict:
    - "APPROVED"
    - "REQUEST_CHANGES"
    - "BLOCKING"

  blocking_issues:
    - "Security vulnerability"
    - "Breaking API change without deprecation"
    - "Test coverage below 80%"
    - "Type hints missing or Any used"
    - "Secrets hardcoded"

  non_blocking_issues:
    - "Style suggestions"
    - "Minor improvements"
    - "Documentation gaps"
```

---

## API-Specific Review Focus

### OpenAPI Compliance
- [ ] Valid OpenAPI 3.0 schema
- [ ] All parameters documented
- [ ] Example values provided
- [ ] Error schemas consistent
- [ ] Tags properly assigned

### Data Layer
- [ ] Migrations are backward compatible
- [ ] Indexes added for new queries
- [ ] Cascade deletes explicit
- [ ] Transactions for multi-table writes

### Authentication
- [ ] JWT validation correct
- [ ] Token expiry handled
- [ ] Refresh token flow implemented
- [ ] Protected routes have dependency

---

## Reviewer Assignment

- Primary: Module owner (user/auth/etc)
- Secondary: Architecture reviewer for cross-cutting
- Auto-assign: Based on file paths changed

---

## Fast-Track Rules

- Documentation only changes
- Test-only additions
- Dependabot updates (if tests pass)
- Changelog updates