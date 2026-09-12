"""Regression test for desktop/main.js bearer-token log redaction.

desktop/main.js spawns the Python service with a generated bearer token
passed as a `--token <value>` CLI arg, then logs the full spawn command
line for debugging. Prior to the fix, that log line included the raw
token, so anyone with access to the startup log (stdout, a log
aggregator, a bug report) could read a live credential.

This test loads desktop/main.js into a Node `vm` sandbox with `electron`
and `child_process` mocked out, drives it through its normal startup
path, and asserts that the token passed to the mocked `spawn()` call
never appears in any captured `console.log` line -- while confirming the
mocked child process still receives the real, unredacted token (i.e. the
fix must not break the service's actual auth).
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_JS = REPO_ROOT / "desktop" / "main.js"

NODE_HARNESS = textwrap.dedent(
    r"""
    const vm = require("vm");
    const fs = require("fs");
    const os = require("os");
    const path = require("path");

    const mainPath = process.argv[2];
    const source = fs.readFileSync(mainPath, "utf8");

    const logs = [];
    const spawnCalls = [];

    const fakeApp = {
      isPackaged: false,
      whenReady: () => Promise.resolve(),
      getPath: () => os.tmpdir(),
      on: () => {},
      quit: () => {},
    };

    class FakeBrowserWindow {
      constructor() {}
      loadURL() {}
      on() {}
    }

    const fakeElectron = {
      app: fakeApp,
      BrowserWindow: FakeBrowserWindow,
      dialog: { showErrorBox: () => {} },
    };

    const fakeChildProcess = {
      spawnSync: () => ({ status: 0 }),
      spawn: (cmd, args, opts) => {
        spawnCalls.push({ cmd, args, opts });
        return {
          stdout: { on: () => {} },
          stderr: { on: () => {} },
          on: () => {},
          exitCode: null,
          signalCode: null,
          kill: () => {},
        };
      },
    };

    const sandboxRequire = (name) => {
      if (name === "electron") return fakeElectron;
      if (name === "child_process") return fakeChildProcess;
      return require(name);
    };

    const sandboxConsole = {
      log: (...args) => logs.push(args.join(" ")),
      warn: (...args) => logs.push(args.join(" ")),
      error: (...args) => logs.push(args.join(" ")),
    };

    const context = {
      require: sandboxRequire,
      module: { exports: {} },
      exports: {},
      __dirname: path.dirname(mainPath),
      __filename: mainPath,
      console: sandboxConsole,
      process,
      Buffer,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      URL,
      Promise,
    };
    vm.createContext(context);
    const script = new vm.Script(source, { filename: mainPath });
    script.runInContext(context);

    setTimeout(() => {
      process.stdout.write("RESULT_JSON:" + JSON.stringify({ logs, spawnCalls }) + "\n");
      process.exit(0);
    }, 500);
    """
)


def _run_harness() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node binary not available")

    result = subprocess.run(
        [node, "-", str(MAIN_JS)],
        input=NODE_HARNESS,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"node harness failed (rc={result.returncode})\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )

    for line in result.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line[len("RESULT_JSON:") :])

    raise AssertionError(f"harness did not emit RESULT_JSON\nstdout={result.stdout}\nstderr={result.stderr}")


def test_spawn_service_redacts_bearer_token_from_logs():
    result = _run_harness()
    spawn_calls = result["spawnCalls"]
    logs = result["logs"]

    assert spawn_calls, "expected desktop/main.js to spawn the python service"
    args = spawn_calls[0]["args"]
    assert "--token" in args, "spawn args should still contain the --token flag"

    token_index = args.index("--token") + 1
    token = args[token_index]
    assert token, "expected a non-empty bearer token to be generated"

    # The real child process must still receive the correct, unredacted token.
    assert token in args

    # But no captured log line may leak that token value.
    leaking_lines = [line for line in logs if token in line]
    assert not leaking_lines, f"bearer token leaked into log output: {leaking_lines!r}"

    # Sanity check: the spawn log line should exist and show it was redacted.
    spawn_logs = [line for line in logs if "spawning:" in line]
    assert spawn_logs, "expected a '[sarathi] spawning: ...' log line"
    assert any("--token ***REDACTED***" in line for line in spawn_logs)
