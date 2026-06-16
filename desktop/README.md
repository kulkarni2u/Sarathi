# Sarathi Desktop (Electron)

An Electron shell that launches the Sarathi local Python service and opens the
web cockpit in a native window. The service serves the built SPA at its own
origin and injects the per-session bearer token via `/sarathi-runtime.js`, so the
Electron window only needs to load the service root URL — there is no token
plumbing in the renderer.

## How it works

`main.js` (the Electron main process):

1. Picks a free TCP port (or falls back to `8765`) and generates a random
   bearer token with `crypto.randomBytes`.
2. Spawns the Python service:
   `python3 -m src.service --db <userData>/sarathi.db --token <token> --host 127.0.0.1 --port <port>`
   with the repo root as the working directory.
3. Polls `http://127.0.0.1:<port>/api/health` (sending
   `Authorization: Bearer <token>`) until the service reports healthy or a ~20s
   timeout elapses.
4. Opens a `BrowserWindow` (with `contextIsolation: true`,
   `nodeIntegration: false`, and `preload.js`) at `http://127.0.0.1:<port>/`.
5. Terminates the service child process on quit.

`preload.js` exposes a tiny, frozen, read-only `window.sarathi`
(`{ desktop: true, version: "0.2.0" }`) so the SPA can detect the desktop shell.
No Node APIs are bridged into the renderer.

## Prerequisites

- **Node.js 22.12+** (required by the Electron desktop packaging toolchain).
- **Python 3.10+** with the `sarathi` package importable. By default the app
  runs `python3`; override with the `SARATHI_PYTHON` environment variable to
  point at a specific interpreter or virtualenv.
- **A built web bundle.** Build it once from the repo root:

  ```sh
  cd web && npm run build   # produces web/dist
  ```

  The service serves `web/dist` at its own origin; without it you get the API
  but no UI.

## Dev run

From this `desktop/` directory:

```sh
npm install
npm start          # runs `electron .`
```

In dev mode the repo root is resolved as two levels up from `desktop/`, so the
spawned service uses the working tree's `src` package and `web/dist` directly.

## Build a macOS artifact

```sh
npm run dist:mac   # electron-builder --mac  -> .dmg in desktop/dist
```

`npm run dist` runs electron-builder for the current platform's default target.
The `extraResources` config bundles the repo's `../src` (Python service) and
`../web/dist` (built SPA) into the packaged app's resources directory; in a
packaged build `main.js` resolves the repo root from `process.resourcesPath`.

## Caveats

- **Host Python is required.** This scaffold spawns the host machine's Python
  interpreter to run the service. It does **not** bundle a standalone Python
  runtime — doing so (e.g. via PyInstaller or a relocatable CPython) is a
  follow-up. The packaged app will fail to start on a machine without a
  compatible Python 3 and the `sarathi` package importable from the bundled
  `src` directory.
- **First cut targets macOS `.dmg`.** Windows/Linux installers are not yet
  configured.
- **A real packaged build needs the full toolchain.** Producing an installer
  requires a machine with the Electron / electron-builder toolchain installed
  (and macOS for a `.dmg`). It cannot be produced in a headless CI without that
  toolchain, and the build in this repository has not been run/verified in such
  an environment.
