# Code Conventions

## Python/FastAPI Project Conventions

---

## Language / Framework

- **Language**: Python 3.11+
- **Framework**: FastAPI 0.100+
- **Runtime**: Uvicorn / ASGI

---

## Style Guide

- **Formatter**: Black (line length: 100)
- **Linter**: Ruff
- **Type Checker**: mypy (strict mode)
- **Import sorting**: isort

---

## Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Files | snake_case | `user_service.py` |
| Classes | PascalCase | `UserService` |
| Functions | snake_case | `get_user_by_id` |
| Async functions | snake_case + `_async` suffix | `fetch_user_async` |
| Constants | UPPER_SNAKE | `MAX_RETRIES` |
| Variables | snake_case | `user_id` |
| Private methods | _prefix | `_internal_calc` |
| Pydantic models | PascalCase + Schema suffix | `UserCreateSchema` |
| Routes | snake_case | `get_users` |
| Dependencies | snake_case | `get_db` |

---

## Code Organization

```
src/
├── api/
│   ├── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── users.py
│   │   └── auth.py
│   └── deps.py
├── services/
│   ├── __init__.py
│   ├── user_service.py
│   └── auth_service.py
├── models/
│   ├── __init__.py
│   ├── user.py
│   └── token.py
├── schemas/
│   ├── __init__.py
│   ├── user.py
│   └── auth.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── security.py
│   └── database.py
├── utils/
│   ├── __init__.py
│   └── exceptions.py
└── main.py
tests/
├── __init__.py
├── conftest.py
├── api/
├── services/
└── schemas/
```

---

## Evidence Requirements by Phase

### Requirements Gathering
- [ ] User story or feature description
- [ ] OpenAPI parameter definitions
- [ ] Request/response schema drafted
- [ ] Edge cases identified
- [ ] Error codes defined

### Implementation
- [ ] Pydantic schemas for request/response
- [ ] Route handler with proper decorators
- [ ] Error handling with custom exceptions
- [ ] Dependency injection for services
- [ ] Logging at entry/exit points
- [ ] Type hints on all functions

### Testing
- [ ] Unit tests for service layer
- [ ] Integration tests for routes (TestClient)
- [ ] Test fixtures for common scenarios
- [ ] Coverage maintained >80%
- [ ] Async tests for async handlers

---

## Elegance Criteria

- Single responsibility per function
- No magic numbers (use constants from config)
- Explicit over implicit
- Minimal nesting (max 3 levels)
- Prefer composition over inheritance
- Use dependency injection
- Async/await for I/O operations
- Type hints required (no `Any`)
- Docstrings for public interfaces

---

## TDD Override Policy

- **Test-first required for**: services, routes, schemas
- **Test-after allowed for**: utilities, internal helpers
- **Coverage gates**: 80% minimum, 90% target

---

## Import Conventions

```python
# 1. Standard library
import json
from typing import Optional
from datetime import datetime

# 2. Third party
from fastapi import Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

# 3. Local application
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate
```

---

## FastAPI-Specific Patterns

### Route Handler Pattern
```python
@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> UserResponse:
    user = await user_service.create(db, user_in)
    return user
```

### Dependency Pattern
```python
async def get_db() -> Generator[Session, None, None]:
    # yield db session
    pass

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # validate and return user
    pass
```

### Error Handling Pattern
```python
class NotFoundError(Exception):
    pass

@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})
```