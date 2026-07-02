# Escalation Policy

Retry budgets and auto-fix limits for Verify/Review quality loops.

When a task's accumulated token usage reaches `max_total_tokens`, the engine
pauses the task (resumable via `sarathi resume`) instead of letting it burn
through the remaining phases unchecked.

```yaml
retry_budgets:
  verify: 2
  review: 1

severity_thresholds:
  block_on: high
  warn_on: medium

auto_fix:
  attempts: 1
  allowed_phases:
    - Verify
    - Elegance

auto_fix_attempts: 1

auto_fix_policies:
  lint: auto
  formatting: auto
  logic: human_review

budget:
  max_total_tokens: 200000
  warn_ratio: 0.8
  on_exhausted: pause

# Classifies phase failures into a recovery_class used to route
# provider-backed recovery dispatch (src/runtime/recovery.py). The values
# below are the engine's built-in defaults, spelled out explicitly so policy
# authors can see the schema and override or extend individual rules without
# changing engine code.
recovery_classification:
  # Ordered rules for deriving a human-readable failure "reason" from a phase
  # result's artifacts. The first matching rule wins. `check` is either
  # "equals" (artifact[field] == expected) or "truthy" (bool(artifact[field])).
  reason_rules:
    - artifact: verification_summary
      field: command_succeeded
      equals: false
      reason: "verification command failed"
    - artifact: verification_summary
      field: lint_errors
      truthy: true
      reason: "lint errors detected"
    - artifact: review_summary
      field: failed
      truthy: true
      reason: "review findings require retry"
  default_reason: "phase requested recovery"

  # Ordered substring rules matched against the lowercased phase error text.
  # The first rule whose `matches` list contains a substring found in the
  # error wins.
  error_text_rules:
    - matches: ["authorization token", "auth"]
      class: auth
    - matches: ["provider unavailable", "cli path not found"]
      class: provider_offline

  # If no error-text rule matches, and the dispatch's provider_context shows
  # this invocation kind, classify as `native_cli_class`. Set
  # native_cli_class to null to disable this rule.
  native_cli_invocation_kind: native_cli
  native_cli_class: native_cli_failure

  # If still unclassified, check whether any keyword appears in the derived
  # reason text (see reason_rules above).
  reason_keyword_rules:
    - keyword: review
      class: review_content

  # Fallback when nothing else matches.
  default_class: generic_retry
```
