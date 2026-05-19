import process from "node:process";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf8");
}

function collectText(value) {
  if (!value) {
    return "";
  }
  if (typeof value === "string") {
    return value.trim();
  }
  if (Array.isArray(value)) {
    return value.map(collectText).filter(Boolean).join("\n").trim();
  }
  if (typeof value === "object") {
    if (typeof value.text === "string") {
      return value.text.trim();
    }
    if (Array.isArray(value.content)) {
      return value.content.map(collectText).filter(Boolean).join("\n").trim();
    }
  }
  return "";
}

async function main() {
  const raw = await readStdin();
  const payload = raw ? JSON.parse(raw) : {};
  const timeoutMs = Math.max(1000, Number(payload.timeout_seconds || 120) * 1000);
  const model =
    (typeof payload.model === "string" && payload.model.trim()) ||
    (typeof process.env.SARATHI_ANTHROPIC_MODEL === "string" && process.env.SARATHI_ANTHROPIC_MODEL.trim()) ||
    "claude-sonnet-4-0";
  const apiKey =
    (typeof payload.api_key === "string" && payload.api_key.trim()) ||
    process.env.ANTHROPIC_API_KEY;
  const baseURL =
    (typeof payload.base_url === "string" && payload.base_url.trim()) ||
    process.env.ANTHROPIC_BASE_URL;
  if (!apiKey) {
    process.stdout.write(
      JSON.stringify({
        success: false,
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "anthropic",
          model,
        },
        error: "ANTHROPIC_API_KEY environment variable is not set",
      }),
    );
    return;
  }

  const abortController = new AbortController();
  const timer = setTimeout(() => abortController.abort(new Error("Anthropic SDK dispatch timed out")), timeoutMs);

  try {
    const { default: Anthropic } = await import("@anthropic-ai/sdk");
    const client = new Anthropic({
      apiKey,
      ...(baseURL ? { baseURL } : {}),
      timeout: Math.min(timeoutMs, 60000),
    });

    const response = await client.messages.create(
      {
        model,
        max_tokens: 4096,
        messages: [{ role: "user", content: String(payload.prompt || "") }],
      },
      {
        signal: abortController.signal,
      },
    );

    const text = collectText(response.content);

    process.stdout.write(
      JSON.stringify({
        success: true,
        outputs: {
          messages: [text || "Anthropic SDK completed the dispatch."],
        },
        evidence: {
          anthropic_sdk: true,
          provider_session_id: response.id,
          workspace_root_used: process.cwd(),
          model,
          ...(baseURL ? { base_url: baseURL } : {}),
        },
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "anthropic",
          provider_session_id: response.id,
          model,
          ...(baseURL ? { base_url: baseURL } : {}),
        },
        usage: {
          input_tokens: response.usage?.input_tokens ?? null,
          output_tokens: response.usage?.output_tokens ?? null,
          total_tokens:
            typeof response.usage?.input_tokens === "number" && typeof response.usage?.output_tokens === "number"
              ? response.usage.input_tokens + response.usage.output_tokens
              : null,
        },
      }),
    );
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        success: false,
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "anthropic",
          model,
        },
        error: error instanceof Error ? error.message : String(error),
      }),
    );
  } finally {
    clearTimeout(timer);
  }
}

await main();
