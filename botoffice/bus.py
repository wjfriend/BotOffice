"""In-process event bus with wildcard topics and a bounded replay log.

The bus is the only contract between the execution layer and the 3D layer
(constraint 10 in CLAUDE.md): the front end subscribes and renders, it never
decides. A bounded history lets a late subscriber (for example the SSE
endpoint) replay what it missed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

MAX_LOG_EVENTS = 5000


class EventBus:
    """Publish/subscribe bus.

    Topics are dot-separated strings such as "agent.move" or "interact.start".
    A subscriber registered on "*" receives every event.
    """

    def __init__(self, max_log: int = MAX_LOG_EVENTS) -> None:
        self._subscribers: dict[str, list[Callable[[dict], Any]]] = defaultdict(list)
        self._log: list[dict] = []
        self._max_log = max_log
        self._seq = 0
        self._queues: list[asyncio.Queue] = []

    def subscribe(self, topic: str, handler: Callable[[dict], Any]) -> None:
        """Register a handler for an exact topic or for "*"."""
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable[[dict], Any]) -> None:
        handlers = self._subscribers.get(topic)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def publish(self, event_type: str, **data: Any) -> dict:
        """Emit an event.

        "seq", "ts" and "type" are reserved keys. The event type lives under
        "type" rather than "topic" so that business payloads can use a field
        called "topic" (a meeting subject, for example) without colliding.
        """
        event: dict[str, Any] = {"seq": self._seq, "ts": round(time.time(), 3), "type": event_type}
        event.update(data)
        self._seq += 1

        self._log.append(event)
        if len(self._log) > self._max_log:
            del self._log[: len(self._log) - self._max_log]

        for handler in list(self._subscribers.get(event_type, [])):
            self._call(handler, event)
        for handler in list(self._subscribers.get("*", [])):
            self._call(handler, event)

        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A slow consumer must not stall the office; drop the oldest item.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:  # noqa: BLE001
                    pass
        return event

    def history(self, limit: int = 200) -> list[dict]:
        """Most recent events, oldest first."""
        return list(self._log[-limit:])

    def stream(self, maxsize: int = 1000) -> asyncio.Queue:
        """Create a queue that receives every subsequent event."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues.append(queue)
        return queue

    def close_stream(self, queue: asyncio.Queue) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    @staticmethod
    def _call(handler: Callable[[dict], Any], event: dict) -> None:
        try:
            handler(event)
        except Exception as exc:  # noqa: BLE001 - one bad subscriber must not break the bus
            log.warning("subscriber failed: %r", exc)
