"""Command line driver: exercise the office without opening the GUI.

    python -m botoffice.cli status
    python -m botoffice.cli add-role alice "Alice" "Frontend Engineer"
    python -m botoffice.cli assign alice bob "Build the login page"
    python -m botoffice.cli meeting alice,bob "Plan the sprint"
    python -m botoffice.cli interact alice bob
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .agent.builtin_tools import register_files_tools
from .agent.runtime import AgentRuntime
from .agent.tools import ToolRegistry
from .bus import EventBus
from .llm.client import LLMClient
from .llm.providers import ProviderRegistry
from .llm.router import ModelBinding, ModelRouter
from .memory import MemoryStore
from .orchestrator.office import Office
from .orchestrator.roles import Role, RoleRegistry, RoleScope
from .orchestrator.tasks import Orchestrator

ROOT = Path(__file__).resolve().parent.parent


def build_context() -> tuple[OfficeContextLike, Orchestrator]:
    """Assemble the same object graph the server uses."""
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    bus = EventBus()
    providers = ProviderRegistry(ROOT / "config" / "providers.json")
    providers.load()
    roles = RoleRegistry(ROOT / "config" / "roles.json")
    roles.load()
    memory = MemoryStore(data_dir / "memory.json", bus=bus)
    office = Office()
    tools = ToolRegistry()
    register_files_tools(tools, ROOT / "workspace")
    client = LLMClient(providers)
    router = ModelRouter(providers, client)
    runtime = AgentRuntime(router, tools, memory, bus)
    orchestrator = Orchestrator(roles, office, runtime, memory, bus)

    for role in roles.list():
        office.assign_desk(role)

    ctx = OfficeContextLike(bus, providers, roles, memory, office, tools)
    ctx.orchestrator = orchestrator
    return ctx, orchestrator


class OfficeContextLike:
    """Small holder so the CLI and the server share the same wiring."""

    def __init__(self, bus, providers, roles, memory, office, tools) -> None:
        self.bus = bus
        self.providers = providers
        self.roles = roles
        self.memory = memory
        self.office = office
        self.tools = tools
        self.orchestrator = None


def cmd_status(ctx, _args) -> int:
    print(json.dumps({
        "roles": [r.as_dict() for r in ctx.roles.list()],
        "providers": [p.redacted() for p in ctx.providers.list()],
        "tools": [t.name for t in ctx.tools.list()],
        "memory": ctx.memory.stats(),
        "cost": ctx.providers.cost_summary(),
        "layout": ctx.office.landmarks(),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_add_role(ctx, args) -> int:
    role = Role(
        id=args.id,
        name=args.name,
        role=args.role_name,
        department=args.department,
        leader=args.leader,
        responsibilities=args.responsibilities or f"Handle {args.role_name} work.",
        scope=RoleScope(
            memory_read=["global", f"dept:{args.department}", f"private:{args.id}"],
            memory_write=[f"dept:{args.department}", f"private:{args.id}"],
        ),
        llm=ModelBinding(primary=args.model, budget_tokens=args.budget),
    )
    ctx.roles.add(role)
    ctx.office.assign_desk(role)
    print(f"added role {role.id} at desk {ctx.office.desk_of(role.id).as_list()}")
    return 0


def cmd_remove_role(ctx, args) -> int:
    if ctx.roles.remove(args.id):
        ctx.office.release_desk(args.id)
        print(f"removed role {args.id}")
        return 0
    print(f"unknown role {args.id}", file=sys.stderr)
    return 1


def cmd_assign(ctx, args) -> int:
    result = asyncio.run(ctx.orchestrator.assign_task(args.leader, args.worker, args.task))
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_handoff(ctx, args) -> int:
    result = asyncio.run(ctx.orchestrator.handoff(args.from_id, args.to_id, args.summary))
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_meeting(ctx, args) -> int:
    participants = [p.strip() for p in args.participants.split(",") if p.strip()]
    result = asyncio.run(ctx.orchestrator.meeting(participants, args.topic))
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_interact(ctx, args) -> int:
    result = asyncio.run(ctx.orchestrator.interact(args.from_id, args.to_id, args.note))
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_memory(ctx, args) -> int:
    entries = ctx.memory.recall([args.scope] if args.scope else None, limit=args.limit)
    print(json.dumps(entries, ensure_ascii=False, indent=2))
    return 0


def cmd_costs(ctx, _args) -> int:
    print(json.dumps({
        "rows": ctx.providers.cost_summary(),
        "total": ctx.providers.total_cost(),
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="botoffice", description="BotOffice CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="show office state")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("add-role", help="add a character to the office")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("role_name")
    p.add_argument("--department", default="general")
    p.add_argument("--leader", action="store_true")
    p.add_argument("--responsibilities", default="")
    p.add_argument("--model", default="")
    p.add_argument("--budget", type=int, default=8000)
    p.set_defaults(func=cmd_add_role)

    p = sub.add_parser("remove-role", help="remove a character")
    p.add_argument("id")
    p.set_defaults(func=cmd_remove_role)

    p = sub.add_parser("assign", help="leader assigns a task")
    p.add_argument("leader")
    p.add_argument("worker")
    p.add_argument("task")
    p.set_defaults(func=cmd_assign)

    p = sub.add_parser("handoff", help="hand work to another bot")
    p.add_argument("from_id")
    p.add_argument("to_id")
    p.add_argument("summary")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("meeting", help="call a meeting")
    p.add_argument("participants", help="comma separated ids")
    p.add_argument("topic")
    p.set_defaults(func=cmd_meeting)

    p = sub.add_parser("interact", help="two bots talk at a desk")
    p.add_argument("from_id")
    p.add_argument("to_id")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_interact)

    p = sub.add_parser("memory", help="show memory entries")
    p.add_argument("--scope", default="")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_memory)

    p = sub.add_parser("costs", help="show spend per provider")
    p.set_defaults(func=cmd_costs)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx, _ = build_context()
    return args.func(ctx, args)


if __name__ == "__main__":
    sys.exit(main())
