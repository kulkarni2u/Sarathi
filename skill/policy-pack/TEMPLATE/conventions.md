# Code Conventions

## [TEMPLATE] Language & Framework Conventions

> Replace this entire file with your team's conventions.

---

## Language / Framework

[TEMPLATE: Specify primary language(s) and framework(s)]

Example: Python 3.11+ / FastAPI 0.100+

---

## Style Guide

[TEMPLATE: Reference your style guide]

Example: PEP 8 with Black formatter

---

## Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Files | snake_case | `user_service.py` |
| Classes | PascalCase | `UserService` |
| Functions | snake_case | `get_user_by_id` |
| Constants | UPPER_SNAKE | `MAX_RETRIES` |
| Variables | snake_case | `user_id` |
| Private methods | _prefix | `_internal_calc` |

---

## Code Organization

[TEMPLATE: Specify your code structure]

```
src/
├── api/           # Route handlers
├── services/      # Business logic
├── models/        # Data models
├── schemas/       # Request/Response schemas
└── utils/         # Helpers
```

---

## Evidence Requirements by Phase

### Requirements Gathering
- [ ] User story or feature description
- [ ] Acceptance criteria
- [ ] Edge cases identified

### Implementation
- [ ] Types/interfaces defined
- [ ] Error handling in place
- [ ] Logging added

### Testing
- [ ] Unit tests for new logic
- [ ] Integration tests for API changes
- [ ] Test coverage maintained (>80%)

---

## Elegance Criteria

[TEMPLATE: Define what "elegant code" means to your team]

Example:
- Single responsibility per function
- No magic numbers (use constants)
- Explicit over implicit
- Minimal nesting (max 3 levels)

---

## TDD Override Policy

[TEMPLATE: Specify TDD requirements]

- Test-first required for: [TEMPLATE: list modules]
- Test-after allowed for: [TEMPLATE: list modules]
- Coverage gates: [TEMPLATE: percentage]

---

## Import Conventions

[TEMPLATE: Define import ordering and style]

```python
# 1. Standard library
# 2. Third party
# 3. Local application
```