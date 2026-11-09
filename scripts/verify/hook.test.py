"""End-to-end check of the Claude Code hook against a running server.

Starts the real backend on the temp test port, runs the hook script with the
payload Claude Code sends, and asserts the worker appears in the office.

Uses BOTOFFICE_URL so the hook never needs the port file, and a throw-away
root so the real config is never touched.

Run: python scripts/verify/hook.test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from botoffice.app import OfficeContext, create_app  # noqa: E402

TEST_PORT = 3901  # constraint 15: temporary tests use 3901
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{TEST_PORT}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def build_context() -> OfficeContext:
    root = Path(tempfile.mkdtemp(prefix="botoffice-hook-"))
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "config" / "providers.json").write_text(
        json.dumps({"providers": []}), encoding="utf-8"
    )
    (root / "config" / "roles.json").write_text(json.dumps({"roles": []}), encoding="utf-8")
    return OfficeContext(root)


def run_hook(payload: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ, BOTOFFICE_URL=f"http://127.0.0.1:{TEST_PORT}")
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hooks" / "botoffice-hook.py")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
    )


def main() -> int:
    context = build_context()
    app = create_app(context)
    config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        ready = False
        for _ in range(80):
            try:
                get_json("/api/status")
                ready = True
                break
            except Exception:  # noqa: BLE001 - not listening yet
                time.sleep(0.15)
        check("server is up", ready, f"port {TEST_PORT}")

        print("=== 1. a tool-use hook registers a worker ===")
        first = run_hook(
            {
                "session_id": "abc123",
                "hook_event_name": "PostToolUse",
                "tool_name": "Edit",
                "cwd": str(ROOT),
            }
        )
        check("hook exits 0", first.returncode == 0, str(first.returncode))
        check("hook writes nothing to stdout", first.stdout == "", repr(first.stdout))
        agents = get_json("/api/bus/agents").get("agents", [])
        check("a worker is registered", len(agents) == 1, str(agents))
        roles = get_json("/api/status").get("roles", [])
        check("the worker is in the office", len(roles) == 1, str(len(roles)))
        check(
            "the worker is external",
            bool(roles) and roles[0].get("kind") == "external",
            str(roles[0].get("kind")) if roles else "",
        )

        print("=== 2. a permission request becomes an approval ===")
        run_hook(
            {
                "session_id": "abc123",
                "hook_event_name": "Notification",
                "message": "allow this command?",
                "tool_name": "Bash",
            }
        )
        approvals = get_json("/api/approvals").get("approvals", [])
        check("an approval is pending", len(approvals) == 1, str(len(approvals)))

        print("=== 3. stopping the session leaves the worker idle ===")
        run_hook({"session_id": "abc123", "hook_event_name": "Stop"})
        roles = get_json("/api/status").get("roles", [])
        check("the worker is still in the office", len(roles) == 1, str(len(roles)))
        states = get_json("/api/roles").get("roles", [])
        check("the roster survives", len(states) == 1, str(len(states)))
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
