"""The office task board.

The board is a read model: it subscribes to the event bus and keeps a small,
in-memory list of what the office is working on right now. Nothing here
decides anything; it only records what already happened so the GUI can show
a Kanban-style overview.

Keeping it in memory is deliberate (constraint 16: no database). The event
log itself is the durable record; the board is a projection of it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ..bus import EventBus

STATUS_QUEUED = "queued"
STATUS_ASSIGNED = "assigned"
STATUS_HANDED_OFF = "handed_off"
STATUS_MEETING = "meeting"
STATUS_CHAT = "chat"
STATUS_DONE = "done"


@dataclass
class BoardTask:
    """One card on the board."""

    id: str
    title: str
    status: str = STATUS_QUEUED
    leader: str = ""
    worker: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "leader": self.leader,
            "worker": self.worker,
            "created_at": round(self.created_at, 3),
            "updated_at": round(self.updated_at, 3),
        }


class TaskBoard:
    """Projects office events into a list of task cards."""

    def __init__(self, bus: EventBus, max_cards: int = 200) -> None:
        self._tasks: dict[str, BoardTask] = {}
        self._lock = threading.RLock()
        self._max_cards = max_cards
        bus.subscribe("*", self._on_event)

    # ------------------------------------------------------------ projection

    def _on_event(self, event: dict) -> None:
        event_type = event.get("type")
        handler = getattr(self, f"_on_{event_type.replace('.', '_')}", None)
        if handler is not None:
            handler(event)

    def _upsert(self, task_id: str, title: str, status: str, **fields) -> BoardTask:
        with self._lock:
            card = self._tasks.get(task_id)
            if card is None:
                card = BoardTask(id=task_id, title=title, status=status)
                self._tasks[task_id] = card
                self._trim()
            if title:
                card.title = title
            card.status = status
            card.updated_at = time.time()
            for key, value in fields.items():
                if value:
                    setattr(card, key, value)
            return card

    def _trim(self) -> None:
        """Drop the oldest cards once the board grows past its cap."""
        if len(self._tasks) <= self._max_cards:
            return
        ordered = sorted(self._tasks.values(), key=lambda card: card.updated_at)
        for card in ordered[: len(self._tasks) - self._max_cards]:
            self._tasks.pop(card.id, None)

    # ------------------------------------------------------------- handlers

    def _on_task_created(self, event: dict) -> None:
        self._upsert(
            event.get("id", ""),
            event.get("task", ""),
            STATUS_QUEUED,
            leader=event.get("leader", ""),
            worker=event.get("worker", ""),
        )

    def _on_task_assigned(self, event: dict) -> None:
        self._upsert(
            event.get("id", ""),
            "",
            STATUS_ASSIGNED,
            worker=event.get("worker", ""),
            leader=event.get("leader", ""),
        )

    def _on_handoff_done(self, event: dict) -> None:
        self._upsert(
            event.get("id", ""),
            "",
            STATUS_HANDED_OFF,
            worker=event.get("receiver", ""),
        )

    def _on_meeting_started(self, event: dict) -> None:
        participants = event.get("participants") or []
        self._upsert(
            event.get("id", ""),
            f"Meeting: {event.get('topic', '')}",
            STATUS_MEETING,
            leader=", ".join(participants),
        )

    def _on_meeting_ended(self, event: dict) -> None:
        self._upsert(event.get("id", ""), "", STATUS_DONE)

    def _on_interact_started(self, event: dict) -> None:
        self._upsert(
            event.get("id", ""),
            f"Talk: {event.get('id', '')} -> {event.get('peer', '')}",
            STATUS_CHAT,
            leader=event.get("id", ""),
            worker=event.get("peer", ""),
        )

    def _on_interact_ended(self, event: dict) -> None:
        self._upsert(event.get("id", ""), "", STATUS_DONE)

    # ---------------------------------------------------------------- read

    def list(self) -> list[dict]:
        with self._lock:
            cards = sorted(self._tasks.values(), key=lambda card: card.updated_at, reverse=True)
            return [card.as_dict() for card in cards]

    def summary(self) -> dict:
        with self._lock:
            counts: dict[str, int] = {}
            for card in self._tasks.values():
                counts[card.status] = counts.get(card.status, 0) + 1
        return {"total": sum(counts.values()), "by_status": counts}
