"""Inbox: messages the office produced that a person should be able to read.

Agents talk to each other and report back all day. The activity feed scrolls
past; the inbox keeps those messages so you can read them later and see what
you have not looked at yet.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Message:
    id: str
    sender: str
    text: str
    kind: str = "say"
    ts: float = field(default_factory=time.time)
    read: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "text": self.text,
            "kind": self.kind,
            "ts": round(self.ts, 3),
            "read": self.read,
        }


class Inbox:
    """Collects agent messages and tracks what has been read."""

    def __init__(self, bus, limit: int = 300) -> None:
        self._lock = threading.RLock()
        self._items: list[Message] = []
        self._limit = limit
        bus.subscribe("agent.say", self._on_say)
        bus.subscribe("task.assigned", self._on_task_assigned)
        bus.subscribe("handoff.done", self._on_handoff)

    # ------------------------------------------------------------- events

    def _on_say(self, event: dict) -> None:
        self.add(event.get("id", ""), event.get("text", ""), "say")

    def _on_task_assigned(self, event: dict) -> None:
        worker = event.get("worker", "")
        self.add(
            event.get("leader", ""),
            f"assigned a task to {worker}",
            "task",
        )

    def _on_handoff(self, event: dict) -> None:
        self.add(
            event.get("sender", ""),
            f"handed work to {event.get('receiver', '')}",
            "handoff",
        )

    # -------------------------------------------------------------- store

    def add(self, sender: str, text: str, kind: str = "say") -> Message | None:
        text = (text or "").strip()
        if not text:
            return None
        message = Message(
            id=f"msg-{uuid.uuid4().hex[:8]}",
            sender=sender,
            text=text,
            kind=kind,
        )
        with self._lock:
            self._items.append(message)
            if len(self._items) > self._limit:
                del self._items[: len(self._items) - self._limit]
        return message

    def list(self, unread_only: bool = False) -> list[dict]:
        with self._lock:
            items = [
                item for item in self._items if not unread_only or not item.read
            ]
        items.sort(key=lambda item: item.ts, reverse=True)
        return [item.as_dict() for item in items]

    def unread(self) -> int:
        with self._lock:
            return sum(1 for item in self._items if not item.read)

    def mark_all_read(self) -> int:
        with self._lock:
            changed = 0
            for item in self._items:
                if not item.read:
                    item.read = True
                    changed += 1
        return changed
