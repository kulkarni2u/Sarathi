# Task Tracking Policy

## FastAPI Project Task Manifest & Tracking

---

## Task Manifest Format

```yaml
task_manifest:
  version: "1.0"

  required_fields:
    - "task_id"
    - "type"
    - "description"
    - "complexity"
    - "skills_required"
    - "acceptance_criteria"

  optional_fields:
    - "parent_task_id"
    - "depends_on"
    - "blocked_by"
    - "estimated_effort"
    - "budget"
    - "labels"
    - "pr_url"

  example:
    task_id: "TASK-2024-042"
    type: "feature"
    description: "Add user password reset flow"
    complexity: "medium"
    skills_required:
      - "auth_jwt"
      - "framework_fastapi"
      - "orm_sqlalchemy"
    acceptance_criteria:
      - "POST /auth/password-reset sends email"
      - "POST /auth/password-reset/confirm resets password"
      - "Token expires after 1 hour"
      - "Rate limited to 3 attempts per hour"
    depends_on:
      - "TASK-2024-040"  # Email service
    blocked_by: []
    estimated_effort: "medium_effort"
    budget:
      tokens: 60000
      time_minutes: 30
    labels:
      - "auth"
      - "security"
      - "email"
```

---

## Block Resolution Options

```yaml
block_resolution:
  wait:
    description: "Pause task until block resolved"
    use_when:
      - "Awaiting dependent service"
      - "Waiting on API specification"
      - "Pending schema approval"
    timeout_minutes: 60
    notify_on_timeout: true

  skip:
    description: "Mark as skipped, proceed without"
    use_when:
      - "Optional enhancement"
      - "Deferred to later milestone"
      - "Proof of concept"
    requires_approval: true
    requires_justification: true

  substitute:
    description: "Replace with alternative implementation"
    use_when:
      - "External API changed"
      - "Library unavailable"
      - "Simpler approach available"
    requires_documentation: true
    document_alternative: true

  continue_anyway:
    description: "Proceed ignoring the block"
    use_when:
      - "Non-critical path"
      - "Graceful degradation possible"
      - "Partial delivery accepted"
    requires_justification: true
    add_warnings_to_output: true
```

---

## Background Unblock Configuration

```yaml
background_unblock:
  enabled: true
  polling_interval_seconds: 300
  max_wait_minutes: 120
  notification_channels:
    - "slack"
    - "console"

  actions:
    on_resolved: "notify_and_resume"
    on_timeout: "notify_and_skip"
    on_cancelled: "notify_and_remove"

  resume_task: true
  preserve_context: true
```

---

## Dependency Tracking

```yaml
dependency_tracking:
  manifest_format: "explicit"

  dependency_types:
    blocking:
      description: "Must complete before this task"
      symbol: "BLOCKS"
      color: "red"

    sequential:
      description: "Should complete before this task"
      symbol: "AFTER"
      color: "yellow"

    parallel:
      description: "Can run concurrently"
      symbol: "WITH"
      color: "green"

  cycle_detection: true
  max_depth: 5
  suggest_parallelization: true

  tracking:
    - "task_id"
    - "type"
    - "status"
    - "depends_on"
    - "blocked_by"
    - "resolved_at"
```

---

## Task State Machine

```yaml
task_states:
  - "created"
  - "queued"
  - "in_progress"
  - "blocked"
  - "completed"
  - "failed"
  - "skipped"

  transitions:
    created -> queued:
      trigger: "task_queued"
      guard: "dependencies_met"

    created -> blocked:
      trigger: "dependency_not_met"

    queued -> in_progress:
      trigger: "agent_started"
      guard: "budget_available"

    in_progress -> blocked:
      trigger: "block_encountered"
      save_context: true

    blocked -> queued:
      trigger: "block_resolved"
      guard: "dependencies_still_met"

    blocked -> skipped:
      trigger: "block_unresolvable"
      requires_justification: true

    in_progress -> completed:
      trigger: "success"
      guard: "acceptance_criteria_met"

    in_progress -> failed:
      trigger: "irreversible_error"
      requires_documentation: true

    queued -> skipped:
      trigger: "user_cancelled"

  final_states:
    - "completed"
    - "failed"
    - "skipped"
```

---

## Task Metadata

```yaml
metadata:
  track_tokens: true
  track_time: true
  track_attempts: true
  track_model: true
  track_skills: true

  logging:
    level: "detailed"
    output:
      - "console"
      - "file:task_logs/{task_id}.json"

  aggregation:
    - "complexity"
    - "skills_used"
    - "model_used"
    - "attempts"
    - "tokens_spent"
    - "time_spent"

  reporting:
    velocity_per_skill: true
    budget_accuracy: true
    failure_patterns: true
```

---

## FastAPI-Specific Fields

```yaml
fastapi_extensions:
  track_api_contract: true
  track_schema_changes: true
  track_route_changes: true

  api_contract_fields:
    - "endpoint"
    - "method"
    - "request_schema"
    - "response_schema"
    - "status_codes"

  validation:
    - "OpenAPI spec compliance"
    - "Schema version tracking"
    - "Breaking change detection"
```