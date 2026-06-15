// Electron main process for the Sarathi desktop shell.
//
// Responsibilities:
//   1. Pick a free port (or default 8765) and generate a random bearer token.
//   2. Spawn the Python service (`python -m src.service ...`) as a child process.
//   3. Poll the service /api/health endpoint (with the bearer token) until it is
//      ready, then open a BrowserWindow pointed at the service root URL. The
//      service injects the token via /sarathi-runtime.js, so the window itself
//      needs no token plumbing.
//   4. On quit, terminate the child service.
//
// This mirrors src/service/desktop.py but for a packaged Electron app.

const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const http = require("http");
const net = require("net");
const path = require("path");

const DEFAULT_PORT = 8765;
const HEALTH_TIMEOUT_MS = 20000;
const HEALTH_POLL_INTERVAL_MS = 250;

let serviceChild = null;
let mainWindow = null;
let shuttingDown = false;
let activePort = null;

// Resolve the directory that contains the Python `src` package.
//   - Dev (running `electron .` from desktop/): two levels up from __dirname.
//   - Packaged: electron-builder copies ../src and ../web/dist into the app's
//     resources directory (see "extraResources" in package.json).
function resolveRepoRoot() {
  if (app.isPackaged) {
    return process.resourcesPath;
  }
  return path.resolve(__dirname, "..");
}

function resolvePythonBin() {
  return process.env.SARATHI_PYTHON || "python3";
}

// Find a free TCP port. Falls back to DEFAULT_PORT on any error.
function choosePort() {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.unref();
    probe.on("error", () => resolve(DEFAULT_PORT));
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port || DEFAULT_PORT));
    });
  });
}

function spawnService({ port, token, repoRoot, dbPath }) {
  const pythonBin = resolvePythonBin();
  const args = [
    "-m",
    "src.service",
    "--db",
    dbPath,
    "--token",
    token,
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ];

  console.log(`[sarathi] spawning: ${pythonBin} ${args.join(" ")} (cwd=${repoRoot})`);
  const child = spawn(pythonBin, args, { cwd: repoRoot });

  child.stdout.on("data", (data) => process.stdout.write(`[service] ${data}`));
  child.stderr.on("data", (data) => process.stderr.write(`[service] ${data}`));

  child.on("exit", (code, signal) => {
    if (shuttingDown) {
      return;
    }
    const detail = `Sarathi service exited unexpectedly (code=${code}, signal=${signal}).`;
    console.error(`[sarathi] ${detail}`);
    dialog.showErrorBox("Sarathi service stopped", detail);
    app.quit();
  });

  return child;
}

// Poll /api/health until the service reports ok or we time out.
function waitForService({ port, token }) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.request(
        {
          host: "127.0.0.1",
          port,
          path: "/api/health",
          method: "GET",
          headers: { Authorization: `Bearer ${token}` },
          timeout: 1500,
        },
        (res) => {
          let body = "";
          res.on("data", (chunk) => {
            body += chunk;
          });
          res.on("end", () => {
            let ok = false;
            try {
              const payload = JSON.parse(body);
              ok = Boolean(payload.ok) && payload.data && payload.data.status === "ok";
            } catch (err) {
              ok = false;
            }
            if (ok) {
              resolve();
            } else {
              retry();
            }
          });
        }
      );
      req.on("error", retry);
      req.on("timeout", () => {
        req.destroy();
        retry();
      });
      req.end();
    };

    const retry = () => {
      if (Date.now() >= deadline) {
        reject(new Error("Sarathi service did not become healthy in time."));
        return;
      }
      setTimeout(attempt, HEALTH_POLL_INTERVAL_MS);
    };

    attempt();
  });
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: "Sarathi",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadURL(`http://127.0.0.1:${port}/`);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function terminateService() {
  if (!serviceChild || serviceChild.exitCode !== null || serviceChild.signalCode !== null) {
    return;
  }
  shuttingDown = true;
  serviceChild.kill("SIGTERM");
  // Hard-kill fallback if the process ignores SIGTERM.
  setTimeout(() => {
    if (serviceChild && serviceChild.exitCode === null && serviceChild.signalCode === null) {
      serviceChild.kill("SIGKILL");
    }
  }, 5000);
}

async function bootstrap() {
  const port = await choosePort();
  activePort = port;
  const token = crypto.randomBytes(24).toString("hex");
  const repoRoot = resolveRepoRoot();
  const dbPath = path.join(app.getPath("userData"), "sarathi.db");

  serviceChild = spawnService({ port, token, repoRoot, dbPath });

  try {
    await waitForService({ port, token });
  } catch (err) {
    console.error(`[sarathi] ${err.message}`);
    dialog.showErrorBox(
      "Sarathi failed to start",
      `${err.message}\n\nCheck that Python 3 and the sarathi package are importable ` +
        `from:\n${repoRoot}\n\nYou can override the interpreter with the SARATHI_PYTHON ` +
        `environment variable.`
    );
    app.quit();
    return;
  }

  createWindow(port);
}

app.whenReady().then(bootstrap);

app.on("activate", () => {
  // macOS convention: re-open a window when the dock icon is clicked. The
  // service child stays alive while the app is running, so only re-create the
  // window if the service is up; otherwise re-run the full bootstrap.
  if (BrowserWindow.getAllWindows().length === 0 && !shuttingDown) {
    const serviceAlive =
      serviceChild && serviceChild.exitCode === null && serviceChild.signalCode === null;
    if (serviceAlive && activePort !== null) {
      createWindow(activePort);
    } else {
      bootstrap();
    }
  }
});

app.on("window-all-closed", () => {
  // Standard convention: stay alive on macOS until Cmd+Q, quit elsewhere.
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", terminateService);
app.on("quit", terminateService);
