"""Check the "new conversation" flow and the task board.

Asserts the product rules that matter:

  - the first employee in an empty office becomes the Lead
  - later employees are members, and get their own desks
  - an external runtime (claude-code) is stored as kind=external
  - the board endpoint answers and the status endpoint reports the office

Runs against a throw-away root so the real config is never touched.

Run: python scripts/verify/employee.test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
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


def build_client() -> TestClient:
    root = Path(tempfile.mkdtemp(prefix="botoffice-verify-"))
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "config" / "providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "mock",
                        "protocol": "mock",
                        "base_url": "",
                        "api_key": "",
                        "model": "mock-1",
                        "label": "Mock",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "config" / "roles.json").write_text(json.dumps({"roles": []}), encoding="utf-8")
    context = OfficeContext(root)
    return TestClient(create_app(context))


def main() -> int:
    client = build_client()

    print("=== 1. empty office starts with nobody ===")
    status = client.get("/api/status").json()
    check("office is empty", len(status["roles"]) == 0, str(len(status["roles"])))

    print("=== 2. first employee becomes the Lead ===")
    first = client.post(
        "/api/employees",
        json={
            "id": "lead",
            "name": "Lead",
            "role": "Boss",
            "runtime": "builtin",
            "provider": "mock",
            "department": "general",
        },
    ).json()
    check("first employee is lead", first.get("rank") == "lead", str(first.get("rank")))
    check("lead flag is set", first.get("leader") is True)
    check("lead got the first desk", first.get("desk") == [-6.0, -3.6], str(first.get("desk")))

    print("=== 3. the second employee is a member ===")
    second = client.post(
        "/api/employees",
        json={
            "id": "worker",
            "name": "Worker",
            "role": "Engineer",
            "runtime": "builtin",
            "provider": "mock",
            "department": "frontend",
        },
    ).json()
    check("second employee is member", second.get("rank") == "member", str(second.get("rank")))
    check("second employee has a different desk", second.get("desk") != first.get("desk"))

    print("=== 4. an external runtime is recorded as external ===")
    external = client.post(
        "/api/employees",
        json={
            "id": "claude",
            "name": "Claude Code",
            "role": "Coder",
            "runtime": "claude-code",
        },
    ).json()
    check("kind is external", external.get("kind") == "external", str(external.get("kind")))
    check(
        "runtime is stored",
        (external.get("external") or {}).get("runtime") == "claude-code",
        str(external.get("external")),
    )

    print("=== 5. unknown provider is rejected ===")
    bad = client.post(
        "/api/employees",
        json={"id": "bad", "name": "Bad", "runtime": "builtin", "provider": "nope"},
    )
    check("unknown provider returns 400", bad.status_code == 400, str(bad.status_code))

    print("=== 6. the board answers ===")
    board = client.get("/api/tasks").json()
    check("board has a task list", isinstance(board.get("tasks"), list))
    check("board has a summary", isinstance(board.get("summary"), dict))

    print("=== 7. status reports every employee ===")
    status = client.get("/api/status").json()
    check("three employees", len(status["roles"]) == 3, str(len(status["roles"])))
    check("layout has desks for each", len(status["layout"]["desks"]) == 3)

    print("=== 8. you can talk to an internal employee ===")
    reply = client.post("/api/agents/worker/say", json={"text": "status?"}).json()
    check("reply comes back", bool(reply.get("text")), str(reply)[:90])
    check("reply is from the worker", reply.get("from") == "worker", str(reply.get("from")))

    print("=== 9. external employees reject direct messages ===")
    bad = client.post("/api/agents/claude/say", json={"text": "hi"})
    check("external returns 400", bad.status_code == 400, str(bad.status_code))

    print("=== 10. teams get their own offices ===")
    alpha = client.post(
        "/api/employees",
        json={
            "id": "bob2",
            "name": "Bob2",
            "runtime": "builtin",
            "provider": "mock",
            "team": "alpha",
        },
    ).json()
    check("team stored", alpha.get("team") == "alpha", str(alpha.get("team")))
    general_status = client.get("/api/status?team=general").json()
    alpha_status = client.get("/api/status?team=alpha").json()
    check("general keeps its staff", len(general_status["roles"]) == 3,
          str(len(general_status["roles"])))
    check("alpha has one employee", len(alpha_status["roles"]) == 1,
          str(len(alpha_status["roles"])))
    check("alpha starts at its own first desk",
          alpha_status["layout"]["desks"].get("bob2") == [-6.0, -3.6],
          str(alpha_status["layout"]["desks"]))
    check("team list is reported", "alpha" in (alpha_status.get("teams") or []),
          str(alpha_status.get("teams")))

    if FAILURES:
        print(f"\n{len(FAILURES)} CHECK(S) FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
