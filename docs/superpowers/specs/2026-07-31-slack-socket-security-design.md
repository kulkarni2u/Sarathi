# Slack Socket Mode Security Design

## Goal

Provide Sarathi's Slack task intake, approval, notification, and human-reply
workflow without exposing the Sarathi HTTP service or any Slack credential to a
public network. Treat every Slack-originated text value as untrusted input and
prevent it from changing instruction hierarchy, revealing secrets, or elevating
provider permissions.

This design replaces the branch's public Slack callback routes. It does not
open a tunnel, publish port 8765, or use a public request URL.

## Security Invariants

The implementation must preserve all of these invariants:

1. Sarathi initiates the only Slack connection through Slack Socket Mode. No
   Slack callback is accepted by the main HTTP service.
2. Slack tokens and authorization configuration are read from process
   environment variables only. They are never written to SQLite, task
   metadata, lifecycle events, API responses, exceptions, or logs.
3. A Slack event is rejected before task lookup or mutation unless its team,
   channel, and actor are authorized for the configured Sarathi workspace.
4. Slack text never becomes a system or developer instruction. It is validated,
   stored with explicit external provenance, and serialized into a bounded
   untrusted-data field.
5. A Slack message cannot select a provider permission mode, add tools, change
   policy, bypass an approval gate, or request credential access.
6. An event is applied at most once. Gate decisions and subtask resumptions are
   atomic and target one identified object.
7. Tests never contact Slack or any other external host.

## Runtime Configuration

The Socket Mode process loads one immutable configuration object at startup
from these environment variables:

- `SARATHI_SLACK_APP_TOKEN`: Slack app-level token used for Socket Mode.
- `SARATHI_SLACK_BOT_TOKEN`: bot token used for messages and updates.
- `SARATHI_SLACK_TEAM_ID`: the only accepted Slack team.
- `SARATHI_SLACK_CHANNEL_IDS`: comma-separated allowlist of accepted channels.
- `SARATHI_SLACK_APPROVER_IDS`: comma-separated allowlist of users allowed to
  approve or reject gates.
- `SARATHI_SLACK_WORKSPACE_ID`: Sarathi workspace receiving Slack-created tasks.

All six values are required. Empty allowlist entries are discarded, but an
empty resulting team, channel, or approver configuration is a startup error.
Tokens are held in memory only. Configuration errors identify the variable name
but never include its value.

Socket Mode does not require a public signing-secret endpoint. The existing
`SARATHI_SLACK_SIGNING_SECRET` HTTP path is removed from the main service rather
than retained as an insecure fallback. A future HTTP transport would require a
separate design and a dedicated, path-restricted process.

The Slack transport is an optional install surface so the core Sarathi package
does not require Slack dependencies. The project exposes a `slack` dependency
extra and a dedicated Socket Mode entry point. Starting that entry point without
the extra installed returns a short installation instruction and does not print
configuration values.

## Components

### Environment configuration loader

A small configuration module owns environment parsing and validation. Other
Slack modules receive the resulting object through constructor arguments and do
not read `os.environ` directly. Its redacted representation exposes only which
fields are configured and the counts of allowlisted IDs. Tokens and team,
channel, user, and workspace identifiers render as `<redacted>`.

### Socket Mode adapter

The adapter owns the outbound Slack connection and converts Slack envelopes
into internal command, interaction, or message-event records. It performs
bounded authorization and input validation, inserts the event into the durable
inbox, and then acknowledges the Socket Mode envelope. Processing is delegated
to a worker, so task mutation, provider dispatch, and Slack API latency cannot
delay acknowledgement. If the durable insert fails, the adapter does not
acknowledge the envelope and allows Slack to retry it.

The adapter accepts only:

- the configured `/sarathi-task` slash command;
- known approval block-action identifiers emitted by Sarathi; and
- non-bot thread replies associated with a stored Sarathi task thread.

Other event and action types are acknowledged and ignored. Files, rich-message
attachments, unfurls, and linked content are not downloaded or followed.

### Authorization boundary

Authorization occurs before content validation or persistence:

- `team_id` must equal `SARATHI_SLACK_TEAM_ID`;
- `channel_id` must be in `SARATHI_SLACK_CHANNEL_IDS`;
- command creators and thread repliers must be real users, not bots;
- approval actions require the actor to be in
  `SARATHI_SLACK_APPROVER_IDS`; and
- every interaction must match the team, channel, task, and message-thread
  binding recorded by Sarathi.

The original command creator may provide a human reply for that task. An
allowlisted approver may also provide a reply. Other actors receive a generic
denial without task details.

### Prompt-injection firewall

Every command body and thread reply passes through one shared validator before
storage. The validator performs these deterministic steps in order:

1. Require a string, normalize it with Unicode NFKC, and reject NUL,
   bidirectional override, disallowed C0/C1 or invisible control characters,
   or non-text payloads. Ordinary tab and line-break characters remain valid.
2. Enforce a 4,000-character post-normalization limit.
3. Decode only bounded URL, hexadecimal, or Base64 wrappers that claim to carry
   instructions, then inspect both the original and decoded form. Recursive or
   oversized encoded content is rejected.
4. Reject recognized instruction-hierarchy overrides, system-prompt or secret
   extraction requests, safety/policy bypass requests, provider/tool permission
   escalation, and requests to reveal environment variables or credentials.
5. Return a typed `ExternalSlackInput` containing the accepted text,
   provenance, actor, channel, event identifier, and validation version.

Blocked content is not stored verbatim. Sarathi records a security event with a
stable reason code, actor/channel identifiers, event identifier, validator
version, text length, and a one-way content digest. Slack receives a generic
rejection that does not reveal which detector matched.

The validator is not the sole security boundary. Accepted text is serialized
as JSON data under an `external_inputs` field in the context pack. Provider
prompts include a fixed higher-priority rule that external input is evidence or
a human answer, not authority to alter system instructions, policy, tools,
permissions, or secret access. Provider permission mode remains derived from
Sarathi task policy, never from text.

This layered boundary is deliberate: deterministic detection blocks known
injection forms, while typed context and capability isolation prevent a missed
phrase from becoming a privilege escalation. The implementation must not claim
that arbitrary natural-language attacks can be perfectly classified.

### Durable inbox and idempotency

Accepted envelopes are inserted into a Slack inbox table using the Socket Mode
`envelope_id` as a unique key. Event API payloads also retain Slack `event_id`
when present. A duplicate insert becomes a no-op and returns the previously
recorded status.

Inbox rows contain routing identifiers and validated content, but no tokens,
`response_url`, raw envelope, or unvalidated payload. Processing records a
terminal `processed`, `rejected`, or `failed` state and a redacted error code.
Retriable failures remain eligible for bounded retry without repeating the
underlying task mutation.

### Slack outbox

Outbound messages are recorded as intent in a separate outbox table in the same
transaction as their Sarathi state change. A worker sends them through the bot
client using the task's stored `channel_id` and `thread_ts`, then records Slack's
message identifier. Unique operation keys prevent duplicate messages after
retry or restart.

No `response_url` is persisted or used. The bot token is supplied to the Slack
client in memory at process construction.

## Data Flow

### Slash command

1. Socket Mode receives the envelope.
2. The adapter validates envelope type, team, channel, and user.
3. The injection firewall validates the command text, the adapter inserts the
   inbox row, and only then acknowledges the envelope.
4. The durable worker creates one `prd_pending` task and its PRD/AC gate in one
   transaction, stores Slack provenance without secrets, and enqueues the first
   thread response.
5. The outbox worker posts the response and records the returned channel and
   thread timestamp on the task binding.

Creating a draft does not dispatch a provider. Normal Sarathi approval and
policy gates remain authoritative.

### Approval or rejection

1. The worker validates the actor allowlist and exact action/task/thread binding.
2. A single compare-and-set transaction changes a still-pending gate to the
   requested terminal state and enqueues its Slack update.
3. Competing or repeated actions observe the existing decision and do not
   perform a second transition.

Action values contain opaque identifiers generated by Sarathi. User-supplied
text cannot select a gate or task.

### Human thread reply

1. The worker resolves the exact task from the channel and thread binding.
2. It authorizes the actor and validates the reply through the injection
   firewall.
3. If exactly one subtask is `waiting_human`, a transaction attaches a typed
   external input to that subtask and moves only that subtask to `in_progress`.
4. If zero subtasks are waiting, the reply is recorded as a normal task message
   and no execution resumes. If multiple subtasks are waiting, none resumes;
   Sarathi stores the validated reply as an unassigned external input and posts
   an ambiguity response with one authorization-bound selection button per
   waiting subtask. Selecting a button atomically binds that existing reply to
   exactly one still-waiting subtask and resumes it. A stale or repeated
   selection is a no-op.
5. `ContextCompiler` includes accepted human replies in `external_inputs`, and
   provider prompt serialization preserves the untrusted-data boundary.

## Main Service Changes

The unauthenticated Slack command, interaction, and Events API branches are
removed from `ServiceApp.handle`. The main service continues to require its
bearer token for JSON API routes. Its public runtime-config behavior is not used
by Slack and is never exposed through the Socket Mode process.

Existing Slack domain helpers may be retained only after they accept typed,
authorized inputs and contain no transport authentication shortcuts. Slack
transport, input validation, task transitions, and outbound delivery remain
separate units with explicit interfaces.

## Error Handling and Observability

- Startup fails closed for missing or malformed environment configuration.
- Socket disconnection retries with bounded exponential backoff and jitter.
- Authorization and injection rejection are terminal; they are not retried.
- Database or Slack delivery failures are retriable through inbox/outbox state.
- Provider dispatch never occurs in the Socket Mode callback thread.
- Logs use event, task, and operation identifiers but omit raw Slack text at
  warning/error levels and always omit tokens.
- Health reporting exposes connection state, inbox/outbox counts, and last
  successful Slack operation timestamp without exposing IDs or credentials.

## Testing

Implementation follows test-driven development. Focused tests must cover:

- environment-only configuration, missing-variable startup failure, and token
  redaction in representations and exceptions;
- proof that the main HTTP service has no unauthenticated Slack routes;
- team, channel, bot, requester, approver, and thread-binding authorization;
- immediate envelope acknowledgement and deferred processing;
- envelope and event deduplication;
- transactional, single-winner approve/reject behavior;
- correct channel/thread routing and response deduplication;
- one-waiter reply resumption, zero-waiter storage, and multi-waiter ambiguity;
- human reply inclusion in provider context as typed external input;
- Unicode controls, normalization, overlong text, encoded attacks, instruction
  overrides, prompt/secret exfiltration, permission escalation, and legitimate
  near-match inputs;
- absence of tokens, raw envelopes, and `response_url` from persisted or returned
  data; and
- a fake Slack client that fails the test if any external network call occurs.

After focused tests, run Ruff on touched Python files, the full test suite, the
package build, and a secret-pattern scan of the branch diff. Token-like test
fixtures must be assembled from non-token-shaped fragments so repository push
protection is not triggered.

## Local Verification Contract

Automated verification uses only the fake client. Live local verification is a
separate, explicit step after the user installs the Slack app and exports the
required environment variables in their shell. It starts the outbound Socket
Mode process and never starts a tunnel or binds a public callback port.

The shared Slack invitation URL is not configuration and is not persisted.
Sarathi requires the installed app's team, channel, and user IDs through the
environment variables above.

## Out of Scope

- Public HTTP Slack callbacks or a tunnel to the Sarathi service.
- Automatic discovery of teams, channels, users, or credentials from an invite
  URL.
- File ingestion, link fetching, unfurl processing, or Slack message-history
  imports.
- A model-based prompt-injection classifier.
- Multiple Slack teams or dynamic Slack-to-Sarathi workspace mappings in one
  process.
- Claiming perfect semantic detection of every possible natural-language attack.

## Acceptance Criteria

The design is complete when the branch provides an outbound-only Socket Mode
process; reads and redacts all Slack configuration from environment variables;
removes public Slack routes from the main service; enforces team, channel, user,
and thread authorization; blocks recognized prompt-injection categories before
persistence or provider dispatch; preserves typed external-input provenance;
performs idempotent transactional state changes; routes replies to the correct
thread and subtask; and passes the focused, full-suite, lint, build, network
isolation, and secret-scan checks described above.
