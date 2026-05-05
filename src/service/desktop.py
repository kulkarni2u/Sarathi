"""Local desktop launcher for the Sarathi UI + service stack."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_db_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / ".sarathi" / "sarathi.db"


def default_runtime_script_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "desktop" / "public" / "sarathi-runtime.js"


def render_runtime_script(*, base_url: str, token: str) -> str:
    payload = {"baseUrl": base_url.rstrip("/"), "token": token}
    return (
        "window.__SARATHI_RUNTIME_CONFIG__ = "
        f"{json.dumps(payload, sort_keys=True)};\n"
    )


def render_runtime_stub() -> str:
    return "window.__SARATHI_RUNTIME_CONFIG__ = window.__SARATHI_RUNTIME_CONFIG__ || {};\n"


def write_runtime_script(path: Path, *, base_url: str, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_runtime_script(base_url=base_url, token=token))


def write_runtime_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_runtime_stub())


def choose_port(preferred: int) -> int:
    if preferred > 0:
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_launch_config(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root()
    service_port = choose_port(args.service_port)
    vite_port = choose_port(args.vite_port)
    token = args.token or secrets.token_urlsafe(18)
    db_path = Path(args.db) if args.db else default_db_path(root)
    runtime_script = Path(args.runtime_script) if args.runtime_script else default_runtime_script_path(root)
    return {
        "repo_root": str(root),
        "desktop_dir": str(root / "desktop"),
        "db_path": str(db_path),
        "runtime_script": str(runtime_script),
        "service_host": args.service_host,
        "service_port": service_port,
        "vite_host": args.vite_host,
        "vite_port": vite_port,
        "token": token,
        "base_url": f"http://{args.service_host}:{service_port}",
    }


def wait_for_service(*, base_url: str, token: str, timeout_seconds: float = 12.0) -> None:
    deadline = time.time() + timeout_seconds
    request = urllib.request.Request(
        f"{base_url}/api/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok") and payload.get("data", {}).get("status") == "ok":
                return
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"Sarathi local service did not become healthy in time: {last_error}")


def terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.service.desktop",
        description="Run the Sarathi local desktop stack with runtime config wiring.",
    )
    parser.add_argument("--db", help="SQLite database path for desktop state.")
    parser.add_argument("--token", help="Bearer token for the local UI/service session. Defaults to a random per-run token.")
    parser.add_argument("--service-host", default="127.0.0.1", help="Host for the local Python service.")
    parser.add_argument("--service-port", type=int, default=8765, help="Port for the local Python service. Use 0 to auto-pick.")
    parser.add_argument("--vite-host", default="127.0.0.1", help="Host for the Vite desktop UI.")
    parser.add_argument("--vite-port", type=int, default=5173, help="Port for the Vite desktop UI. Use 0 to auto-pick.")
    parser.add_argument("--runtime-script", help="Path to the generated runtime config script.")
    parser.add_argument("--ui-only", action="store_true", help="Start only the desktop UI using runtime config from the provided host/port/token.")
    parser.add_argument("--service-only", action="store_true", help="Start only the local Python service.")
    parser.add_argument("--print-config", action="store_true", help="Print the resolved startup configuration as JSON and exit.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = build_launch_config(args)
    if args.print_config:
        print(json.dumps(config, indent=2, sort_keys=True))
        return

    runtime_script = Path(config["runtime_script"])
    write_runtime_script(runtime_script, base_url=config["base_url"], token=config["token"])
    atexit.register(write_runtime_stub, runtime_script)

    root = Path(config["repo_root"])
    desktop_dir = Path(config["desktop_dir"])
    service_process: subprocess.Popen[str] | None = None
    ui_process: subprocess.Popen[str] | None = None

    try:
        if not args.ui_only:
            service_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "src.service",
                    "--db",
                    config["db_path"],
                    "--token",
                    config["token"],
                    "--host",
                    config["service_host"],
                    "--port",
                    str(config["service_port"]),
                ],
                cwd=root,
                text=True,
            )
            wait_for_service(base_url=config["base_url"], token=config["token"])
            print(f"Sarathi desktop service ready at {config['base_url']}", flush=True)

        if args.service_only:
            assert service_process is not None
            service_process.wait()
            return

        ui_env = os.environ.copy()
        ui_env["VITE_SARATHI_API_BASE_URL"] = config["base_url"]
        ui_env["VITE_SARATHI_API_TOKEN"] = config["token"]
        ui_process = subprocess.Popen(
            [
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                config["vite_host"],
                "--port",
                str(config["vite_port"]),
            ],
            cwd=desktop_dir,
            env=ui_env,
            text=True,
        )
        print(
            f"Sarathi desktop UI starting on http://{config['vite_host']}:{config['vite_port']}",
            flush=True,
        )
        ui_process.wait()
    except KeyboardInterrupt:
        print("\nStopping Sarathi desktop stack.", flush=True)
    finally:
        terminate_process(ui_process)
        terminate_process(service_process)


if __name__ == "__main__":
    main()
