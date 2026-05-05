"""Command-line launcher for the Sarathi local desktop service."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import create_http_server


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.service",
        description="Run the Sarathi local desktop service.",
    )
    parser.add_argument(
        "--db",
        default=".sarathi/sarathi.db",
        help="SQLite database path for desktop state.",
    )
    parser.add_argument(
        "--token",
        default="dev",
        help="Bearer token expected from the desktop UI.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind.",
    )
    args = parser.parse_args()

    server = create_http_server(
        db_path=Path(args.db),
        token=args.token,
        host=args.host,
        port=args.port,
    )
    host, port = server.server_address[:2]
    print(f"Sarathi local service listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Sarathi local service.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
