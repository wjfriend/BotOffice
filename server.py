"""Server entry point (headless mode).

Run with:  python server.py [--port 3010]

Prints one ready line with the chosen port so a launcher can read it, and
writes data/hub.port so CLI hooks can find the hub without configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from botoffice.app import OfficeContext, create_app

ROOT = Path(__file__).resolve().parent


def write_port_file(port: int) -> None:
    """Let hook scripts find the hub even when the port is not fixed."""
    try:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "hub.port").write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BotOffice backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3010)
    parser.add_argument("--log-level", default="info")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    context = OfficeContext()
    app = create_app(context)

    write_port_file(args.port)
    # A launcher can wait for this line to learn the real port.
    print(json.dumps({"event": "ready", "port": args.port}), flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
