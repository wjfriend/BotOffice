"""Check the Agent Bus entry point.

Asserts the contract a CLI hook depends on:

  - the first event from an unknown runtime creates an external employee
  - each bus event maps onto the same office events internal agents emit
  - an unknown event is rejected instead of silently ignored
  - the agents endpoint reports who has been seen

Runs against a throw-away root so the real config is never touched.

Run: python scripts/verify/bus.test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from botoffice.app import OfficeContext, create_app  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def build_client() -> tuple[TestClient, OfficeContext]:
    root = Path(tempfile.mkdtemp(prefix="botoffice-bus-"))
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "config" / "providers.json").write_text(
        json.dumps({"providers": []}), encoding="utf-8"
    )
    (root / "config" / "roles.json").write_text(json.dumps({"roles": []}), encoding="utf-8")
    context = OfficeContext(root)
    return TestClient(create_app(context)), context


class _Recorder(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            _Recorder.received.append(json.loads(body))
        except json.JSONDecodeError:
            _Recorder.received.append({})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args) -> None:  # noqa: D401 - silence the test
        pass


def check_hook() -> None:
    """The hook must forward a CLI payload and never disturb the host."""
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    port = server.server_address[1]
    threading.Thread(target=server.handle_request, daemon=True).start()

    env = dict(os.environ, BOTOFFICE_URL=f"http://127.0.0.1:{port}")
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hooks" / "botoffice-hook.py")],
        input=json.dumps(
            {"session_id": "abc", "hook_event_name": "PostToolUse", "tool_name": "Edit"}
        ),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    server.server_close()

    check("hook exits 0", process.returncode == 0, str(process.returncode))
    check("hook writes nothing to stdout", process.stdout == "", repr(process.stdout))
    check("hook forwarded one payload", len(_Recorder.received) == 1,
          str(len(_Recorder.received)))
    if _Recorder.received:
        sent = _Recorder.received[0]
        check("hook mapped PostToolUse", sent.get("event") == "tool_use",
              str(sent.get("event")))
        check("hook forwarded the tool", sent.get("tool") == "Edit", str(sent.get("tool")))


def main() -> int:
    client, context = build_client()
    events: list[dict] = []
    context.bus.subscribe("*", events.append)

    print("=== 1. a session_start creates an external employee ===")
    response = client.post(
        "/api/bus/events",
        json={
            "runtime": "claude-code",
            "agent": "claude-code-1",
            "event": "session_start",
        },
    )
    check("request accepted", response.status_code == 200, str(response.status_code))
    body = response.json()
    check("employee id returned", bool(body.get("employee")), str(body.get("employee")))

    roles = client.get("/api/status").json()["roles"]
    check("one employee exists", len(roles) == 1, str(len(roles)))
    check("kind is external", roles[0]["kind"] == "external", roles[0]["kind"])
    check(
        "runtime stored",
        (roles[0].get("external") or {}).get("runtime") == "claude-code",
        str(roles[0].get("external")),
    )

    print("=== 2. tool_use marks the worker as working ===")
    events.clear()
    response = client.post(
        "/api/bus/events",
        json={
            "runtime": "claude-code",
            "agent": "claude-code-1",
            "event": "tool_use",
            "tool": "Edit",
            "file": "src/app.ts",
        },
    )
    check("state is working", response.json().get("state") == "working", str(response.json()))
    states = [e for e in events if e["type"] == "agent.state"]
    check("state event published", bool(states), str(len(states)))
    tools = [e for e in events if e["type"] == "agent.tool_call"]
    check("tool call published", len(tools) == 1, str(len(tools)))

    print("=== 3. a second runtime gets its own employee ===")
    client.post(
        "/api/bus/events",
        json={"runtime": "codex", "agent": "codex-7", "event": "session_start"},
    )
    roles = client.get("/api/status").json()["roles"]
    check("two employees now", len(roles) == 2, str(len(roles)))

    print("=== 4. a finished session leaves the worker idle, not gone ===")
    response = client.post(
        "/api/bus/events",
        json={"runtime": "claude-code", "agent": "claude-code-1", "event": "session_end"},
    )
    check("state is idle", response.json().get("state") == "idle", str(response.json()))
    roles = client.get("/api/status").json()["roles"]
    check("the employee stays in the office", len(roles) == 2, str(len(roles)))

    print("=== 5. an unknown event is rejected ===")
    response = client.post(
        "/api/bus/events",
        json={"runtime": "claude-code", "agent": "x", "event": "nonsense"},
    )
    check("unknown event returns 400", response.status_code == 400, str(response.status_code))

    print("=== 6. the agents endpoint lists who was seen ===")
    agents = client.get("/api/bus/agents").json()["agents"]
    check("two agents reported", len(agents) == 2, str(len(agents)))
    check("each has a runtime", all(a.get("runtime") for a in agents), str(agents))

    print("=== 7. the hook script forwards and maps a CLI payload ===")
    check_hook()

    print("=== 8. a permission request puts the worker in waiting ===")
    response = client.post(
        "/api/bus/events",
        json={
            "runtime": "claude-code",
            "agent": "claude-code-1",
            "event": "permission_request",
            "message": "allow rm -rf?",
        },
    )
    check("state is waiting", response.json().get("state") == "waiting", str(response.json()))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
