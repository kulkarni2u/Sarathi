# Skills Policy

## Python Skill Families & Routing

---

## Skill Families

```yaml
skill_families:
  language_python:
    display_name: "Python Development"
    models: ["gpt-4o", "gpt-4-turbo"]
    conventions: "python"
    priority: 1
    file_patterns: ["*.py"]
    keywords: ["python", "py"]

  framework_fastapi:
    display_name: "FastAPI Development"
    models: ["gpt-4o", "gpt-4-turbo"]
    conventions: "fastapi"
    parent: "language_python"
    priority: 2
    keywords: ["fastapi", "uvicorn", "starlette"]
    files: ["main.py", "routes/", "schemas/"]

  orm_sqlalchemy:
    display_name: "SQLAlchemy ORM"
    models: ["gpt-4o"]
    conventions: "sqlalchemy"
    parent: "language_python"
    priority: 3
    keywords: ["sqlalchemy", "orm", "session"]
    files: ["models/", "**/*model*.py"]

  database_postgresql:
    display_name: "PostgreSQL"
    models: ["gpt-4o"]
    conventions: "sql"
    priority: 3
    keywords: ["postgresql", "psql", "alembic"]
    files: ["alembic/", "migrations/"]

  testing_pytest:
    display_name: "Python Testing"
    models: ["gpt-4o-mini", "gpt-4o"]
    conventions: "pytest"
    parent: "language_python"
    priority: 2
    keywords: ["pytest", "test", "fixture", "coverage"]
    files: ["tests/", "conftest.py"]

  auth_jwt:
    display_name: "JWT Authentication"
    models: ["gpt-4o"]
    conventions: "auth"
    parent: "framework_fastapi"
    priority: 4
    keywords: ["jwt", "oauth", "token", "auth"]
    files: ["**/auth*.py", "**/security*.py"]

  data_pydantic:
    display_name: "Pydantic Data Validation"
    models: ["gpt-4o"]
    conventions: "pydantic"
    parent: "language_python"
    priority: 3
    keywords: ["pydantic", "schema", "validation", "model"]
    files: ["schemas/", "**/*schema*.py"]
```

---

## Routing Rules

```yaml
task_to_skill:
  "bug_fix.api":
    primary: "framework_fastapi"
    secondary: ["language_python", "testing_pytest"]
    complexity_boost: 1

  "bug_fix.database":
    primary: "orm_sqlalchemy"
    secondary: ["language_python", "database_postgresql"]

  "new_endpoint":
    primary: "framework_fastapi"
    secondary: ["orm_sqlalchemy", "data_pydantic", "testing_pytest"]
    complexity_boost: 1

  "new_service":
    primary: "language_python"
    secondary: ["orm_sqlalchemy", "testing_pytest"]

  "data_migration":
    primary: "database_postgresql"
    secondary: ["orm_sqlalchemy"]

  "auth_implementation":
    primary: "auth_jwt"
    secondary: ["framework_fastapi", "language_python"]

  "test_writing":
    primary: "testing_pytest"
    secondary: ["language_python"]

  "schema_change":
    primary: "data_pydantic"
    secondary: ["framework_fastapi", "orm_sqlalchemy"]
```

---

## Skill Discovery Paths

1. **File extension**: `.py` → language_python
2. **Framework detection**: Check imports (`fastapi`, `FastAPI` → framework_fastapi)
3. **File path**: `routes/` → framework_fastapi, `tests/` → testing_pytest
4. **Dependency files**: `requirements.txt` scan for framework indicators
5. **Context keywords**: Scan diff for `async def`, `@router`, `class Schema`

---

## Missing Skill Protocol

```yaml
missing_skill_response:
  detect_unknown: true
  fallback_to_generic: true
  request_human_input: false

  generic_skills:
    language_python: 0.7
    code_review: 0.5
    debugging: 0.5

  escalation_triggers:
    - "Unknown framework detected"
    - "No matching convention found"
    - "Skill family rating < 0.4"
    - "Multiple conflicting skills detected"

  fallback_priority:
    - "language_python"
    - "framework_fastapi"
    - "testing_pytest"
```

---

## Skill Confidence Scoring

```yaml
confidence_scoring:
  direct_match: 1.0
  parent_match: 0.8
  sibling_match: 0.6
  file_path_match: 0.7
  keyword_match: 0.5
  generic_fallback: 0.4

  threshold:
    minimum: 0.5
    preferred: 0.7
    high_confidence: 0.9
```

---

## Skill Composition Rules

| Task | Primary Skill | Additional Skills |
|------|--------------|-------------------|
| FastAPI endpoint | framework_fastapi | +1 orm_sqlalchemy, +1 data_pydantic, +1 testing_pytest |
| Database model | orm_sqlalchemy | +1 database_postgresql |
| Auth flow | auth_jwt | +1 framework_fastapi |
| Migration | database_postgresql | +1 orm_sqlalchemy |
| Unit tests | testing_pytest | +1 language_python |

---

## Override Protocol

- Task spans multiple domains → human selects primary
- Legacy system → language_python only
- Security-critical → auth_jwt required
- Mixed Python/JS → split by file changes