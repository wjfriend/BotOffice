"""Global tool registry.

Every tool is implemented once and shared by every agent (constraint 13).
A role selects which of them it may use through ``scope.tools``; an empty
list means "all of them".

Tool contract:

    name        unique id, snake_case
    description one line, shown to the LLM
    schema      JSON schema of the arguments, shown to the LLM
    handler     async callable(**kwargs) -> str | dict

Optional tools (Browser Use, Tarsier) register themselves only when their
dependency is importable, so the office still starts without them
(constraint 19).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class Tool:
    """One registered capability."""

    name: str
    description: str
    schema: dict
    handler: Callable[..., Any]
    category: str = "general"
    requires: str = ""
    metadata: dict = field(default_factory=dict)

    def spec(self) -> dict:
        """The description the LLM sees."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }


class ToolRegistry:
    """Holds the tools and dispatches calls."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown tool {name!r}; known: {sorted(self._tools)}")
        return tool

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def available_for(self, allowed: list[str]) -> list[Tool]:
        """Tools a role may use. An empty allow-list means all tools."""
        if not allowed:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.name in allowed]

    def specs_for(self, allowed: list[str]) -> list[dict]:
        return [tool.spec() for tool in self.available_for(allowed)]

    def lock_for(self, name: str) -> asyncio.Lock:
        """Per-tool lock.

        Browser tools use it to serialise work on a shared profile
        (constraint 12); other tools get one too so a slow call cannot
        interleave badly with a second call to the same tool.
        """
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    async def call(self, name: str, arguments: dict) -> dict:
        """Run a tool and return a JSON-serialisable result.

        Never raises for tool-level failures: the error is returned so the
        agent loop can feed it back to the LLM and let it recover.
        """
        try:
            tool = self.get(name)
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

        handler = tool.handler
        try:
            signature = inspect.signature(handler)
            accepts_kwargs = any(
                p.kind is inspect.Parameter.VAR_KEYWORD
                for p in signature.parameters.values()
            )
            if not accepts_kwargs:
                signature.bind(**arguments)
        except TypeError as exc:
            return {"ok": False, "error": f"invalid arguments for {name}: {exc}"}

        async with self.lock_for(name):
            try:
                if inspect.iscoroutinefunction(handler):
                    result = await handler(**arguments)
                else:
                    result = await asyncio.to_thread(handler, **arguments)
            except Exception as exc:  # noqa: BLE001 - tool errors must not kill the loop
                log.exception("tool %s failed", name)
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        if isinstance(result, dict):
            payload = dict(result)
            payload.setdefault("ok", True)
            return payload
        return {"ok": True, "result": result}
