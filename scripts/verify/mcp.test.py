"""End-to-end check of the MCP client.

Starts a real MCP server over stdio, lists its tools, registers them as
office tools, and calls one through the same registry every team uses.
The HTTP side (add, list, remove) is checked separately.

Run: python scripts/verify/mcp.test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from botoffice.agent.mcp import McpServer  # noqa: E402
from botoffice.app import OfficeContext, create_app  # noqa: E402

SCRIPT = ROOT / "scripts" / "verify" / "mcp_echo_server.py"
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def make_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="botoffice-mcp-"))
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    (root / "config" / "providers.json").write_text(
        json.dumps({"providers": []}), encoding="utf-8"
    )
    (root / "config" / "roles.json").write_text(
        json.dumps({"roles": []}), encoding="utf-8"
    )
    return root


async def use_client(context: OfficeContext) -> None:
    server = McpServer(id="echo", name="Echo", command=sys.executable,
                       args=[str(SCRIPT)])
    context.mcp.add(server)

    print("=== 2. connecting lists the server's tools ===")
    tools = await context.mcp.connect("echo", working_dir=context.root / "workspace")
    check("one tool discovered", len(tools) == 1, str([tool["name"] for tool in tools]))
    check("tool carries a schema",
          bool(tools) and "properties" in tools[0].get("schema", {}), "")
    check("server is marked connected", context.mcp.get("echo").connected is True)

    print("=== 3. the tools become office tools ===")
    names = context.register_mcp_tools("echo", tools)
    check("registered under a namespaced name", names == ["mcp_echo_echo"], str(names))
    registry = context.registry_for("general")
    available = {tool.name for tool in registry.list()}
    check("visible to a team registry", "mcp_echo_echo" in available, str(sorted(available))[:120])

    print("=== 4. calling the tool goes through to the server ===")
    result = await registry.call("mcp_echo_echo", {"text": "hi"})
    check("the tool answers", result.get("ok") is True, str(result)[:120])
    check("the payload round-trips", result.get("result") == "echo: hi",
          str(result.get("result")))

    print("=== 5. disconnect clears the tools ===")
    await context.mcp.disconnect("echo")
    context._unregister_mcp_tools("echo")
    after = {tool.name for tool in context.registry_for("general").list()}
    check("tool is gone", "mcp_echo_echo" not in after, str(sorted(after))[:120])


def main() -> int:
    root = make_root()
    context = OfficeContext(root)
    asyncio.run(use_client(context))

    print("=== 6. the HTTP side manages servers ===")
    client = TestClient(create_app(context))
    created = client.post(
        "/api/mcp",
        json={"id": "echo", "name": "Echo", "command": sys.executable,
              "args": [str(SCRIPT)]},
    )
    check("server added", created.status_code == 200, str(created.status_code))
    listed = client.get("/api/mcp").json()["servers"]
    check("server listed", len(listed) == 1, str(listed[0].get("id") if listed else ""))
    bad = client.post("/api/mcp", json={"id": "", "command": ""})
    check("missing fields rejected", bad.status_code == 400, str(bad.status_code))
    client.delete("/api/mcp/echo")
    gone = client.get("/api/mcp").json()["servers"]
    check("server removed", len(gone) == 0, str(len(gone)))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
