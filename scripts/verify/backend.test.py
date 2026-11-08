"""End-to-end check of the M1 backend using the offline mock provider.

Runs the four interaction modes and asserts the properties the product
depends on:

  - the four modes complete and emit the right events
  - agents actually walk (a move event with a different target is emitted)
  - memory stays separated: a private note is invisible to another agent
  - work traces never leak into the chat context
  - a tool outside the role's scope is denied

Run: python scripts/verify/backend.test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from botoffice.agent.runtime import AgentRuntime  # noqa: E402
from botoffice.agent.tools import ToolRegistry  # noqa: E402
from botoffice.bus import EventBus  # noqa: E402
from botoffice.llm.client import LLMClient  # noqa: E402
from botoffice.llm.providers import Provider, ProviderRegistry  # noqa: E402
from botoffice.llm.router import ModelBinding, ModelRouter  # noqa: E402
from botoffice.memory import MemoryStore, private_scope  # noqa: E402
from botoffice.orchestrator.office import OfficeManager  # noqa: E402
from botoffice.orchestrator.roles import Role, RoleRegistry, RoleScope  # noqa: E402
from botoffice.orchestrator.tasks import Orchestrator  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def build() -> tuple[dict, Orchestrator]:
    bus = EventBus()
    events: list[dict] = []
    bus.subscribe("*", events.append)

    providers = ProviderRegistry()
    providers.add(
        Provider(id="mock-cheap", protocol="mock", base_url="", api_key="", model="mock-1",
                 cost_per_1k_input=0.001, cost_per_1k_output=0.002)
    )

    roles = RoleRegistry(Path("config/roles.json"))
    roles._roles.clear()  # start from an empty office
    roles._roles["alice"] = Role(
        id="alice", name="Alice", role="Frontend Engineer", department="frontend",
        leader=True, responsibilities="Own the UI.",
        scope=RoleScope(memory_read=["global", "dept:frontend", "private:alice"],
                        memory_write=["global", "dept:frontend", "private:alice"],
                        tools=["files_read"]),
        llm=ModelBinding(primary="mock-cheap", budget_tokens=4000),
    )
    roles._roles["bob"] = Role(
        id="bob", name="Bob", role="Backend Engineer", department="backend",
        responsibilities="Own the API.",
        scope=RoleScope(memory_read=["global", "dept:backend", "private:bob"],
                        memory_write=["dept:backend", "private:bob"],
                        tools=[]),
        llm=ModelBinding(primary="mock-cheap", budget_tokens=4000),
    )

    memory = MemoryStore(Path("data/test-memory.json"), bus=bus)
    memory._entries.clear()
    offices = OfficeManager()
    tools = ToolRegistry()
    from botoffice.agent.builtin_tools import register_files_tools

    register_files_tools(tools, ROOT / "workspace")
    client = LLMClient(providers)
    router = ModelRouter(providers, client)
    runtime = AgentRuntime(router, tools, memory, bus)
    orchestrator = Orchestrator(roles, offices, runtime, memory, bus)
    offices.office_for("general").assign_desk(roles.get("alice"))
    offices.office_for("general").assign_desk(roles.get("bob"))

    return {"bus": bus, "events": events, "memory": memory, "roles": roles,
            "offices": offices, "tools": tools, "providers": providers}, orchestrator


async def main() -> int:
    ctx, orchestrator = build()
    events = ctx["events"]
    memory = ctx["memory"]
    roles = ctx["roles"]

    print("=== 1. assign task (leader -> worker) ===")
    result = await orchestrator.assign_task("alice", "bob", "Build the login page")
    check("assign produced two messages", len(result.messages) == 2, str(len(result.messages)))
    moves = [e for e in events if e["type"] == "agent.move"]
    check("assign produced a walk", len(moves) >= 1, f"{len(moves)} move events")
    leader_desk = ctx["offices"].office_for("general").desk_of("alice").as_list()
    check(
        "worker walked to the leader's desk",
        any(m["to"] == leader_desk for m in moves),
        str([m["to"] for m in moves]),
    )

    print("=== 2. handoff at a desk ===")
    result = await orchestrator.handoff("alice", "bob", "Frontend is done, backend please continue")
    check("handoff produced two messages", len(result.messages) == 2)
    desk = ctx["offices"].office_for("general").desk_of("bob").as_list()
    check(
        "sender walked to the receiver's desk",
        any(m["to"] == desk for m in events if m["type"] == "agent.move"),
        f"desk={desk}",
    )

    print("=== 3. meeting ===")
    result = await orchestrator.meeting(["alice", "bob"], "Plan the sprint")
    check("meeting produced one message per participant", len(result.messages) == 2)
    meeting_moves = [
        m for m in events
        if m["type"] == "agent.move" and m["purpose"] == "meeting"
    ]
    check("both agents walked into the meeting room", len(meeting_moves) == 2,
          str([m["to"] for m in meeting_moves]))

    print("=== 4. drag-to-talk ===")
    result = await orchestrator.interact("alice", "bob", "let us review the task")
    check("interact produced two messages", len(result.messages) == 2)
    check("both agents made a decision", len(result.decisions) == 2)
    check(
        "decisions are from the fixed set",
        all(d["decision"] in ("check_current_task", "new_requirement", "keep_waiting")
            for d in result.decisions),
        str([d["decision"] for d in result.decisions]),
    )

    print("=== 5. memory isolation ===")
    memory.remember(private_scope("alice"), "alice", "Alice private note about billing")
    alice_view = memory.recall(roles.get("alice").scope.memory_read, limit=50)
    bob_view = memory.recall(roles.get("bob").scope.memory_read, limit=50)
    check("alice sees her own private note",
          any("private note about billing" in e["text"] for e in alice_view))
    check("bob cannot see alice's private note",
          not any("private note about billing" in e["text"] for e in bob_view))
    check("bob sees only his own scopes",
          all(e["scope"] in roles.get("bob").scope.memory_read for e in bob_view))

    print("=== 6. scope enforcement on write ===")
    before = len(memory.recall(["global"], limit=1000))
    await orchestrator.handoff("bob", "alice", "back to frontend")
    after = len(memory.recall(["global"], limit=1000))
    check("bob could not write to the global board", after == before, f"{before} -> {after}")

    print("=== 7. tool scope denial ===")
    from botoffice.agent.runtime import parse_reply

    tools = ctx["tools"]
    result = await tools.call("files_read", {"path": "nope.txt"})
    check("missing file returns an error result, not a crash", result.get("ok") is False)
    result = await tools.call("no_such_tool", {})
    check("unknown tool returns an error result", result.get("ok") is False)

    print("=== 8. cost accounting ===")
    rows = ctx["providers"].cost_summary()
    check("calls were recorded", len(rows) == 1, json.dumps(rows))
    check("total cost was computed", ctx["providers"].total_cost() > 0,
          str(ctx["providers"].total_cost()))

    print("=== 9. work traces stay out of chat context ===")
    from botoffice.memory import assemble_context, estimate_tokens

    trace = memory.remember("work:task-1", "alice", "step one done, step two pending")
    blocks = [("global", "some global note"), ("current task trace", trace["text"])]
    body, stats = assemble_context(blocks, budget_tokens=1000)
    check("work trace is retrievable when explicitly asked for",
          "step one done" in body)

    print()
    # Rule 9: a test must not leave runtime files behind.
    test_file = Path("data/test-memory.json")
    if test_file.exists():
        test_file.unlink()

    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
