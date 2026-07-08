# Policy Pack: Notifications

Outbound notifications for attention-worthy lifecycle events. Secrets stay
in the environment — this file only names the env vars that hold them.

## Slack

Two transports are supported:

- **Incoming webhook** (simplest): create a webhook in Slack, export it as
  `SARATHI_SLACK_WEBHOOK_URL`, and set `enabled: true`. The channel is fixed
  by the webhook itself.
- **Bot token**: export `SARATHI_SLACK_BOT_TOKEN` and set `channel`; messages
  go through `chat.postMessage`, so one token can post to any channel the bot
  is invited to.

```yaml
slack:
  enabled: false
  webhook_env: SARATHI_SLACK_WEBHOOK_URL

  # Bot-token mode instead of a webhook:
  # bot_token_env: SARATHI_SLACK_BOT_TOKEN
  # channel: "#sarathi-runs"

  timeout_seconds: 5

  # fnmatch-style patterns matched against lifecycle event types.
  # Add "phase.*" for chatty per-phase progress messages.
  events:
    - task.completed
    - task.failed
    - task.paused
    - task.escalated
    - task.cancelled
    - task.timed_out
    - budget.exhausted
    - approval.requested
    - review.rejected
```

Notes:

- Notifications are best-effort: a Slack outage never fails or blocks a run.
- The HTTP service and worker use environment-only configuration
  (`SARATHI_SLACK_WEBHOOK_URL` / `SARATHI_SLACK_BOT_TOKEN` +
  `SARATHI_SLACK_CHANNEL`, optional `SARATHI_SLACK_EVENTS` as a
  comma-separated pattern list), since the service spans workspaces.
- CLI/TUI/MCP runs read this policy file; if the file is absent entirely,
  exporting the webhook env var alone activates notifications with the
  default event list.
