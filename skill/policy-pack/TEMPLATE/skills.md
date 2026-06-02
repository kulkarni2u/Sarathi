# Skills Policy

## [TEMPLATE] Skill Routing & Discovery

> Replace with your team's skill ecosystem.

---

## Skill Families

```yaml
skill_families:
  language_python:
    display_name: "Python Development"
    models: ["gpt-4", "claude-3"]
    conventions: "python"
    priority: 1

  language_typescript:
    display_name: "TypeScript Development"
    models: ["gpt-4", "claude-3"]
    conventions: "typescript"
    priority: 1

  framework_fastapi:
    display_name: "FastAPI Development"
    models: ["gpt-4", "claude-3"]
    conventions: "fastapi"
    parent: "language_python"
    priority: 2

  framework_react:
    display_name: "React Development"
    models: ["gpt-4", "claude-3"]
    conventions: "react"
    parent: "language_typescript"
    priority: 2

  database_postgresql:
    display_name: "PostgreSQL"
    models: ["gpt-4"]
    conventions: "sql"
    priority: 3

  cloud_aws:
    display_name: "AWS Cloud"
    models: ["gpt-4"]
    conventions: "aws"
    priority: 3
```

---

## Routing Rules

```yaml
task_to_skill:
  "bug_fix.python":
    primary: "language_python"
    secondary: ["framework_fastapi"]

  "new_endpoint.python":
    primary: "framework_fastapi"
    secondary: ["language_python", "database_postgresql"]

  "data_migration":
    primary: "database_postgresql"
    secondary: ["language_python"]

  "frontend_component":
    primary: "framework_react"
    secondary: ["language_typescript"]

  "infrastructure":
    primary: "cloud_aws"
    secondary: []
```

---

## Skill Discovery Paths

1. File extension analysis (`.py` → Python, `.ts` → TypeScript)
2. Framework detection (`fastapi`, `django`, `express`)
3. Dependency analysis (`package.json`, `requirements.txt`)
4. Context keywords (imports, function signatures)

---

## Missing Skill Protocol

```yaml
missing_skill_response:
  detect_unknown: true
  fallback_to_generic: true
  request_human_input: true

  generic_skills:
    - "language_generic"
    - "code_review"
    - "debugging"

  escalation_triggers:
    - "Unknown framework detected"
    - "No matching convention found"
    - "Skill family rating < 3"
```

---

## Skill Confidence Scoring

```yaml
confidence_scoring:
  direct_match: 1.0
  parent_match: 0.8
  sibling_match: 0.6
  generic_fallback: 0.4

  threshold:
    minimum: 0.5
    preferred: 0.7
```

---

## Skill Composition

[TEMPLATE: How to combine multiple skills]

Example:
- FastAPI endpoint = framework_fastapi + language_python
- AWS Lambda = cloud_aws + language_python
- React component = framework_react + language_typescript

---

## Override Protocol

[TEMPLATE: When human can override skill selection]

- Task spans multiple domains
- Specialized security requirements
- Legacy system without clear skill match