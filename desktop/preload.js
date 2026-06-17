// Minimal, contextIsolation-safe preload.
// Exposes a tiny read-only marker object to the renderer so the SPA can
// detect that it is running inside the Electron desktop shell. No Node APIs
// are leaked across the bridge.
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("sarathi", Object.freeze({
  desktop: true,
  version: "0.2.0",
}));
