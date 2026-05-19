import process from "node:process";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf8");
}

function collectText(value) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (Array.isArray(value)) {
    return value.map(collectText).filter(Boolean).join("\n").trim();
  }
  if (value && typeof value === "object") {
    if (typeof value.text === "string") {
      return value.text.trim();
    }
    if (typeof value.content === "string") {
      return value.content.trim();
    }
    if (Array.isArray(value.content)) {
      return value.content.map(collectText).filter(Boolean).join("\n").trim();
    }
    if (Array.isArray(value.parts)) {
      return value.parts.map(collectText).filter(Boolean).join("\n").trim();
    }
    if (Array.isArray(value.messages)) {
      return value.messages.map(collectText).filter(Boolean).join("\n").trim();
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
    (typeof process.env.SARATHI_OPENAI_MODEL === "string" && process.env.SARATHI_OPENAI_MODEL.trim()) ||
    "gpt-4.1";
  const apiKey =
    (typeof payload.api_key === "string" && payload.api_key.trim()) ||
    process.env.OPENAI_API_KEY;
  const baseURL =
    (typeof payload.base_url === "string" && payload.base_url.trim()) ||
    process.env.OPENAI_BASE_URL;
  if (!apiKey) {
    process.stdout.write(
      JSON.stringify({
        success: false,
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "openai",
          model,
        },
        error: "OPENAI_API_KEY environment variable is not set",
      }),
    );
    return;
  }
  const abortController = new AbortController();
  const timer = setTimeout(() => abortController.abort(new Error("OpenAI SDK dispatch timed out")), timeoutMs);

  let client = null;
  try {
    const { default: OpenAI } = await import("openai");
    client = new OpenAI({
      apiKey,
      ...(baseURL ? { baseURL } : {}),
      timeout: Math.min(timeoutMs, 60000),
    });

    const response = await client.responses.create({
      model,
      input: [{ type: "message", role: "user", content: String(payload.prompt || "") }],
      temperature: 0.7,
      max_output_tokens: 8192,
      stream: false,
      abortSignal: abortController.signal,
    });

    const text =
      (typeof response.output_text === "string" && response.output_text.trim()) ||
      collectText(response.output);

    process.stdout.write(
      JSON.stringify({
        success: true,
        outputs: {
          messages: [text || "OpenAI SDK completed the dispatch."],
        },
        evidence: {
          openai_sdk: true,
          provider_session_id: response.id,
          workspace_root_used: process.cwd(),
          model,
          ...(baseURL ? { base_url: baseURL } : {}),
        },
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "openai",
          provider_session_id: response.id,
          model,
          ...(baseURL ? { base_url: baseURL } : {}),
        },
        usage: {
          input_tokens: response.usage?.input_tokens ?? null,
          output_tokens: response.usage?.output_tokens ?? null,
          total_tokens: response.usage?.total_tokens ?? null,
        },
      }),
    );
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        success: false,
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "openai",
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
