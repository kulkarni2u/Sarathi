(function applySarathiRuntimeConfig() {
  const existing = window.__SARATHI_RUNTIME_CONFIG__;
  if (existing && typeof existing.baseUrl === "string" && existing.baseUrl) {
    return;
  }
  window.__SARATHI_RUNTIME_CONFIG__ = {"baseUrl": "http://127.0.0.1:8765", "token": "UArjoHcx2gtKSQpWdrT2siDL"};
})();
