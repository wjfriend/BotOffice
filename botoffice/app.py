"""FastAPI application: REST endpoints plus an SSE event stream.

The 3D layer connects to the SSE stream and renders events. It may only
*request* interactions through the REST API; it never decides on its own
(constraint 10).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent.builtin_tools import register_browser_tools, register_tarsier_tools
from .agent.runtime import AgentRuntime
from .agent.tools import Tool, ToolRegistry
from .bus import EventBus
from .external.ingest import BusIngest
from .llm.client import LLMClient
from .llm.providers import ProviderRegistry
from .llm.router import ModelRouter
from .logging_setup import get_logger, setup_logging
from .memory import MemoryStore
from .orchestrator.board import TaskBoard
from .orchestrator.office import OfficeManager
from .orchestrator.roles import Role, RoleRegistry, RoleScope
from .orchestrator.teams import TeamRegistry
from .orchestrator.tasks import Orchestrator

log = get_logger("botoffice.app")

ROOT = Path(__file__).resolve().parent.parent


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
        self.ingest = BusIngest(self)
        self.orchestrator = Orchestrator(
            self.roles, self.offices, self.runtime, self.memory, self.bus
        )

        # Give every loaded role a desk in its own team's office.
        for role in self.roles.list():
            self.offices.office_for(role.team).assign_desk(role)

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
            "roles": [role.as_dict() for role in roles],
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
