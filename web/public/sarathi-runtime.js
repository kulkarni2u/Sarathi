// Dev-time stub for the runtime config contract.
//
// In a real desktop session, src/service/desktop.py overwrites this file
// (via render_runtime_script / write_runtime_script) with the live service
// baseUrl + token before launching the Vite dev server / serving the built
// app. This stub just ensures the global exists so src/api/runtimeConfig.ts
// can fall back to VITE_SARATHI_API_BASE_URL / VITE_SARATHI_API_TOKEN or the
// http://127.0.0.1:8765 default.
window.__SARATHI_RUNTIME_CONFIG__ = window.__SARATHI_RUNTIME_CONFIG__ || {};
