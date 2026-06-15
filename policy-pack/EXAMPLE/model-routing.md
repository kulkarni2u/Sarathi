# Model Routing Policy

Which provider executes dispatched work. `local` is the safe deterministic
default; switch to claude / codex / opencode once their CLIs are configured
(see `sarathi providers` in the desktop service).

```yaml
provider: local

# Example per-phase overrides (uncomment and adapt):
# phase_providers:
#   Build: claude
#   Review: codex
```

## Gateway provider (OpenAI-compatible endpoints)

The `gateway` provider type is a pure-Python adapter that dispatches to any
OpenAI-compatible Chat Completions endpoint via `base_url` (OpenRouter, Ollama,
vLLM, Azure, ...). It calls the HTTP API directly with `httpx` — no Node.js and
no CLI required. The request goes to `<base_url>/chat/completions`.

Config keys:

- `type: gateway` (required)
- `base_url` (required) — e.g. `http://127.0.0.1:11434/v1`
- `model` (required) — the model id sent in the request body
- `api_key_env` (optional) — the NAME of an environment variable holding the
  API key. When set and non-empty, the adapter sends
  `Authorization: Bearer <value>`. Omit it for keyless backends like Ollama.
- `timeout_seconds` (optional, default 120)

> Note: the block below is illustrative and is intentionally **not** a ```yaml
> fence — the policy compiler merges every ```yaml block in this file, so a
> second active block would override the `provider: local` setting above.
> To use a gateway, replace the active block above with one of these.

```text
provider: ollama

providers:
  # Keyless local Ollama — no Authorization header is sent.
  ollama:
    type: gateway
    base_url: http://127.0.0.1:11434/v1
    model: llama3

  # OpenRouter — reads the key from the OPENROUTER_API_KEY env var.
  openrouter:
    type: gateway
    base_url: https://openrouter.ai/api/v1
    model: anthropic/claude-3.5-sonnet
    api_key_env: OPENROUTER_API_KEY
    timeout_seconds: 120
```
