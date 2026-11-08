"""Layered memory store.

Four physically separated scopes (constraint 6 in CLAUDE.md):

    global           the company notice board, readable by everyone
    dept:<name>      a department whiteboard, readable by that department
    private:<id>     a personal drawer, readable only by its owner
    work:<task_id>   a work trace, never injected into chat context

Private entries are never returned by a cross-scope read: :func:`recall`
filters by the caller's own scope list, so an agent physically cannot read
another agent's drawer even if it asks for "global".
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable

from ..bus import EventBus

GLOBAL_SCOPE = "global"
DEPT_PREFIX = "dept:"
PRIVATE_PREFIX = "private:"
WORK_PREFIX = "work:"


def scope_kind(scope: str) -> str:
    """Classify a scope string."""
    if scope == GLOBAL_SCOPE:
        return "global"
    if scope.startswith(DEPT_PREFIX):
        return "dept"
    if scope.startswith(PRIVATE_PREFIX):
        return "private"
    if scope.startswith(WORK_PREFIX):
        return "work"
    return "unknown"


def dept_scope(name: str) -> str:
    return f"{DEPT_PREFIX}{name}"


def private_scope(agent_id: str) -> str:
    return f"{PRIVATE_PREFIX}{agent_id}"


def work_scope(task_id: str) -> str:
    return f"{WORK_PREFIX}{task_id}"


class MemoryStore:
    """JSON-backed memory with atomic writes and keyword retrieval."""

    def __init__(self, path: Path, bus: EventBus | None = None) -> None:
        self.path = Path(path)
        self.bus = bus
        self._lock = threading.RLock()
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            self._entries = json.loads(raw) if raw.strip() else []
        except (OSError, json.JSONDecodeError):
            self._entries = []

    def _persist(self) -> None:
        """Atomic write: write to a temp file in the same directory, then replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._entries, ensure_ascii=False, indent=1)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def remember(
        self,
        scope: str,
        author: str,
        text: str,
        *,
        kind: str = "fact",
        task_id: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> dict:
        """Append one entry. Text should already be condensed (see compact.py)."""
        entry = {
            "id": len(self._entries) + 1,
            "ts": round(time.time(), 3),
            "scope": scope,
            "author": author,
            "kind": kind,
            "text": text.strip(),
            "tags": sorted(tags or []),
        }
        if task_id:
            entry["task_id"] = task_id
        with self._lock:
            self._entries.append(entry)
            self._persist()
        if self.bus:
            self.bus.publish(
                "memory.write",
                scope=scope,
                author=author,
                kind=kind,
                entry_id=entry["id"],
                chars=len(entry["text"]),
            )
        return entry

    def recall(self, scopes: Iterable[str] | None, limit: int = 50) -> list[dict]:
        """Return the newest entries whose scope is in the caller's scope list.

        ``scopes=None`` means "every scope" and is only used by the read-only
        inspection endpoints. Agent code always passes an explicit list.
        """
        allowed = set(scopes) if scopes is not None else None
        with self._lock:
            if allowed is None:
                hits = list(self._entries)
            else:
                hits = [e for e in self._entries if e["scope"] in allowed]
        return list(reversed(hits))[:limit]

    def search(
        self,
        query: str,
        scopes: Iterable[str],
        limit: int = 10,
    ) -> list[dict]:
        """Keyword search restricted to the caller's scopes.

        Scoring counts substring hits in text and tags. This is the L2 layer
        placeholder: it needs no embeddings and no extra dependency, and a
        vector index can replace it later without changing the call site.
        """
        allowed = set(scopes)
        needle = query.casefold().strip()
        if not needle:
            return []
        terms = [t for t in needle.replace(",", " ").split() if t]
        scored: list[tuple[float, dict]] = []
        with self._lock:
            for entry in self._entries:
                if entry["scope"] not in allowed:
                    continue
                haystack = entry["text"].casefold()
                tag_blob = " ".join(entry.get("tags", [])).casefold()
                score = 0.0
                for term in terms:
                    if term in haystack:
                        score += 2.0
                    if term in tag_blob:
                        score += 1.0
                if score > 0:
                    scored.append((score, entry))
        scored.sort(key=lambda pair: (pair[0], pair[1]["ts"]), reverse=True)
        return [entry for _, entry in scored[:limit]]

    def by_task(self, task_id: str, limit: int = 200) -> list[dict]:
        """All entries attached to a task, oldest first."""
        with self._lock:
            hits = [e for e in self._entries if e.get("task_id") == task_id]
        return hits[-limit:]

    def stats(self) -> dict:
        """Entry counts per scope kind, for the status panel."""
        counts: dict[str, int] = {}
        with self._lock:
            for entry in self._entries:
                kind = scope_kind(entry["scope"])
                counts[kind] = counts.get(kind, 0) + 1
        return {"total": len(self._entries), "by_kind": counts}
