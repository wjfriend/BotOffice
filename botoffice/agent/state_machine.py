"""Visible agent state machine.

The 3D layer renders this state; it never computes it (constraint 10).
States are the same set a viewer would expect to see:

    IDLE -> WALK_TO -> INTERACT -> RETURN_TO_DESK -> IDLE

Every transition publishes an event on the bus so the scene can animate it.
"""

from __future__ import annotations

from enum import Enum

from ..bus import EventBus


class AgentState(str, Enum):
    IDLE = "idle"
    WALKING = "walking"
    INTERACTING = "interacting"
    WORKING = "working"
    WAITING = "waiting"
    MEETING = "meeting"
    RETURNING = "returning"
    OFFLINE = "offline"


# Which transitions are legal. An illegal transition is a bug, so it raises
# instead of silently continuing.
_ALLOWED: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {
        AgentState.WALKING,
        AgentState.WORKING,
        AgentState.INTERACTING,
        AgentState.MEETING,
        AgentState.WAITING,
        AgentState.OFFLINE,
    },
    AgentState.WALKING: {
        AgentState.INTERACTING,
        AgentState.MEETING,
        AgentState.WORKING,
        AgentState.WAITING,
        AgentState.RETURNING,
        AgentState.IDLE,
    },
    AgentState.INTERACTING: {
        AgentState.RETURNING,
        AgentState.WORKING,
        AgentState.WALKING,
        AgentState.MEETING,
        AgentState.WAITING,
        AgentState.IDLE,
    },
    AgentState.MEETING: {
        AgentState.RETURNING,
        AgentState.WORKING,
        AgentState.INTERACTING,
        AgentState.WAITING,
        AgentState.IDLE,
    },
    AgentState.WORKING: {
        AgentState.WALKING,
        AgentState.INTERACTING,
        AgentState.MEETING,
        AgentState.WAITING,
        AgentState.RETURNING,
        AgentState.IDLE,
        AgentState.OFFLINE,
    },
    # Waiting: has work, but is blocked on a person (approval, input).
    AgentState.WAITING: {
        AgentState.IDLE,
        AgentState.WORKING,
        AgentState.WALKING,
        AgentState.INTERACTING,
        AgentState.MEETING,
        AgentState.RETURNING,
        AgentState.OFFLINE,
    },
    AgentState.RETURNING: {
        AgentState.IDLE,
        AgentState.WORKING,
        AgentState.WAITING,
        AgentState.WALKING,
    },
    AgentState.OFFLINE: {AgentState.IDLE},
}


class StateMachine:
    """Tracks one agent's visible state and publishes every change."""

    def __init__(self, agent_id: str, bus: EventBus, initial: AgentState = AgentState.IDLE) -> None:
        self.agent_id = agent_id
        self.bus = bus
        self.state = initial

    def can(self, target: AgentState) -> bool:
        return target in _ALLOWED.get(self.state, set())

    def to(self, target: AgentState, **context: object) -> AgentState:
        """Move to a new state and publish the change."""
        if not self.can(target):
            raise ValueError(
                f"agent {self.agent_id}: illegal transition {self.state.value} -> {target.value}"
            )
        previous = self.state
        self.state = target
        self.bus.publish(
            "agent.state",
            id=self.agent_id,
            state=target.value,
            previous=previous.value,
            **context,
        )
        return target
