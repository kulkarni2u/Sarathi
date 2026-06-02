# Model Routing Policy

## OpenAI Model Routing for Python Tasks

---

## Effort Buckets

```yaml
effort_buckets:
  quick_fix:
    description: "Single file, clear solution, low risk"
    examples:
      - "Add Pydantic validation"
      - "Fix null check"
      - "Add docstring"
      - "Update error message"
      - "Minor route parameter change"
    time_estimate: "< 10 minutes"
    token_budget: 15000

  medium_effort:
    description: "2-5 files, moderate complexity, standard risk"
    examples:
      - "New GET endpoint with service layer"
      - "Add pagination to list endpoint"
      - "Implement simple background task"
      - "Add request validation schema"
      - "Database query optimization"
    time_estimate: "10-30 minutes"
    token_budget: 50000

  major_undertaking:
    description: "6+ files or high complexity or high risk"
    examples:
      - "Full auth flow implementation"
      - "Multi-tenant isolation"
      - "Payment integration"
      - "Complex async workflow"
      - "Public API redesign"
    time_estimate: "> 30 minutes"
    token_budget: 120000
```

---

## Token Budget Guidelines

| Effort | Token Budget (soft) | Token Budget (hard) |
|--------|---------------------|---------------------|
| quick_fix | 10,000 | 25,000 |
| medium_effort | 50,000 | 100,000 |
| major_undertaking | 120,000 | 200,000 |

---

## Time Budget Guidelines

| Effort | Time Budget (soft) | Time Budget (hard) |
|--------|--------------------|--------------------|
| quick_fix | 5 min | 15 min |
| medium_effort | 20 min | 45 min |
| major_undertaking | 60 min | 90 min |

---

## Complexity Score Dimensions

```yaml
complexity_dimensions:
  file_count:
    weight: 20
    scale: "linear"
    mapping:
      1: 0
      2-5: 50
      6+: 100

  architectural_impact:
    weight: 30
    scale: "stepped"
    levels:
      local: 0
      module: 50
      system: 100

  risk_level:
    weight: 25
    scale: "stepped"
    levels:
      low: 0
      medium: 50
      high: 75
      critical: 100

  uncertainty:
    weight: 25
    scale: "linear"
    range: [0, 100]
    factors:
      - "Business logic complexity"
      - "Edge case count"
      - "Integration points"
```

---

## Model Routing Table

```yaml
model_routing:
  quick_fix:
    primary: "gpt-4o-mini"
    fallback: "gpt-4o"
    temperature: 0.3
    max_tokens: 4000
    system_prompt: "You are a Python code reviewer. Be concise. Focus on the specific fix. Follow FastAPI conventions."

  medium_effort:
    primary: "gpt-4o"
    fallback: "gpt-4-turbo"
    temperature: 0.5
    max_tokens: 16000
    system_prompt: "You are a Python backend developer. Implement clean, maintainable FastAPI code with proper type hints and error handling."

  major_undertaking:
    primary: "gpt-4-turbo"
    fallback: "gpt-4-turbo"
    temperature: 0.7
    max_tokens: 32000
    system_prompt: "You are a senior Python architect. Design robust, scalable solutions with proper separation of concerns, testing, and documentation."
```

---

## Provider Selection

```yaml
providers:
  code_generation: "openai"
  code_review: "openai"
  debugging: "openai"
  refactoring: "openai"
  documentation: "openai"
  architecture: "openai"

  reasoning_tasks:
    complex_logic: "o3-mini"
    architecture_design: "gpt-4-turbo"
```

---

## Task-Specific Routing

```yaml
task_specific:
  pydantic_schema:
    preferred_model: "gpt-4o"
    max_tokens: 8000

  route_handler:
    preferred_model: "gpt-4o"
    max_tokens: 8000

  service_layer:
    preferred_model: "gpt-4o"
    max_tokens: 12000

  database_migration:
    preferred_model: "gpt-4o"
    max_tokens: 8000
    extra_context: "Include rollback strategy"

  test_writing:
    preferred_model: "gpt-4o-mini"
    max_tokens: 6000

  auth_implementation:
    preferred_model: "gpt-4-turbo"
    max_tokens: 16000
    extra_review: true
```

---

## Override Rules

- Security-related tasks: always gpt-4-turbo
- Breaking changes: always gpt-4-turbo
- Auth implementation: always gpt-4-turbo
- Documentation only: gpt-4o-mini
- Hotfix in production: downgrade one level
- Performance-critical: upgrade one level

---

## Context Enrichment

```yaml
context_for_model:
  python:
    include:
      - "Python 3.11+"
      - "Type hints required"
      - "PEP 8 + Black formatting"

  fastapi:
    include:
      - "FastAPI 0.100+"
      - "Pydantic v2"
      - "Dependency injection"
      - "Async handlers"

  testing:
    include:
      - "pytest"
      - "pytest-asyncio"
      - "TestClient for routes"
      - "80% coverage minimum"
```