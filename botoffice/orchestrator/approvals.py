"""Approvals: work that needs a human decision before it can continue.

A CLI agent that asks for permission, or an internal agent that wants to do
something risky, raises an approval here. It stays pending until the user
approves or rejects it, and the scene shows the worker as ``waiting``.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


@dataclass
class Approval:
    """One pending decision."""

    id: str
    agent: str
    kind: str
    title: str
    detail: str = ""
    status: str = PENDING
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "created_at": round(self.created_at, 3),
        }


class ApprovalQueue:
    """Collects approvals and lets the user resolve them."""

    def __init__(self, bus) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, Approval] = {}
        bus.subscribe("bus.event", self._on_bus_event)
        bus.subscribe("approval.request", self._on_request)

    # ------------------------------------------------------------- events

    def _on_bus_event(self, event: dict) -> None:
        if event.get("event") != "permission_request":
            return
        self.add(
            agent=event.get("id") or event.get("agent", ""),
            kind="permission",
            title=event.get("message") or "Permission requested",
            detail=event.get("tool", ""),
        )

    def _on_request(self, event: dict) -> None:
        self.add(
            agent=event.get("id") or event.get("agent", ""),
            kind=event.get("kind", "action"),
            title=event.get("title", "Approval needed"),
            detail=event.get("detail", ""),
        )

    # -------------------------------------------------------------- store

    def add(self, agent: str, kind: str, title: str, detail: str = "") -> Approval:
        item = Approval(
            id=f"ap-{uuid.uuid4().hex[:8]}",
            agent=agent,
            kind=kind,
            title=title,
            detail=detail,
        )
        with self._lock:
            self._items[item.id] = item
        return item

    def list(self, status: str | None = PENDING) -> list[dict]:
        with self._lock:
            items = [
                item for item in self._items.values()
                if status is None or item.status == status
            ]
        items.sort(key=lambda item: item.created_at)
        return [item.as_dict() for item in items]

    def resolve(self, approval_id: str, approved: bool) -> Approval:
        with self._lock:
            item = self._items.get(approval_id)
        if item is None:
            raise KeyError(f"unknown approval {approval_id!r}")
        item.status = APPROVED if approved else REJECTED
        return item
