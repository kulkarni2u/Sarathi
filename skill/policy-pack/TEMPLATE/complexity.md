# Complexity Triggers

## [TEMPLATE] Complexity Classification Policy

> Replace this entire file with your team's complexity classification rules.

---

## Complexity Levels

### Low Complexity
Indicators:
- Single file change
- Bug fix with clear cause (e.g., null check, boundary condition)
- Documentation update only
- Simple refactor (rename variable, extract method)
- No external API changes
- Test coverage: existing tests pass

### Medium Complexity
Indicators:
- Multi-file changes (2-5 files)
- New endpoint, utility function, or helper
- Performance optimization within existing architecture
- Adding configuration option
- Database migration with backward compatibility
- Requires test additions or modifications

### High Complexity
Indicators:
- Cross-cutting concerns (auth, logging, caching)
- Architecture changes or new patterns
- Public API modifications
- Security-sensitive code
- Breaking changes or deprecations
- Complex business logic
- 6+ files affected

---

## Classification Thresholds

| Dimension | Low | Medium | High |
|-----------|-----|--------|------|
| Files affected | 1 | 2-5 | 6+ |
| Test coverage delta | None | Minor additions | Major additions |
| Breaking changes | No | Possible | Likely |
| Security impact | None | Low | Medium+ |

---

## Historical Comparison Rules

- Compare with last 10 PRs of similar type
- Flag if complexity exceeds 2x median for same task type
- Consider team velocity impact

---

## Routing Rules

| Complexity | Phase Budget | Model Tier | Review Depth |
|------------|-------------|------------|--------------|
| Low | 1 attempt | fast/cheap | basic |
| Medium | 2 attempts | balanced | standard |
| High | 3+ attempts | premium | deep |

---

## Override Conditions

[TEMPLATE: Specify when to override complexity classification, e.g., "security fixes always High", "dependency updates always Medium"]