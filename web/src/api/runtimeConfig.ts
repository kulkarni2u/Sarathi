// Runtime configuration contract.
//
// `src/service/desktop.py` (`render_runtime_script` / `write_runtime_script`)
// generates a small script that sets a global before the app boots:
//
//   window.__SARATHI_RUNTIME_CONFIG__ = { baseUrl: "...", token: "..." };
//
// `render_runtime_stub` writes `window.__SARATHI_RUNTIME_CONFIG__ =
// window.__SARATHI_RUNTIME_CONFIG__ || {}` when no live session is wired up
// (e.g. on shutdown), so the key may exist but be empty.
//
// `index.html` loads this script from `/sarathi-runtime.js` *before*
// `src/main.tsx`. In a plain `vite dev` session that file won't exist, so we
// fall back to Vite env vars (`VITE_SARATHI_API_BASE_URL` /
// `VITE_SARATHI_API_TOKEN`, which desktop.py also sets when it spawns `npm
// run dev`) and finally to a hardcoded local default.

export interface SarathiRuntimeConfig {
  baseUrl: string;
  token: string;
}

declare global {
  interface Window {
    __SARATHI_RUNTIME_CONFIG__?: Partial<SarathiRuntimeConfig>;
  }
}

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

function readEnv(key: string): string | undefined {
  // import.meta.env values are statically replaced by Vite at build time.
  const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
  return env?.[key];
}

let cached: SarathiRuntimeConfig | null = null;

/**
 * Resolve the runtime config exactly once, in priority order:
 *   1. window.__SARATHI_RUNTIME_CONFIG__ written by desktop.py
 *   2. Vite dev env vars (VITE_SARATHI_API_BASE_URL / VITE_SARATHI_API_TOKEN)
 *   3. Local dev fallback (http://127.0.0.1:8765, empty token)
 */
export function getRuntimeConfig(): SarathiRuntimeConfig {
  if (cached) return cached;

  const injected = typeof window !== "undefined" ? window.__SARATHI_RUNTIME_CONFIG__ : undefined;

  const baseUrl =
    injected?.baseUrl ||
    readEnv("VITE_SARATHI_API_BASE_URL") ||
    DEFAULT_BASE_URL;

  const token = injected?.token || readEnv("VITE_SARATHI_API_TOKEN") || "";

  cached = { baseUrl: baseUrl.replace(/\/+$/, ""), token };
  return cached;
}

/** Test-only helper to bypass the cache. Not used in production code paths. */
export function __resetRuntimeConfigCache(): void {
  cached = null;
}
