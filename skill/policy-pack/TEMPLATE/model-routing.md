# Model Routing Policy

## [TEMPLATE] Model Selection Guidelines

> Replace with your team's model routing decisions.

---

## Effort Buckets

```yaml
effort_buckets:
  quick_fix:
    description: "Single file, clear solution, low risk"
    examples:
      - "Bug fix with obvious cause"
      - "Add null check"
      - "Rename variable"
      - "Documentation update"
    time_estimate: "< 10 minutes"

  medium_effort:
    description: "2-5 files, moderate complexity, standard risk"
    examples:
      - "New endpoint implementation"
      - "Refactor within module"
      - "Add configuration option"
      - "Database migration"
    time_estimate: "10-30 minutes"

  major_undertaking:
    description: "6+ files or high complexity or high risk"
    examples:
      - "Architecture change"
      - "Cross-cutting feature"
      - "Security implementation"
      - "Public API redesign"
    time_estimate: "> 30 minutes"
```

---

## Token Budget Guidelines

| Effort | Token Budget (soft) | Token Budget (hard) |
|--------|---------------------|---------------------|
| quick_fix | 10,000 | 25,000 |
| medium_effort | 50,000 | 100,000 |
| major_undertaking | 150,000 | 300,000 |

---

## Time Budget Guidelines

| Effort | Time Budget (soft) | Time Budget (hard) |
|--------|--------------------|--------------------|
| quick_fix | 5 min | 15 min |
| medium_effort | 20 min | 45 min |
| major_undertaking | 60 min | 120 min |

---

## Complexity Score Dimensions

```yaml
complexity_dimensions:
  file_count:
    weight: 20
    scale: "linear"

  architectural_impact:
    weight: 30
    scale: "stepped"
    levels: ["local", "module", "system"]

  risk_level:
    weight: 25
    scale: "stepped"
    levels: ["low", "medium", "high", "critical"]

  uncertainty:
    weight: 25
    scale: "linear"
    range: [0, 100]
```

---

## Model Routing Table

```yaml
model_routing:
  quick_fix:
    primary: "fast/cheap-model"
    fallback: "balanced-model"
    temperature: 0.3
    max_tokens: 2000

  medium_effort:
    primary: "balanced-model"
    fallback: "premium-model"
    temperature: 0.5
    max_tokens: 8000

  major_undertaking:
    primary: "premium-model"
    fallback: "premium-model"
    temperature: 0.7
    max_tokens: 16000
```

---

## Provider Selection

[TEMPLATE: Specify model providers per task type]

```yaml
providers:
  code_generation: "openai"
  code_review: "anthropic"
  debugging: "openai"
  refactoring: "openai"
  documentation: "openai"
```

---

## Model-Specific Prompts

[TEMPLATE: Add model-specific system prompts]

- fast/cheap: "Be concise, prefer existing patterns"
- balanced: "Balance thoroughness and efficiency"
- premium: "Think carefully, consider edge cases"

---

## Override Rules

[TEMPLATE: When to override model selection]

- Security-related: always use premium
- Breaking changes: always use premium
- Documentation only: use fast/cheap