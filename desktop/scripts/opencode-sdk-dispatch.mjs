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
    (typeof process.env.SARATHI_OPENCODE_MODEL === "string" && process.env.SARATHI_OPENCODE_MODEL.trim()) ||
    "opencode/minimax-m2.5-free";
  const abortController = new AbortController();
  const timer = setTimeout(() => abortController.abort(new Error("OpenCode SDK dispatch timed out")), timeoutMs);

  let opencode = null;
  try {
    const { createOpencode } = await import("@opencode-ai/sdk");
    opencode = await createOpencode({
      timeout: Math.min(timeoutMs, 15000),
      signal: abortController.signal,
      config: {
        model,
      },
    });

    const session = await opencode.client.session.create({
      body: {
        title: payload.title || "Sarathi OpenCode SDK dispatch",
      },
    });

    const reply = await opencode.client.session.prompt({
      path: { id: session.id },
      body: {
        parts: [{ type: "text", text: String(payload.prompt || "") }],
      },
    });

    const response = reply?.data ?? reply;
    const text = collectText(response);

    process.stdout.write(
      JSON.stringify({
        success: true,
        outputs: {
          messages: [text || "OpenCode SDK completed the dispatch."],
        },
        evidence: {
          opencode_sdk: true,
          provider_session_id: session.id,
          workspace_root_used: process.cwd(),
          model,
        },
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "opencode",
          provider_session_id: session.id,
          server_url: opencode.server?.url ?? null,
          model,
        },
      }),
    );
  } catch (error) {
    process.stdout.write(
      JSON.stringify({
        success: false,
        artifacts: {
          invocation_kind: "sdk",
          sdk_family: "opencode",
          model,
        },
        error: error instanceof Error ? error.message : String(error),
      }),
    );
  } finally {
    clearTimeout(timer);
    try {
      await opencode?.server?.close?.();
    } catch {
      // Best effort shutdown; the Python side already has a fallback path.
    }
  }
}

await main();
