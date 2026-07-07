import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Sarathi web cockpit (M1 scaffold).
//
// Port 5173 matches the default `--vite-port` in `src/service/desktop.py`,
// which launches this dev server and writes a runtime config script
// (`/sarathi-runtime.js`) containing the live service `baseUrl` + `token`.
//
// The API client (see src/api/runtimeConfig.ts) reads that runtime config
// directly and talks to the absolute `baseUrl`, so no dev proxy is strictly
// required. We still configure a `/api` proxy to `127.0.0.1:8765` (the
// desktop.py default service port) as a convenience for local development
// when the runtime script is absent and a service happens to be running.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "node",
    globals: true,
  },
} as any);
