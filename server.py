"""Server entry point.

Run with:  python server.py [--port 3010]

The Electron shell launches this module and reads the chosen port from
stdout, so the desktop build never fights over a fixed port.
"""

from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from botoffice.app import OfficeContext, create_app


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

    # The desktop shell waits for this line to learn the real port.
    print(json.dumps({"event": "ready", "port": args.port}), flush=True)

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
