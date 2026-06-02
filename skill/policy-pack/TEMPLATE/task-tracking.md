# Task Tracking Policy

## [TEMPLATE] Task Manifest & Tracking

> Replace with your team's task tracking conventions.

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

  example:
    task_id: "TASK-2024-001"
    type: "feature"
    description: "Add user authentication endpoint"
    complexity: "medium"
    skills_required:
      - "framework_fastapi"
      - "database_postgresql"
    acceptance_criteria:
      - "POST /auth/login returns JWT"
      - "Invalid credentials return 401"
      - "Rate limiting applied"
    depends_on: []
    blocked_by: []
```

---

## Block Resolution Options

```yaml
block_resolution:
  wait:
    description: "Pause task until block resolved"
    use_when:
      - "Awaiting external dependency"
      - "Waiting on API specification"
      - "Pending human decision"
    timeout_minutes: 60

  skip:
    description: "Mark as skipped, proceed without"
    use_when:
      - "Optional enhancement"
      - "Deferred to later milestone"
      - "Proof of concept"
    requires_approval: true

  substitute:
    description: "Replace with alternative implementation"
    use_when:
      - "Library unavailable"
      - "API changed"
      - "Simpler approach available"
    requires_documentation: true

  continue_anyway:
    description: "Proceed ignoring the block"
    use_when:
      - "Non-critical path"
      - "Graceful degradation possible"
      - "Partial delivery accepted"
    requires_justification: true
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
    - "email"

  actions:
    on_resolved: "notify_and_resume"
    on_timeout: "notify_and_skip"
    on_cancelled: "notify_and_remove"
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

    sequential:
      description: "Should complete before this task"
      symbol: "AFTER"

    parallel:
      description: "Can run concurrently"
      symbol: "WITH"

  cycle_detection: true
  max_depth: 5
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
    created -> queued: "task_queued"
    created -> blocked: "dependency_not_met"
    queued -> in_progress: "agent_started"
    in_progress -> blocked: "block_encountered"
    blocked -> queued: "block_resolved"
    in_progress -> completed: "success"
    in_progress -> failed: "irreversible_error"
    queued -> skipped: "user_cancelled"
    blocked -> skipped: "block_unresolvable"
```

---

## Task Metadata

```yaml
metadata:
  track_tokens: true
  track_time: true
  track_attempts: true
  track_model: true

  logging:
    level: "standard"
    output: ["console", "file", "telemetry"]
```