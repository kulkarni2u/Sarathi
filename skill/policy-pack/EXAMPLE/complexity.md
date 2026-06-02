# Complexity Triggers

## Complexity Classification Policy for Python/FastAPI Projects

---

## Complexity Levels

### Low Complexity
Indicators:
- Single file change
- Bug fix with clear cause (e.g., null check, missing validation)
- Pydantic schema adjustment
- Route handler parameter change
- FastAPI dependency injection tweak
- Documentation/docstring update
- Test addition for existing functionality

Examples:
- Add `Optional` to query parameter
- Fix typo in error message
- Add one new enum value
- Update pytest fixture

### Medium Complexity
Indicators:
- Multi-file changes (2-5 files)
- New API endpoint with full implementation
- Database migration (Alembic)
- New service class or utility function
- Request/response schema changes
- Authentication/authorization additions
- Caching implementation

Examples:
- Add `GET /users/{user_id}` endpoint
- Implement pagination for list endpoint
- Add JWT refresh token logic
- Create background task processor

### High Complexity
Indicators:
- Cross-cutting concerns (auth, logging, caching)
- Database schema redesign
- Multiple endpoint changes
- Security-sensitive code (password reset, payment)
- Breaking changes or deprecations
- Complex business logic with multiple edge cases
- OpenAPI spec changes
- 6+ files affected

Examples:
- Implement OAuth2 flow
- Multi-tenant isolation
- Full authentication redesign
- Payment integration
- Complex async workflow

---

## Classification Thresholds

| Dimension | Low | Medium | High |
|-----------|-----|--------|------|
| Files affected | 1 | 2-5 | 6+ |
| New endpoints | 0 | 1-2 | 3+ |
| Schema changes | Minor | Moderate | Major |
| DB migrations | None | Simple | Complex |
| Test coverage delta | None | Minor additions | Major additions |
| Breaking changes | No | Possible | Likely |
| Security impact | None | Low | Medium+ |

---

## Historical Comparison Rules

- Compare with last 10 PRs of similar type
- Flag if complexity exceeds 2x median for same task type
- Consider team velocity impact
- Python file changes weighted by LOC (fewer lines = potentially simpler)

---

## Routing Rules

| Complexity | Phase Budget | Model Tier | Review Depth |
|------------|-------------|------------|--------------|
| Low | 1 attempt | gpt-4o-mini | basic |
| Medium | 2 attempts | gpt-4o | standard |
| High | 3+ attempts | gpt-4-turbo | deep |

---

## Override Conditions

- Security fixes: always High complexity
- Dependency updates: always Medium complexity
- Performance optimizations: upgrade by one level
- Breaking API changes: always High complexity
- Hotfixes in production: downgrade by one level (if security safe)