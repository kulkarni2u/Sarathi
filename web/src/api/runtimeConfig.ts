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
// When the cockpit is served single-origin by the service, `baseUrl` is set
// to the empty string `""` to mean "same origin as the page" — `request()`
// then issues relative `fetch("/workspaces/...")` calls against the current
// origin. This is distinct from no runtime config being present at all.
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
 *   1. window.__SARATHI_RUNTIME_CONFIG__ written by desktop.py — including an
 *      explicit `baseUrl: ""`, which means "same origin" and is honored as
 *      relative (NOT replaced by the dev fallback below)
 *   2. Vite dev env vars (VITE_SARATHI_API_BASE_URL / VITE_SARATHI_API_TOKEN)
 *   3. Local dev fallback (http://127.0.0.1:8765, empty token)
 *
 * Steps 2-3 only apply when no runtime config was injected at all (i.e. the
 * `__SARATHI_RUNTIME_CONFIG__` global, or its `baseUrl` key, is absent).
 */
export function getRuntimeConfig(): SarathiRuntimeConfig {
  if (cached) return cached;

  const injected = typeof window !== "undefined" ? window.__SARATHI_RUNTIME_CONFIG__ : undefined;

  // `baseUrl` may be explicitly set to "" by desktop.py to mean "same
  // origin as the page that served the cockpit" (a relative fetch path).
  // Only fall through to env vars / the local dev default when no runtime
  // config was injected at all, i.e. `injected` itself (or its `baseUrl`
  // key) is absent — not merely empty.
  const baseUrl =
    injected && "baseUrl" in injected
      ? injected.baseUrl ?? ""
      : readEnv("VITE_SARATHI_API_BASE_URL") || DEFAULT_BASE_URL;

  const token = injected?.token || readEnv("VITE_SARATHI_API_TOKEN") || "";

  cached = { baseUrl: baseUrl.replace(/\/+$/, ""), token };
  return cached;
}

/** Test-only helper to bypass the cache. Not used in production code paths. */
export function __resetRuntimeConfigCache(): void {
  cached = null;
}
