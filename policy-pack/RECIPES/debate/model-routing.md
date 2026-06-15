# Model Routing Policy

Which provider executes dispatched work. This recipe pack declares a default
provider plus TWO gateway providers so the orchestrator recipe can fan out
branch work across them and then run a cross-provider JUDGE before merge.

The endpoints below are illustrative (a keyless local Ollama and OpenRouter).
The orchestrator recipe fans out candidate implementations across `provider-a`
and `provider-b` in parallel, then a cross-provider JUDGE reviews the merged
result before it is applied. Replace the `base_url`/`model` values with your own
OpenAI-compatible endpoints.

```yaml
provider: local

providers:
  provider-a:
    type: gateway
    base_url: http://127.0.0.1:11434/v1
    model: llama3
  provider-b:
    type: gateway
    base_url: https://openrouter.ai/api/v1
    model: anthropic/claude-3.5-sonnet
    api_key_env: OPENROUTER_API_KEY
```
