"""FastAPI application: REST endpoints plus an SSE event stream.

The 3D layer connects to the SSE stream and renders events. It may only
*request* interactions through the REST API; it never decides on its own
(constraint 10).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import yaml
from pydantic import BaseModel, Field

from .agent.builtin_tools import register_browser_tools, register_tarsier_tools
from .agent.mcp import McpRegistry, McpServer
from .agent.runtime import AgentRuntime
from .agent.tools import Tool, ToolRegistry
from .bus import EventBus
from .external.ingest import BusIngest
from .llm.client import LLMClient
from .llm.providers import ProviderRegistry
from .llm.router import ModelRouter
from .logging_setup import get_logger, setup_logging
from .memory import MemoryStore
from .orchestrator.approvals import ApprovalQueue
from .orchestrator.board import TaskBoard
from .orchestrator.groups import GroupStore
from .orchestrator.inbox import Inbox
from .orchestrator.routines import RoutineRunner, RoutineStore
from .orchestrator.office import OfficeManager
from .orchestrator.roles import Role, RoleRegistry, RoleScope
from .orchestrator.teams import TeamRegistry
from .orchestrator.tasks import Orchestrator

log = get_logger("botoffice.app")

ROOT = Path(__file__).resolve().parent.parent


def _slug(text: str) -> str:
    """Make an arbitrary name safe to use inside a tool name."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-") or "x"


class OfficeContext:
    """Everything the app owns, assembled once at startup."""

    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.data_dir = root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.bus = EventBus()
        self.providers = ProviderRegistry(root / "config" / "providers.json")
        self.providers.load()
        self.roles = RoleRegistry(root / "config" / "roles.json")
        self.roles.load()
        self.memory = MemoryStore(self.data_dir / "memory.json", bus=self.bus)
        self.offices = OfficeManager()
        self.tools = ToolRegistry()  # shared tools only: browser, desktop
        self.teams = TeamRegistry(root / "config" / "teams.json", root / "workspace")
        self.teams.load()
        self._team_registries: dict[str, ToolRegistry] = {}
        self.client = LLMClient(self.providers)
        self.router = ModelRouter(self.providers, self.client)
        self.runtime = AgentRuntime(
            self.router, self.tools, self.memory, self.bus,
            registry_for=self.registry_for,
        )
        self.board = TaskBoard(self.bus)
        self.approvals = ApprovalQueue(self.bus)
        self.inbox = Inbox(self.bus)
        self.routines = RoutineStore(root / "config" / "routines.json")
        self.routines.load()
        self.routine_runner = RoutineRunner(self.routines, self.run_routine)
        self.routine_runner.start()
        self.groups = GroupStore(root / "config" / "groups.json")
        self.groups.load()
        self.mcp = McpRegistry(root / "config" / "mcp.json")
        self.mcp.load()
        self._mcp_tool_names: dict[str, list[str]] = {}
        self.ingest = BusIngest(self)
        self.agent_usage: dict[str, dict] = {}
        self.agent_action: dict[str, str] = {}
        self.agent_log: dict[str, list[dict]] = {}
        self.tool_calls: list[dict] = []
        self.bus.subscribe("agent.usage", self._on_usage)
        self.bus.subscribe("agent.say", self._on_say)
        self.bus.subscribe("agent.tool_call", self._on_tool_call)
        self.bus.subscribe("agent.say", self._on_log)
        self.bus.subscribe("agent.tool_call", self._on_log)
        self.bus.subscribe("agent.state", self._on_log)
        self.bus.subscribe("bus.event", self._on_log)

        self.orchestrator = Orchestrator(
            self.roles, self.offices, self.runtime, self.memory, self.bus
        )

        # Give every loaded role a desk in its own team's office.
        for role in self.roles.list():
            self.offices.office_for(role.team).assign_desk(role)

    def _on_usage(self, event: dict) -> None:
        self.agent_usage[event.get("id", "")] = {
            "tokens": int(event.get("tokens") or 0),
            "limit": int(event.get("limit") or 0),
        }

    def _on_say(self, event: dict) -> None:
        text = str(event.get("text", "")).strip()
        if text:
            self.agent_action[event.get("id", "")] = text[:80]

    def _on_log(self, event: dict) -> None:
        """Keep a short per-agent event log for the detail panel."""
        agent_id = event.get("id", "")
        if not agent_id:
            return
        kind = event.get("type", "")
        if kind == "agent.say":
            text = event.get("text", "")
        elif kind == "agent.tool_call":
            text = f"tool: {event.get('tool', '')}"
        elif kind == "agent.state":
            text = f"state: {event.get('state', '')}"
        else:
            text = " ".join(
                str(event.get(key, ""))
                for key in ("event", "tool", "message")
                if event.get(key)
            )
        self.agent_log.setdefault(agent_id, []).append(
            {"ts": event.get("ts"), "type": kind, "text": text}
        )
        self.agent_log[agent_id] = self.agent_log[agent_id][-200:]

    def _on_tool_call(self, event: dict) -> None:
        tool = event.get("tool", "")
        if tool:
            self.agent_action[event.get("id", "")] = f"using {tool}"[:80]
            # Keep a short, global strip of recent tool runs so the chat
            # can show what the office is executing right now.
            self.tool_calls.append(
                {
                    "id": event.get("id", ""),
                    "tool": tool,
                    "ts": event.get("ts"),
                }
            )
            self.tool_calls = self.tool_calls[-30:]

    def _unregister_mcp_tools(self, server_id: str) -> None:
        for name in self._mcp_tool_names.pop(server_id, []):
            self.tools.unregister(name)
        self._team_registries.clear()

    def register_mcp_tools(self, server_id: str, tools: list[dict]) -> list[str]:
        """Expose a connected server's tools as office tools."""
        from .agent.tools import Tool

        self._unregister_mcp_tools(server_id)
        names: list[str] = []
        for tool in tools:
            mcp_name = str(tool.get("name") or "")
            if not mcp_name:
                continue
            name = f"mcp_{_slug(server_id)}_{_slug(mcp_name)}"
            self.tools.register(
                Tool(
                    name=name,
                    description=str(tool.get("description") or mcp_name),
                    schema=tool.get("schema") or {},
                    handler=self._mcp_handler(server_id, mcp_name),
                    category="mcp",
                    requires=server_id,
                    metadata={"server": server_id, "mcp_tool": mcp_name},
                )
            )
            names.append(name)
        self._mcp_tool_names[server_id] = names
        self._team_registries.clear()
        return names

    def _mcp_handler(self, server_id: str, tool_name: str):
        async def handler(**kwargs):
            return await self.mcp.call(server_id, tool_name, kwargs)

        return handler

    def run_routine(self, routine) -> None:
        """Run one routine as the team lead, off the caller's thread.

        A routine is a prompt on a schedule, so it needs the same loop an
        ordinary instruction uses. If the office has nobody to run it, the
        routine is skipped rather than failing loudly.
        """
        role = next(
            (item for item in self.roles.list()
             if item.kind != "user" and item.rank in ("lead", "manager")),
            None,
        ) or next(
            (item for item in self.roles.list() if item.kind != "user"),
            None,
        )
        if role is None:
            return
        self.bus.publish("routine.started", id=routine.id, name=routine.name, by=role.id)
        asyncio.run(
            self.runtime.run(role, routine.prompt, context_blocks=[])
        )

    def hire(self, role: Role) -> Role:
        """Add one employee and give it a desk.

        This is the single place a new character enters the office, whether
        the user clicked "new conversation" or a Lead hired someone.
        """
        desk = self.offices.office_for(role.team).assign_desk(role)
        role.desk = desk
        self.roles.add(role)
        self.bus.publish(
            "employee.hired",
            id=role.id,
            name=role.name,
            rank=role.rank,
            kind=role.kind,
            desk=desk,
        )
        return role

    def registry_for(self, team: str | None) -> ToolRegistry:
        """The tool set for one team.

        Shared tools (browser, desktop) are copied from the global registry;
        the file tools are bound to that team's own workspace, so two teams
        never see each other's project files.
        """
        from dataclasses import asdict

        from .agent.builtin_tools import register_files_tools

        key = (team or "general").strip() or "general"
        registry = self._team_registries.get(key)
        if registry is None:
            registry = ToolRegistry()
            for tool in self.tools.list():
                registry.register(Tool(**asdict(tool)))
            workspace = Path(self.teams.get(key).workspace)
            register_files_tools(registry, workspace, allow_commands=False)
            self._team_registries[key] = registry
        return registry

    async def setup_tools(self, workspace: Path, allow_commands: bool = False) -> None:
        browser_ok = await register_browser_tools(self.tools)
        tarsier_ok = await register_tarsier_tools(self.tools)
        self._team_registries.clear()
        log.info(
            "tools registered: %s (browser=%s tarsier=%s)",
            [t.name for t in self.tools.list()],
            browser_ok,
            tarsier_ok,
        )


# ------------------------------------------------------------------ models


class ProviderIn(BaseModel):
    id: str
    protocol: str = "openai"
    base_url: str
    api_key: str = ""
    model: str
    label: str = ""
    short: str = ""
    currency: str = "CNY"
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    temperature: float = 0.7


class RoleIn(BaseModel):
    id: str
    name: str
    role: str = ""
    kind: str = "builtin"
    department: str = "general"
    leader: bool = False
    rank: str = ""
    responsibilities: str = ""
    memory_read: list[str] = Field(default_factory=lambda: ["global"])
    memory_write: list[str] = Field(default_factory=lambda: ["global"])
    tools: list[str] = Field(default_factory=list)
    model_primary: str = ""
    model_fallback: str = ""
    budget_tokens: int = 8000
    avatar: str = ""
    runtime: str = ""


class EmployeeIn(BaseModel):
    """One entry in the "new conversation" flow.

    runtime is either "builtin" (an internal agent bound to one of the user's
    LLM providers) or an external CLI such as "claude-code".
    """

    id: str
    name: str
    role: str = ""
    runtime: str = "builtin"
    provider: str = ""
    department: str = "general"
    team: str = "general"
    responsibilities: str = ""
    avatar: str = ""


class SayIn(BaseModel):
    text: str


class ModelIn(BaseModel):
    primary: str = ""
    fallback: str = ""
    prefer_cheap: bool = False
    budget_tokens: int | None = None


class KeyIn(BaseModel):
    api_key: str


class HideIn(BaseModel):
    hidden: bool = True


class TeamImportIn(BaseModel):
    markdown: str
    workspace: str = ""


class McpServerIn(BaseModel):
    id: str
    name: str = ""
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict = Field(default_factory=dict)


class RoutineIn(BaseModel):
    name: str
    prompt: str
    every_minutes: int = 0
    at_hour: int = -1
    at_minute: int = 0
    crons: list[str] = Field(default_factory=list)


class GroupIn(BaseModel):
    name: str
    participant_ids: list[str] = Field(default_factory=list)


class GroupMessageIn(BaseModel):
    text: str
    speaker: str = ""


class ApprovalIn(BaseModel):
    approved: bool


class TeamIn(BaseModel):
    id: str
    name: str = ""
    workspace: str


class AssignIn(BaseModel):
    leader_id: str
    worker_id: str
    task: str


class HandoffIn(BaseModel):
    from_id: str
    to_id: str
    summary: str


class MeetingIn(BaseModel):
    participant_ids: list[str]
    topic: str


class InteractIn(BaseModel):
    from_id: str
    to_id: str
    note: str = ""


# -------------------------------------------------------------------- app


def create_app(context: OfficeContext | None = None) -> FastAPI:
    setup_logging()
    ctx = context or OfficeContext()
    app = FastAPI(title="BotOffice", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        await ctx.setup_tools(ctx.root / "workspace")

    # ------------------------------------------------------------- status

    @app.get("/api/status")
    async def status(team: str | None = None) -> dict:
        roles = ctx.roles.list()
        if team:
            roles = [role for role in roles if role.team == team]
        office = ctx.offices.office_for(team or "general")
        return {
            "roles": [
                {
                    **role.as_dict(),
                    "usage": ctx.agent_usage.get(role.id, {}),
                    "action": ctx.agent_action.get(role.id, ""),
                }
                for role in roles
            ],
            "providers": [p.redacted() for p in ctx.providers.list()],
            "tools": [t.name for t in ctx.tools.list()],
            "memory": ctx.memory.stats(),
            "cost": ctx.providers.cost_summary(),
            "total_cost": ctx.providers.total_cost(),
            "layout": office.landmarks(),
            "board": ctx.board.summary(),
            "teams": sorted(
                {role.team for role in ctx.roles.list()}
                | {team.id for team in ctx.teams.list()}
            ) or ["general"],
            "team": team or "general",
        }

    @app.get("/api/tasks")
    async def tasks() -> dict:
        return {"tasks": ctx.board.list(), "summary": ctx.board.summary()}

    # ------------------------------------------------------------ roles

    @app.get("/api/roles")
    async def list_roles() -> dict:
        return {"roles": [role.as_dict() for role in ctx.roles.list()]}

    @app.post("/api/roles")
    async def add_role(payload: RoleIn) -> dict:
        if any(r.id == payload.id for r in ctx.roles.list()):
            raise HTTPException(status_code=409, detail=f"role {payload.id!r} already exists")
        from .llm.router import ModelBinding

        external = {"runtime": payload.runtime} if payload.runtime and payload.runtime != "builtin" else {}
        role = Role(
            id=payload.id,
            name=payload.name,
            role=payload.role,
            kind=payload.kind,
            department=payload.department,
            leader=payload.leader,
            rank=payload.rank,
            responsibilities=payload.responsibilities,
            scope=RoleScope(
                memory_read=payload.memory_read,
                memory_write=payload.memory_write,
                tools=payload.tools,
            ),
            llm=ModelBinding(
                primary=payload.model_primary,
                fallback=payload.model_fallback,
                budget_tokens=payload.budget_tokens,
            ),
            avatar=payload.avatar,
            external=external,
        )
        ctx.hire(role)
        return role.as_dict()

    @app.post("/api/employees")
    async def new_conversation(payload: EmployeeIn) -> dict:
        """Create an employee from the "new conversation" dialog.

        The first employee in an empty office automatically becomes the Lead.
        An external runtime (claude-code, codex, ...) is recorded as kind
        "external"; its model is decided by that CLI, not by us.
        """
        from .llm.router import ModelBinding

        if any(r.id == payload.id for r in ctx.roles.list()):
            raise HTTPException(status_code=409, detail=f"employee {payload.id!r} already exists")

        runtime = (payload.runtime or "builtin").strip()
        is_external = runtime != "builtin"
        if is_external:
            kind = "external"
            external = {"runtime": runtime}
            model_primary = ""
        else:
            kind = "builtin"
            external = {}
            model_primary = payload.provider
            if model_primary and model_primary not in {p.id for p in ctx.providers.list()}:
                raise HTTPException(
                    status_code=400, detail=f"unknown provider {model_primary!r}"
                )

        # The owner is not an employee, so it does not count when deciding
        # who becomes the first Lead.
        first = not any(r.kind != "user" for r in ctx.roles.list())
        role = Role(
            id=payload.id,
            name=payload.name,
            role=payload.role,
            kind=kind,
            department=payload.department,
            team=payload.team or "general",
            leader=first,
            rank="lead" if first else "member",
            responsibilities=payload.responsibilities,
            scope=RoleScope(
                memory_read=["global", f"dept:{payload.department}", f"private:{payload.id}"],
                memory_write=(
                    ["global", f"dept:{payload.department}", f"private:{payload.id}"]
                    if first
                    else [f"dept:{payload.department}", f"private:{payload.id}"]
                ),
                tools=[],
            ),
            llm=ModelBinding(primary=model_primary),
            avatar=payload.avatar,
            external=external,
        )
        ctx.hire(role)
        return role.as_dict()

    @app.post("/api/boss")
    async def add_boss() -> dict:
        """Create the owner's own character.

        This is the user in the office: the person who talks to the Lead and
        hands work down. It is not an employee and never runs an LLM loop.
        """
        from .llm.router import ModelBinding

        if any(r.kind == "user" for r in ctx.roles.list()):
            raise HTTPException(status_code=409, detail="the owner already exists")
        role = Role(
            id="me",
            name="You",
            role="Owner",
            kind="user",
            rank="owner",
            department="general",
            responsibilities=(
                "This is you: the person who talks to the Lead and assigns work."
            ),
            scope=RoleScope(memory_read=["global"], memory_write=["global"]),
            llm=ModelBinding(primary=""),
        )
        ctx.hire(role)
        return role.as_dict()

    @app.get("/api/agents/{agent_id}/log")
    async def agent_log(agent_id: str, limit: int = 100) -> dict:
        return {"log": ctx.agent_log.get(agent_id, [])[-limit:]}

    # ----------------------------------------------------------- model picker

    @app.post("/api/roles/{role_id}/model")
    async def set_role_model(role_id: str, payload: ModelIn) -> dict:
        """Switch an employee's model without recreating the employee."""
        from .llm.router import ModelBinding

        try:
            role = ctx.roles.get(role_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        role.llm = ModelBinding(
            primary=payload.primary or role.llm.primary,
            fallback=payload.fallback or role.llm.fallback,
            prefer_cheap=payload.prefer_cheap,
            budget_tokens=payload.budget_tokens or role.llm.budget_tokens,
        )
        ctx.roles.save()
        ctx.bus.publish("role.updated", id=role.id, primary=role.llm.primary)
        return role.as_dict()

    # ------------------------------------------------------------- secrets

    @app.post("/api/providers/{provider_id}/key")
    async def set_provider_key(provider_id: str, payload: KeyIn) -> dict:
        """Set a provider key. No endpoint ever reads the key back."""
        try:
            provider = ctx.providers.get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        provider.api_key = payload.api_key.strip()
        ctx.providers.add(provider)
        ctx.bus.publish("provider.updated", id=provider.id)
        return {"id": provider.id, "api_key_set": bool(provider.api_key)}

    # ------------------------------------------------------- bot management

    @app.post("/api/roles/{role_id}/duplicate")
    async def duplicate_role(role_id: str) -> dict:
        try:
            source = ctx.roles.get(role_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        copy = dataclasses.replace(
            source,
            id=f"{source.id}-copy",
            name=f"{source.name} Copy",
            hidden=False,
        )
        ctx.hire(copy)
        return copy.as_dict()

    @app.post("/api/roles/{role_id}/hide")
    async def hide_role(role_id: str, payload: HideIn) -> dict:
        try:
            role = ctx.roles.get(role_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        role.hidden = payload.hidden
        ctx.roles.save()
        ctx.bus.publish("role.updated", id=role.id, hidden=role.hidden)
        return role.as_dict()

    # ------------------------------------------------------- team transfer

    @app.get("/api/teams/{team_id}/export")
    async def export_team(team_id: str) -> dict:
        """Write a team as a portable Markdown file with YAML frontmatter."""
        team = ctx.teams.get(team_id)
        members = [role for role in ctx.roles.list() if role.team == team_id]
        lines = [
            "---",
            f"team: {team.id}",
            f"name: {team.name or team.id}",
            f"workspace: {team.workspace}",
            "members:",
        ]
        for member in members:
            lines += [
                f"  - id: {member.id}",
                f"    name: {member.name}",
                f"    role: {member.role}",
                f"    kind: {member.kind}",
                f"    department: {member.department}",
                f"    runtime: {(member.external or {}).get('runtime', '')}",
                f"    provider: {member.llm.primary}",
                f"    responsibilities: {member.responsibilities}",
            ]
        lines += [
            "---",
            "",
            f"# Team {team.id}",
            "",
            f"{len(members)} employees. Import this file to rebuild the team.",
        ]
        return {"filename": f"{team.id}.md", "markdown": "\n".join(lines)}

    @app.post("/api/teams/import")
    async def import_team(payload: TeamImportIn) -> dict:
        """Rebuild a team from the Markdown file the export endpoint writes."""
        from .llm.router import ModelBinding

        text = payload.markdown or ""
        if not text.startswith("---"):
            raise HTTPException(status_code=400, detail="expected a --- frontmatter block")
        try:
            front = text.split("---", 2)[1]
            data = yaml.safe_load(front)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail=f"invalid frontmatter: {exc}") from exc
        if not isinstance(data, dict) or not data.get("team"):
            raise HTTPException(status_code=400, detail="frontmatter must declare a team id")

        team_id = str(data["team"])
        workspace = payload.workspace or str(data.get("workspace") or "")
        if workspace:
            ctx.teams.set_workspace(team_id, workspace)
        else:
            ctx.teams.get(team_id)

        created: list[str] = []
        for item in data.get("members") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            runtime = str(item.get("runtime") or "").strip()
            provider = str(item.get("provider") or "").strip()
            department = str(item.get("department") or "general")
            role = Role(
                id=str(item["id"]),
                name=str(item.get("name") or item["id"]),
                role=str(item.get("role") or ""),
                kind="external" if runtime else "builtin",
                department=department,
                team=team_id,
                responsibilities=str(item.get("responsibilities") or ""),
                scope=RoleScope(
                    memory_read=["global", f"dept:{department}", f"private:{item['id']}"],
                    memory_write=[f"dept:{department}", f"private:{item['id']}"],
                    tools=[],
                ),
                llm=ModelBinding(primary=provider),
                external={"runtime": runtime} if runtime else {},
            )
            ctx.hire(role)
            created.append(role.id)
        ctx.bus.publish("team.imported", team=team_id, employees=len(created))
        return {"team": team_id, "created": created}

    # -------------------------------------------------------------- routines

    @app.get("/api/routines")
    async def list_routines() -> dict:
        return {"routines": ctx.routines.list()}

    @app.post("/api/routines")
    async def add_routine(payload: RoutineIn) -> dict:
        if not payload.name.strip() or not payload.prompt.strip():
            raise HTTPException(status_code=400, detail="name and prompt are required")
        routine = ctx.routines.add(
            payload.name.strip(),
            payload.prompt.strip(),
            payload.every_minutes,
            payload.at_hour,
            payload.at_minute,
            payload.crons,
        )
        ctx.bus.publish("routine.added", id=routine.id, name=routine.name)
        return routine.as_dict()

    @app.delete("/api/routines/{routine_id}")
    async def delete_routine(routine_id: str) -> dict:
        if not ctx.routines.remove(routine_id):
            raise HTTPException(status_code=404, detail="unknown routine")
        return {"ok": True}

    @app.post("/api/routines/{routine_id}/run")
    async def run_routine_now(routine_id: str) -> dict:
        try:
            routine = ctx.routines.get(routine_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        asyncio.create_task(asyncio.to_thread(ctx.run_routine, routine))
        return {"ok": True, "routine": routine.id}

    # ---------------------------------------------------------------- groups

    @app.get("/api/groups")
    async def list_groups() -> dict:
        return {"groups": ctx.groups.list()}

    @app.post("/api/groups")
    async def add_group(payload: GroupIn) -> dict:
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="name is required")
        members = []
        for member_id in payload.participant_ids:
            try:
                ctx.roles.get(member_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            members.append(member_id)
        if len(members) < 2:
            raise HTTPException(status_code=400, detail="a group needs at least two members")
        group = ctx.groups.add(payload.name.strip(), members)
        ctx.bus.publish("group.added", id=group.id, members=len(members))
        return group.as_dict()

    @app.delete("/api/groups/{group_id}")
    async def delete_group(group_id: str) -> dict:
        if not ctx.groups.remove(group_id):
            raise HTTPException(status_code=404, detail="unknown group")
        return {"ok": True}

    @app.post("/api/groups/{group_id}/message")
    async def group_message(group_id: str, payload: GroupMessageIn) -> dict:
        """Every member of the group answers, in turn."""
        try:
            group = ctx.groups.get(group_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")

        ctx.bus.publish("group.message", id=group.id, text=text, speaker=payload.speaker)
        replies = []
        for member_id in group.participants:
            try:
                role = ctx.roles.get(member_id)
            except KeyError:
                continue
            if role.kind == "user":
                continue
            if role.kind == "builtin" and not role.llm.primary:
                continue
            instruction = (
                f"You are in a group chat called {group.name}.\n\n"
                + (f"{payload.speaker} said: {text}" if payload.speaker else f"The user said: {text}")
                + "\n\nGive one short point and state what you need from the group."
            )
            turn = await ctx.runtime.run(
                role,
                instruction,
                context_blocks=ctx.orchestrator.context_for(role),
            )
            ctx.bus.publish("agent.say", id=role.id, text=turn.text)
            replies.append({"from": role.id, "text": turn.text})
        return {"group": group.id, "replies": replies}

    @app.get("/api/tools/recent")
    async def recent_tool_calls(limit: int = 20) -> dict:
        """The latest tool runs, newest first, for the chat strip."""
        items = list(ctx.tool_calls)
        items.reverse()
        return {"tools": items[:limit]}

    # ------------------------------------------------------------------ mcp

    @app.get("/api/mcp")
    async def list_mcp() -> dict:
        return {"servers": ctx.mcp.list()}

    @app.post("/api/mcp")
    async def add_mcp(payload: McpServerIn) -> dict:
        if not payload.id.strip() or not payload.command.strip():
            raise HTTPException(status_code=400, detail="id and command are required")
        server = McpServer(
            id=payload.id.strip(),
            name=payload.name.strip(),
            command=payload.command.strip(),
            args=[str(item) for item in payload.args],
            env={str(k): str(v) for k, v in (payload.env or {}).items()},
        )
        ctx.mcp.add(server)
        ctx.bus.publish("mcp.added", id=server.id)
        return server.as_dict()

    @app.delete("/api/mcp/{server_id}")
    async def remove_mcp(server_id: str) -> dict:
        ctx._unregister_mcp_tools(server_id)
        if not ctx.mcp.remove(server_id):
            raise HTTPException(status_code=404, detail="unknown MCP server")
        return {"ok": True}

    @app.post("/api/mcp/{server_id}/connect")
    async def connect_mcp(server_id: str) -> dict:
        """Start the server and register its tools for every team."""
        try:
            tools = await ctx.mcp.connect(
                server_id, working_dir=ctx.root / "workspace"
            )
        except Exception as exc:  # noqa: BLE001 - report, do not crash the app
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        names = ctx.register_mcp_tools(server_id, tools)
        ctx.bus.publish("mcp.connected", id=server_id, tools=len(names))
        return {"server": server_id, "tools": tools, "registered": names}

    @app.get("/api/inbox")
    async def list_inbox(unread_only: bool = False) -> dict:
        return {
            "messages": ctx.inbox.list(unread_only),
            "unread": ctx.inbox.unread(),
        }

    @app.post("/api/inbox/read")
    async def mark_inbox_read() -> dict:
        return {"changed": ctx.inbox.mark_all_read(), "unread": ctx.inbox.unread()}

    @app.get("/api/approvals")
    async def list_approvals(status: str | None = "pending") -> dict:
        return {"approvals": ctx.approvals.list(status)}

    @app.post("/api/approvals/{approval_id}")
    async def resolve_approval(approval_id: str, payload: ApprovalIn) -> dict:
        try:
            item = ctx.approvals.resolve(approval_id, payload.approved)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return item.as_dict()

    @app.get("/api/teams")
    async def list_teams() -> dict:
        return {"teams": [team.as_dict() for team in ctx.teams.list()]}

    @app.post("/api/teams")
    async def save_team(payload: TeamIn) -> dict:
        """Create a team or change its working directory."""
        team = ctx.teams.set_workspace(payload.id, payload.workspace)
        if payload.name:
            team.name = payload.name
            ctx.teams.save()
        # The tool set is bound to the folder, so rebuild it.
        ctx._team_registries.pop(team.id, None)
        return team.as_dict()

    @app.post("/api/bus/events")
    async def bus_events(payload: dict) -> dict:
        """Entry point for CLI hooks (Claude Code, Codex, ...).

        The hook posts one small JSON object and never waits for a reply, so
        this must stay fast: no model calls, no disk writes.
        """
        try:
            return ctx.ingest.handle(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/bus/agents")
    async def bus_agents() -> dict:
        return {"agents": ctx.ingest.agents()}

    @app.post("/api/agents/{agent_id}/say")
    async def say(agent_id: str, payload: SayIn) -> dict:
        """Send one message to an employee and return their reply.

        Only internal agents can answer: external workers are driven by their
        own CLI, and the owner is the user themselves.
        """
        try:
            role = ctx.roles.get(agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        if role.kind == "user":
            raise HTTPException(status_code=400, detail="this is you")
        if role.kind == "external":
            raise HTTPException(
                status_code=400,
                detail="external agents are driven by their own CLI; messages are not supported yet",
            )
        if not role.llm.primary:
            raise HTTPException(status_code=400, detail=f"{role.id} has no model configured")

        ctx.bus.publish("agent.say", id=role.id, text=text)
        turn = await ctx.runtime.run(
            role,
            text,
            context_blocks=ctx.orchestrator.context_for(role),
        )
        return {"from": role.id, "text": turn.text}

    @app.delete("/api/roles/{role_id}")
    async def delete_role(role_id: str) -> dict:
        try:
            role = ctx.roles.get(role_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        team = role.team
        ctx.roles.remove(role_id)
        ctx.offices.office_for(team).release_desk(role_id)
        ctx.bus.publish("role.removed", id=role_id)
        return {"ok": True}

    # -------------------------------------------------------- providers

    @app.get("/api/providers")
    async def list_providers() -> dict:
        return {"providers": [p.redacted() for p in ctx.providers.list()]}

    @app.post("/api/providers")
    async def add_provider(payload: ProviderIn) -> dict:
        from .llm.providers import Provider

        try:
            provider = Provider(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ctx.providers.add(provider)
        ctx.bus.publish("provider.added", id=provider.id)
        return provider.redacted()

    @app.delete("/api/providers/{provider_id}")
    async def delete_provider(provider_id: str) -> dict:
        if not ctx.providers.remove(provider_id):
            raise HTTPException(status_code=404, detail=f"unknown provider {provider_id!r}")
        return {"ok": True}

    # ------------------------------------------------------- interactions

    @app.post("/api/interactions/assign")
    async def assign(payload: AssignIn) -> dict:
        result = await ctx.orchestrator.assign_task(
            payload.leader_id, payload.worker_id, payload.task
        )
        return result.as_dict()

    @app.post("/api/interactions/handoff")
    async def handoff(payload: HandoffIn) -> dict:
        result = await ctx.orchestrator.handoff(
            payload.from_id, payload.to_id, payload.summary
        )
        return result.as_dict()

    @app.post("/api/interactions/meeting")
    async def meeting(payload: MeetingIn) -> dict:
        result = await ctx.orchestrator.meeting(payload.participant_ids, payload.topic)
        return result.as_dict()

    @app.post("/api/interactions/interact")
    async def interact(payload: InteractIn) -> dict:
        result = await ctx.orchestrator.interact(payload.from_id, payload.to_id, payload.note)
        return result.as_dict()

    # ----------------------------------------------------------- memory

    @app.get("/api/memory")
    async def read_memory(scope: str | None = None, limit: int = 50) -> dict:
        entries = ctx.memory.recall([scope] if scope else None, limit=limit)
        return {"entries": entries}

    @app.get("/api/memory/stats")
    async def memory_stats() -> dict:
        return ctx.memory.stats()

    # ------------------------------------------------------------ costs

    @app.get("/api/costs")
    async def costs() -> dict:
        return {
            "rows": ctx.providers.cost_summary(),
            "total": ctx.providers.total_cost(),
            "usage": [r.as_dict() for r in ctx.providers.usage_records()[-100:]],
        }

    # ------------------------------------------------------------ events

    @app.get("/api/events")
    async def events(limit: int = 200) -> dict:
        return {"events": ctx.bus.history(limit)}

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        """Server-sent events: the live feed the 3D layer subscribes to."""

        async def generator():
            queue = ctx.bus.stream()
            try:
                for event in ctx.bus.history(50):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                ctx.bus.close_stream(queue)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------ static

    public_dir = ctx.root / "public"
    if public_dir.exists():
        app.mount("/", StaticFiles(directory=str(public_dir), html=True), name="public")

    app.state.ctx = ctx
    return app
