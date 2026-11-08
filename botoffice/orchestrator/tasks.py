"""The four ways agents interact in the office.

    assign   a leader hands a task to a bot; the bot walks to the leader
    handoff  one bot passes work to another at the other's desk
    meeting  several bots gather in the meeting room
    interact the user drags one avatar onto another and they talk

All four share the same shape:

    walk -> interact -> remember -> return to desk

The user can trigger them from the GUI, and the same events drive the 3D
animation, so dragging an avatar and pressing a button produce identical
behaviour on the backend (constraint 10).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from ..agent.runtime import AgentRuntime
from ..agent.state_machine import AgentState, StateMachine
from ..bus import EventBus
from ..memory import MemoryStore, private_scope, work_scope
from .office import (
    LEADER_OFFICE_DOOR,
    MEETING_ROOM_CENTER,
    Office,
    Point,
    meeting_seat,
    walk_seconds,
)

log = logging.getLogger(__name__)

# The three outcomes an agent can pick when it is asked to talk to a peer.
DECISIONS = ("check_current_task", "new_requirement", "keep_waiting")


@dataclass
class InteractionResult:
    """What happened in one interaction."""

    kind: str
    participants: list[str] = field(default_factory=list)
    task_id: str = ""
    messages: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    memory_written: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "participants": self.participants,
            "task_id": self.task_id,
            "messages": self.messages,
            "decisions": self.decisions,
            "memory_written": self.memory_written,
        }


class Orchestrator:
    """Drives agents through the office."""

    def __init__(
        self,
        roles: "RoleRegistryLike",
        office: Office,
        runtime: AgentRuntime,
        memory: MemoryStore,
        bus: EventBus,
    ) -> None:
        self.roles = roles
        self.office = office
        self.runtime = runtime
        self.memory = memory
        self.bus = bus
        self._machines: dict[str, StateMachine] = {}

    def machine(self, role_id: str) -> StateMachine:
        if role_id not in self._machines:
            self._machines[role_id] = StateMachine(role_id, self.bus)
        return self._machines[role_id]

    # ------------------------------------------------------------- movement

    async def _walk_to(self, role, target: Point, purpose: str) -> None:
        """Move an agent to a point and publish the animation events."""
        machine = self.machine(role.id)
        origin = self.office.desk_of(role.id)
        machine.to(AgentState.WALKING, purpose=purpose)
        self.bus.publish(
            "agent.move",
            id=role.id,
            start=origin.as_list(),
            to=target.as_list(),
            purpose=purpose,
            duration=round(walk_seconds(origin, target), 3),
        )
        await asyncio.sleep(walk_seconds(origin, target))
        machine.to(AgentState.INTERACTING if purpose != "meeting" else AgentState.MEETING,
                   purpose=purpose)

    async def _return_to_desk(self, role) -> None:
        machine = self.machine(role.id)
        if machine.state in (AgentState.OFFLINE, AgentState.IDLE):
            return
        machine.to(AgentState.RETURNING)
        origin = self.office.desk_of(role.id)
        self.bus.publish(
            "agent.move",
            id=role.id,
            start=origin.as_list(),
            to=origin.as_list(),
            purpose="return",
            duration=0.0,
        )
        machine.to(AgentState.IDLE)

    # --------------------------------------------------------------- memory

    def _remember(self, role, scope: str, text: str, task_id: str | None = None) -> dict | None:
        """Write to memory only if the role's scope allows it."""
        if not role.scope.can_write(scope):
            self.bus.publish(
                "memory.denied", id=role.id, scope=scope, reason="scope forbids writing"
            )
            return None
        return self.memory.remember(scope, role.id, text, task_id=task_id)

    def _context_blocks(self, role, task_id: str | None) -> list[tuple[str, str]]:
        """Build the context an agent sees, respecting its read scope."""
        blocks: list[tuple[str, str]] = []
        global_entries = self.memory.recall(["global"], limit=20)
        if global_entries:
            blocks.append(
                ("global memory", "\n".join(f"- {e['text']}" for e in global_entries))
            )
        dept_scope_name = f"dept:{role.department}"
        if role.scope.can_read(dept_scope_name):
            dept_entries = self.memory.recall([dept_scope_name], limit=20)
            if dept_entries:
                blocks.append(
                    (
                        f"department memory ({role.department})",
                        "\n".join(f"- {e['text']}" for e in dept_entries),
                    )
                )
        if role.scope.can_read(private_scope(role.id)):
            own = self.memory.recall([private_scope(role.id)], limit=20)
            if own:
                blocks.append(
                    ("your private notes", "\n".join(f"- {e['text']}" for e in own))
                )
        if task_id:
            work_entries = self.memory.by_task(task_id, limit=20)
            if work_entries:
                blocks.append(
                    (
                        "current task trace",
                        "\n".join(f"- {e['text']}" for e in work_entries),
                    )
                )
        return blocks

    def context_for(self, role, task_id: str | None = None) -> list[tuple[str, str]]:
        """Public access to the context blocks an agent is allowed to see."""
        return self._context_blocks(role, task_id)

    # ---------------------------------------------------------- interactions

    async def assign_task(
        self,
        leader_id: str,
        worker_id: str,
        task: str,
        *,
        task_id: str | None = None,
    ) -> InteractionResult:
        """A leader assigns a task; the worker walks to the leader's office."""
        leader = self.roles.get(leader_id)
        worker = self.roles.get(worker_id)
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        result = InteractionResult(kind="assign", participants=[leader_id, worker_id], task_id=task_id)

        self.bus.publish("task.created", id=task_id, task=task, leader=leader_id, worker=worker_id)

        await self._walk_to(worker, Point(*LEADER_OFFICE_DOOR), "assign")
        machine = self.machine(leader.id)
        machine.to(AgentState.INTERACTING, purpose="assign")

        instruction = (
            f"You are handing the task below to {worker.name}.\n\n"
            f"Task: {task}\n\n"
            "Accept it, state what you need to start, and confirm."
        )
        turn = await self.runtime.run(
            leader,
            instruction,
            context_blocks=self._context_blocks(leader, task_id),
            task_id=task_id,
        )
        result.messages.append({"from": leader_id, "text": turn.text})

        instruction_back = (
            f"{leader.name} handed you this task: {task}\n\n"
            "Confirm you received it and describe your first step."
        )
        turn = await self.runtime.run(
            worker,
            instruction_back,
            context_blocks=self._context_blocks(worker, task_id),
            task_id=task_id,
        )
        result.messages.append({"from": worker_id, "text": turn.text})

        entry = self._remember(
            worker, private_scope(worker_id), f"Task received from {leader.name}: {task}", task_id
        )
        if entry:
            result.memory_written.append(entry)
        entry = self._remember(
            leader, "global", f"{leader.name} assigned '{task}' to {worker.name}", task_id
        )
        if entry:
            result.memory_written.append(entry)

        await self._return_to_desk(worker)
        machine.to(AgentState.IDLE)
        self.bus.publish("task.assigned", id=task_id, worker=worker_id, leader=leader_id)
        return result

    async def handoff(
        self, from_id: str, to_id: str, summary: str, *, task_id: str | None = None
    ) -> InteractionResult:
        """One bot walks to another bot's desk and passes work over."""
        sender = self.roles.get(from_id)
        receiver = self.roles.get(to_id)
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        result = InteractionResult(kind="handoff", participants=[from_id, to_id], task_id=task_id)

        target = self.office.desk_of(to_id)
        await self._walk_to(sender, target, "handoff")
        self.machine(receiver.id).to(AgentState.INTERACTING, purpose="handoff")

        turn = await self.runtime.run(
            sender,
            f"You are at {receiver.name}'s desk. Hand over this work:\n\n{summary}\n\n"
            "Say what is being handed over and what you already did.",
            context_blocks=self._context_blocks(sender, task_id),
            task_id=task_id,
        )
        result.messages.append({"from": from_id, "text": turn.text})

        turn = await self.runtime.run(
            receiver,
            f"{sender.name} handed you this:\n\n{summary}\n\n"
            "Confirm what you received and what you will do next.",
            context_blocks=self._context_blocks(receiver, task_id),
            task_id=task_id,
        )
        result.messages.append({"from": to_id, "text": turn.text})

        entry = self._remember(receiver, private_scope(to_id), f"Handed over: {summary}", task_id)
        if entry:
            result.memory_written.append(entry)
        entry = self._remember(
            sender, private_scope(from_id), f"Handed over to {receiver.name}: {summary}", task_id
        )
        if entry:
            result.memory_written.append(entry)

        await self._return_to_desk(sender)
        self.machine(receiver.id).to(AgentState.IDLE)
        self.bus.publish("handoff.done", id=task_id, sender=from_id, receiver=to_id)
        return result

    async def meeting(
        self, participant_ids: list[str], topic: str, *, task_id: str | None = None
    ) -> InteractionResult:
        """Gather bots in the meeting room and run a short discussion."""
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        participants = [self.roles.get(pid) for pid in participant_ids]
        result = InteractionResult(
            kind="meeting", participants=list(participant_ids), task_id=task_id
        )

        self.bus.publish("meeting.started", id=task_id, topic=topic, participants=participant_ids)

        for index, role in enumerate(participants):
            await self._walk_to(role, meeting_seat(index), "meeting")

        for role in participants:
            others = ", ".join(p.name for p in participants if p.id != role.id)
            turn = await self.runtime.run(
                role,
                f"You are in a meeting about: {topic}\n\n"
                f"Also present: {others}.\n\n"
                "Give one short point and state what you need from the group.",
                context_blocks=self._context_blocks(role, task_id),
                task_id=task_id,
            )
            result.messages.append({"from": role.id, "text": turn.text})

        leader = next((p for p in participants if p.leader), participants[0] if participants else None)
        if leader is not None:
            entry = self._remember(
                leader, "global", f"Meeting about '{topic}' with {len(participants)} people", task_id
            )
            if entry:
                result.memory_written.append(entry)

        for role in participants:
            await self._return_to_desk(role)

        self.bus.publish("meeting.ended", id=task_id, topic=topic)
        return result

    async def interact(self, from_id: str, to_id: str, note: str = "") -> InteractionResult:
        """Two bots talk because the user dragged one onto the other.

        Each bot decides between three options: check the current task, there
        is a new requirement, or keep waiting. The decision is the agent's,
        not the orchestrator's.
        """
        first = self.roles.get(from_id)
        second = self.roles.get(to_id)
        result = InteractionResult(kind="interact", participants=[from_id, to_id])

        self.bus.publish("interact.started", id=from_id, peer=to_id, note=note)

        target = self.office.desk_of(to_id)
        await self._walk_to(first, target, "interact")
        self.machine(second.id).to(AgentState.INTERACTING, purpose="interact")

        prompt = (
            f"You just walked over to {second.name}'s desk"
            + (f" because the user said: {note}" if note else "")
            + ".\n\n"
            "Look at the shared memory and the current task, then decide exactly "
            "one of these:\n"
            "- check_current_task\n"
            "- new_requirement\n"
            "- keep_waiting\n\n"
            'Reply with JSON: {"decision": "<one of the three>", "say": "<what you say>"}'
        )
        for role, peer in ((first, second), (second, first)):
            turn = await self.runtime.run(
                role,
                prompt.replace(second.name, peer.name) if role is first else prompt.replace(
                    second.name, first.name
                ),
                context_blocks=self._context_blocks(role, None),
            )
            decision = _extract_decision(turn.text)
            result.decisions.append({"from": role.id, "decision": decision, "text": turn.text})
            result.messages.append({"from": role.id, "text": turn.text})

        entry = self._remember(
            first,
            "global",
            f"{first.name} and {second.name} discussed: "
            + "; ".join(d["decision"] for d in result.decisions),
        )
        if entry:
            result.memory_written.append(entry)

        await self._return_to_desk(first)
        self.machine(second.id).to(AgentState.IDLE)
        self.bus.publish("interact.ended", id=from_id, peer=to_id)
        return result


def _extract_decision(text: str) -> str:
    """Pull one of the three decisions out of a reply.

    The model may write the decision as "new_requirement" or as
    "new requirement", and may phrase it in a sentence, so both the
    underscore and the space form are matched.
    """
    lowered = (text or "").lower()
    for decision in DECISIONS:
        if decision in lowered or decision.replace("_", " ") in lowered:
            return decision
    if "new requirement" in lowered or "new_requirement" in lowered:
        return "new_requirement"
    if "check" in lowered and "task" in lowered:
        return "check_current_task"
    return "keep_waiting"


class RoleRegistryLike:
    """Structural description of what the orchestrator needs from the registry."""

    def get(self, role_id: str):  # pragma: no cover - interface only
        raise NotImplementedError

    def list(self):  # pragma: no cover - interface only
        raise NotImplementedError
