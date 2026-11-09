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

import asyncio
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


def build_client() -> tuple[TestClient, OfficeContext]:
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
    return TestClient(create_app(context)), context


def main() -> int:
    client, context = build_client()

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
    check("lead got the first desk", first.get("desk") == [-5.4, -2.4], str(first.get("desk")))

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
          alpha_status["layout"]["desks"].get("bob2") == [-5.4, -2.4],
          str(alpha_status["layout"]["desks"]))
    check("team list is reported", "alpha" in (alpha_status.get("teams") or []),
          str(alpha_status.get("teams")))

    print("=== 11. each team has its own working folder ===")
    alpha_dir = Path(tempfile.mkdtemp(prefix="botoffice-alpha-"))
    (alpha_dir / "hello.txt").write_text("hi from alpha", encoding="utf-8")
    saved = client.post(
        "/api/teams", json={"id": "alpha", "workspace": str(alpha_dir)}
    ).json()
    check("workspace saved", saved.get("workspace") == str(alpha_dir), str(saved))
    registry = context.registry_for("alpha")
    result = asyncio.run(registry.call("files_read", {"path": "hello.txt"}))
    check("alpha reads from its own folder", result.get("ok") is True, str(result)[:90])
    general_registry = context.registry_for("general")
    check("teams get separate tool sets", registry is not general_registry)

    print("=== 12. the inbox keeps what agents said ===")
    inbox = client.get("/api/inbox").json()
    check("inbox has messages", len(inbox.get("messages", [])) >= 1,
          str(len(inbox.get("messages", []))))
    check("messages start unread", inbox.get("unread", 0) >= 1, str(inbox.get("unread")))
    client.post("/api/inbox/read", json={})
    after = client.get("/api/inbox").json()
    check("marking all read clears the count", after.get("unread") == 0, str(after.get("unread")))

    print("=== 13. each employee has a live log ===")
    log = client.get("/api/agents/worker/log").json().get("log", [])
    check("the worker has log entries", len(log) >= 1, str(len(log)))
    check("entries carry text", all("text" in entry for entry in log))

    print("=== 14. a model can be switched per employee ===")
    switched = client.post(
        "/api/roles/worker/model", json={"primary": "qwen"}
    ).json()
    check("model switched", switched.get("llm", {}).get("primary") == "qwen",
          str(switched.get("llm")))

    print("=== 15. a key can be set and never read back ===")
    (context.root / "config" / "providers.json").write_text(
        json.dumps({"providers": [{"id": "mock", "protocol": "mock",
                                   "base_url": "", "api_key": "", "model": "mock-1"}]}),
        encoding="utf-8",
    )
    client.post("/api/providers/mock/key", json={"api_key": "sk-secret"})
    listed = client.get("/api/providers").json()["providers"][0]
    check("key is not returned", "api_key" not in listed, str(listed))
    check("key is reported as set", listed.get("api_key_set") is True, str(listed))

    print("=== 16. an employee can be duplicated and hidden ===")
    copied = client.post("/api/roles/worker/duplicate").json()
    check("duplicate created", copied.get("id") == "worker-copy", str(copied.get("id")))
    hidden = client.post("/api/roles/worker/hide", json={"hidden": True}).json()
    check("employee hidden", hidden.get("hidden") is True, str(hidden.get("hidden")))

    print("=== 17. a team exports and imports back ===")
    exported = client.get("/api/teams/general/export").json()
    check("export has a filename", exported.get("filename", "").endswith(".md"),
          str(exported.get("filename")))
    markdown = exported.get("markdown", "")
    check("export lists members", "- id:" in markdown, markdown[:60])
    client.delete("/api/roles/lead")
    client.delete("/api/roles/worker")
    client.delete("/api/roles/claude")
    client.delete("/api/roles/worker-copy")
    imported = client.post("/api/teams/import", json={"markdown": markdown}).json()
    check("import recreates the team", len(imported.get("created", [])) >= 1,
          str(imported.get("created")))

    print("=== 18. routines can be created, listed and removed ===")
    created = client.post(
        "/api/routines",
        json={"name": "Daily report", "prompt": "Summarise yesterday.",
              "every_minutes": 60},
    ).json()
    check("routine created", bool(created.get("id")), str(created.get("id")))
    listed = client.get("/api/routines").json()["routines"]
    check("routine listed", len(listed) == 1, str(len(listed)))
    started = client.post(f"/api/routines/{created['id']}/run").json()
    check("run accepted", started.get("ok") is True, str(started))
    client.delete(f"/api/routines/{created['id']}")
    after = client.get("/api/routines").json()["routines"]
    check("routine removed", len(after) == 0, str(len(after)))

    if FAILURES:
        print(f"\n{len(FAILURES)} CHECK(S) FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
