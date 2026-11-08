"""Agent Bus: turn external CLI activity into office events.

An external CLI (Claude Code, Codex, ...) calls a hook, and the hook POSTs
one small JSON object here. Nothing in this module talks to a model: it only
maps that payload onto the same events the internal agents already emit, so
the scene animates for external workers exactly as it does for built-in ones.

The hook must never block the CLI, so this endpoint is deliberately tiny and
never waits on anything slow.
"""

from __future__ import annotations

import re
import time

from ..llm.router import ModelBinding
from ..orchestrator.roles import KIND_EXTERNAL, Role, RoleScope

_SLUG = re.compile(r"[^a-z0-9]+")

# Which visible state an incoming bus event puts the worker in.
EVENT_TO_STATE = {
    "session_start": "idle",
    "session_end": "offline",
    "tool_use": "working",
    "task_complete": "idle",
    "heartbeat": "idle",
    "permission_request": "interacting",
}

KNOWN_EVENTS = tuple(EVENT_TO_STATE)


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.strip().lower()).strip("-") or "agent"


class BusIngest:
    """Maps Agent Bus payloads onto office events."""

    def __init__(self, context) -> None:
        self.ctx = context
        self.last_seen: dict[str, float] = {}

    # ------------------------------------------------------------------ api

    def handle(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        runtime = str(payload.get("runtime") or "claude-code").strip().lower()
        agent = str(payload.get("agent") or payload.get("session_id") or runtime)
        event = str(payload.get("event") or "").strip().lower()
        if not event:
            raise ValueError("event is required")
        if event not in EVENT_TO_STATE:
            raise ValueError(f"unknown event {event!r}; expected one of {KNOWN_EVENTS}")

        employee_id = self._employee_id(runtime, agent)
        self.last_seen[employee_id] = time.time()
        self._ensure_employee(employee_id, runtime, agent, payload)

        state = EVENT_TO_STATE[event]
        self.ctx.bus.publish(
            "agent.state", id=employee_id, state=state, runtime=runtime
        )
        self.ctx.bus.publish(
            "bus.event",
            runtime=runtime,
            agent=agent,
            event=event,
            tool=payload.get("tool", ""),
            file=payload.get("file", ""),
            message=payload.get("message", ""),
        )
        if event == "tool_use":
            self.ctx.bus.publish(
                "agent.tool_call", id=employee_id, tool=payload.get("tool", "")
            )
        elif event == "task_complete":
            self.ctx.bus.publish(
                "task.done", worker=employee_id, summary=payload.get("message", "")
            )
        elif event == "permission_request":
            self.ctx.bus.publish(
                "agent.say",
                id=employee_id,
                text=payload.get("message") or "needs you",
            )
        return {"ok": True, "employee": employee_id, "state": state}

    def agents(self) -> list[dict]:
        """External workers seen recently, newest first."""
        now = time.time()
        rows = []
        for employee_id, seen in sorted(
            self.last_seen.items(), key=lambda item: item[1], reverse=True
        ):
            rows.append(
                {
                    "id": employee_id,
                    "runtime": self._runtime_of(employee_id),
                    "seconds_since_seen": round(now - seen, 1),
                }
            )
        return rows

    # ------------------------------------------------------------- internal

    @staticmethod
    def _employee_id(runtime: str, agent: str) -> str:
        slug_runtime = _slug(runtime)
        slug_agent = _slug(agent)
        if slug_agent.startswith(slug_runtime):
            return slug_agent[:48]
        return f"{slug_runtime}-{slug_agent}"[:48]

    def _runtime_of(self, employee_id: str) -> str:
        for role in self.ctx.roles.list():
            if role.id == employee_id:
                return (role.external or {}).get("runtime", "")
        return ""

    def _ensure_employee(self, employee_id: str, runtime: str, agent: str,
                         payload: dict) -> None:
        """Create the external employee the first time its hook fires."""
        existing = {role.id for role in self.ctx.roles.list()}
        if employee_id in existing:
            return
        role = Role(
            id=employee_id,
            name=str(payload.get("name") or agent)[:40],
            role=runtime.replace("-", " ").title(),
            kind=KIND_EXTERNAL,
            rank="member",
            department="external",
            responsibilities=f"External worker driven by {runtime}.",
            scope=RoleScope(
                memory_read=["global", "dept:external"],
                memory_write=["dept:external"],
                tools=[],
            ),
            llm=ModelBinding(primary=""),
            external={"runtime": runtime, "session_id": str(payload.get("session_id", ""))},
        )
        self.ctx.hire(role)
