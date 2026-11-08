"""The agent loop.

One loop serves every role (constraint 13). A role changes the inputs, not
the machinery:

    system prompt   = role responsibilities + scope + available tools
    model           = role.llm binding
    tools           = role.scope.tools subset of the global registry
    memory scopes   = role.scope.memory_read / memory_write

Loop shape:

    build context -> ask the model -> parse the reply -> run tools ->
    feed tool results back -> repeat until the model stops asking for tools

The model decides *what* to do; code decides *whether it is allowed* and
*what actually happens* (Rule 5 in the global guidance).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..bus import EventBus
from ..llm.router import ModelBinding, ModelRouter
from ..memory import MemoryStore, assemble_context, estimate_tokens
from .tools import ToolRegistry

log = logging.getLogger(__name__)

MAX_TURNS = 8
MAX_TOOL_CALLS_PER_TURN = 3

# The model is asked to answer with a small JSON object. Anything else is
# treated as plain speech.
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_TEMPLATE = """You are {name}, working in a virtual office as a {role}.

Responsibilities:
{responsibilities}

Department: {department}
Your visible scope:
- memory you may read: {read_scopes}
- memory you may write: {write_scopes}

Tools you may use:
{tools}

Rules:
- Reply with a single JSON object and nothing else.
- Allowed shapes:
  {{"say": "..."}}                         speak to the room
  {{"tool": "name", "args": {{...}}}}      call one tool
  {{"say": "...", "tool": "name", "args": {{...}}}}  speak, then call a tool
- Prefer one action per reply. Use a tool only when you really need it.
- Keep {{"say"}} under 60 words and in the language of the conversation.
- You cannot call tools outside your list. Do not invent tool names.
"""


@dataclass
class AgentTurn:
    """Result of one agent run."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    turns: int = 0
    provider_id: str = ""
    tokens: int = 0

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "tool_calls": self.tool_calls,
            "turns": self.turns,
            "provider_id": self.provider_id,
            "tokens": self.tokens,
        }


def build_system_prompt(role, tool_specs: list[dict]) -> str:
    """Assemble the system prompt from the role and its allowed tools."""
    if tool_specs:
        tool_lines = "\n".join(
            f"- {spec['name']}: {spec['description']} "
            f"(args: {json.dumps(spec['input_schema'], ensure_ascii=False)})"
            for spec in tool_specs
        )
    else:
        tool_lines = "- (no tools available in your scope)"
    responsibilities = role.responsibilities.strip() or f"Handle {role.role} work."
    return SYSTEM_TEMPLATE.format(
        name=role.name,
        role=role.role or role.name,
        responsibilities=responsibilities,
        department=role.department,
        read_scopes=", ".join(role.scope.memory_read) or "(none)",
        write_scopes=", ".join(role.scope.memory_write) or "(none)",
        tools=tool_lines,
    )


def parse_reply(raw: str) -> dict:
    """Parse the model's reply into an action dict.

    Falls back to plain speech when the reply is not valid JSON, so a
    slightly off-format model still produces a usable turn.
    """
    text = (raw or "").strip()
    if not text:
        return {"say": "", "tool": None, "args": {}, "parsed": False}

    candidate = text
    if not candidate.startswith("{"):
        match = _JSON_BLOCK.search(text)
        if match:
            candidate = match.group(0)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return {"say": text, "tool": None, "args": {}, "parsed": False}

    if not isinstance(data, dict):
        return {"say": text, "tool": None, "args": {}, "parsed": False}

    tool = data.get("tool")
    args = data.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    return {
        "say": str(data.get("say") or ""),
        "tool": str(tool) if tool else None,
        "args": args,
        "parsed": True,
    }


class AgentRuntime:
    """Runs one role against the shared tool registry."""

    def __init__(
        self,
        router: ModelRouter,
        registry: ToolRegistry,
        memory: MemoryStore,
        bus: EventBus,
        registry_for=None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.memory = memory
        self.bus = bus
        # Optional: resolve a per-team registry so each team works in its
        # own folder without changing every call site.
        self.registry_for = registry_for

    async def run(
        self,
        role,
        instruction: str,
        *,
        binding: ModelBinding | None = None,
        context_blocks: list[tuple[str, str]] | None = None,
        task_id: str | None = None,
    ) -> AgentTurn:
        """Run one role to completion and return what it said and did."""
        binding = binding or role.llm
        registry = self.registry
        if self.registry_for is not None:
            registry = self.registry_for(getattr(role, "team", "general"))
        tool_specs = registry.specs_for(role.scope.tools)
        system_prompt = build_system_prompt(role, tool_specs)

        messages: list[dict] = []
        budget = binding.budget_tokens or 8000
        blocks = list(context_blocks or [])
        blocks.append(("instruction", instruction))
        context_text, context_stats = assemble_context(blocks, budget)
        messages.append({"role": "user", "content": context_text})

        turn = AgentTurn()
        for step in range(MAX_TURNS):
            turn.turns = step + 1
            self.bus.publish(
                "agent.think", id=role.id, turn=step + 1, provider=binding.primary
            )
            try:
                raw, provider_id = await self.router.chat(
                    binding, system_prompt, messages
                )
            except Exception as exc:  # noqa: BLE001 - report and stop the loop
                self.bus.publish("agent.error", id=role.id, error=str(exc))
                turn.text = turn.text or f"Model call failed: {exc}"
                return turn

            turn.provider_id = provider_id
            turn.tokens += estimate_tokens(raw)
            action = parse_reply(raw)

            if action["say"]:
                turn.text = action["say"]
                self.bus.publish("agent.say", id=role.id, text=action["say"])

            if not action["tool"]:
                return turn

            tool_name = action["tool"]
            if not any(spec["name"] == tool_name for spec in tool_specs):
                # The model asked for a tool outside its scope. Say so and let
                # it try again rather than silently doing nothing.
                self.bus.publish(
                    "agent.tool_denied", id=role.id, tool=tool_name
                )
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "error": f"tool {tool_name!r} is not available to you",
                                "available": [s["name"] for s in tool_specs],
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            result = await registry.call(tool_name, action["args"])
            turn.tool_calls.append({"tool": tool_name, "args": action["args"], "result": result})
            self.bus.publish(
                "agent.tool_call",
                id=role.id,
                tool=tool_name,
                args=action["args"],
                ok=bool(result.get("ok")),
            )

            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {"tool_result": result}, ensure_ascii=False
                    ),
                }
            )

        self.bus.publish("agent.max_turns", id=role.id, turns=MAX_TURNS)
        return turn
