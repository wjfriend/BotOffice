"""A minimal MCP server used by scripts/verify/mcp.test.py.

It speaks the stdio JSON-RPC dialect MCP uses, with a single `echo` tool, so
the client can be exercised without any third-party package installed.

Run: python scripts/verify/mcp_echo_server.py
"""

from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the text back to the caller.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


def handle(message: dict) -> dict | None:
    """Turn one JSON-RPC request into a reply, or None for notifications."""
    if "id" not in message:
        return None
    method = message.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "botoffice-echo", "version": "1.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        text = (params.get("arguments") or {}).get("text", "")
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"content": [{"type": "text", "text": f"echo: {text}"}]},
        }
    return {"jsonrpc": "2.0", "id": message["id"], "result": {}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(message)
        if reply is None:
            continue
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
