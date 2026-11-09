"""Groups: several agents in one conversation.

A group is a name plus a roster. When someone speaks in it, every member
takes a turn, so three agents can argue out a plan instead of one agent
guessing on its own.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path


def _atomic_write(path: Path, content: str) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@dataclass
class Group:
    id: str
    name: str
    participants: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "participants": list(self.participants),
            "created_at": round(self.created_at, 3),
        }


class GroupStore:
    """Loads and stores groups from a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._groups: dict[str, Group] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        with self._lock:
            self._groups.clear()
            for item in raw.get("groups", []):
                group = Group(**item)
                self._groups[group.id] = group

    def save(self) -> None:
        with self._lock:
            payload = {"groups": [group.as_dict() for group in self._groups.values()]}
            _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    def add(self, name: str, participants: list[str]) -> Group:
        group = Group(
            id=f"gr-{uuid.uuid4().hex[:8]}",
            name=name,
            participants=[str(item) for item in participants],
            created_at=0.0,
        )
        import time

        group.created_at = time.time()
        with self._lock:
            self._groups[group.id] = group
            self.save()
        return group

    def get(self, group_id: str) -> Group:
        with self._lock:
            group = self._groups.get(group_id)
        if group is None:
            raise KeyError(f"unknown group {group_id!r}")
        return group

    def list(self) -> list[dict]:
        with self._lock:
            groups = sorted(self._groups.values(), key=lambda item: item.created_at)
        return [group.as_dict() for group in groups]

    def remove(self, group_id: str) -> bool:
        with self._lock:
            existed = self._groups.pop(group_id, None) is not None
        if existed:
            self.save()
        return existed
