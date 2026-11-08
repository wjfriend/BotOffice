"""Thin client the GUI uses to reach the backend.

Synchronous on purpose. The GUI already runs API calls on one worker thread
and the event stream on another; giving each of them its own asyncio loop
was crashing the process, and there is nothing to gain from async here.
"""

from __future__ import annotations

import json
import threading
import time
from queue import Queue
from typing import Any, Callable

import httpx


def _preload_transport() -> None:
    """Force httpx's lazy imports on the main thread.

    httpx imports its transport stack on first use. Doing that inside a
    worker thread while another thread runs the garbage collector crashes
    CPython 3.14 on Windows, so the imports are forced here, before any
    thread starts.
    """
    with httpx.Client(timeout=1.0):
        pass


_preload_transport()


class OfficeApi:
    """Blocking HTTP client with a streaming event listener."""

    def __init__(self, base_url: str = "http://127.0.0.1:3010") -> None:
        self.base_url = base_url.rstrip("/")

    def call_get(self, path: str) -> Any:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{self.base_url}{path}")
            response.raise_for_status()
            return response.json()

    def call_post(self, path: str, body: dict) -> Any:
        with httpx.Client(timeout=600.0) as client:
            response = client.post(f"{self.base_url}{path}", json=body)
            if response.status_code >= 400:
                return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}
            return response.json()

    def call_delete(self, path: str) -> Any:
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(f"{self.base_url}{path}")
            response.raise_for_status()
            return response.json()

    def listen(
        self,
        sink: Callable[[dict], None],
        stop_event: threading.Event | None = None,
    ) -> None:
        """Consume the event stream and push events into the sink.

        `stop_event` lets the caller shut the loop down cleanly, so no event
        reaches a window that is being destroyed.
        """
        while stop_event is None or not stop_event.is_set():
            try:
                with httpx.Client(timeout=None) as client:
                    with client.stream("GET", f"{self.base_url}/api/stream") as response:
                        for line in response.iter_lines():
                            if stop_event is not None and stop_event.is_set():
                                return
                            if not line.startswith("data:"):
                                continue
                            try:
                                event = json.loads(line[5:].strip())
                            except json.JSONDecodeError:
                                continue
                            sink(event)
            except httpx.HTTPError:
                if stop_event is not None and stop_event.is_set():
                    return
                time.sleep(2.0)


class BackgroundCaller:
    """Runs API calls on a worker thread and delivers results on the UI thread.

    Every request carries an id so the result is routed back to the exact
    callback that asked for it, instead of relying on arrival order.
    """

    def __init__(self, api: OfficeApi, on_result: Callable[[int, Any], None],
                 on_error: Callable[[int, str], None]) -> None:
        self.api = api
        self.on_result = on_result
        self.on_error = on_error
        self._counter = 0
        self._lock = threading.Lock()
        self._queue: "Queue[tuple | None]" = Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._running = True
        self._thread.start()

    def _next_id(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def _loop(self) -> None:
        while self._running:
            job = self._queue.get()
            if job is None:
                break
            request_id, method, args = job
            try:
                result = method(*args)
            except Exception as exc:  # noqa: BLE001
                self.on_error(request_id, str(exc))
                continue
            self.on_result(request_id, result)

    def reserve(self) -> int:
        """Claim a request id before sending, so the handler can be
        registered before the result arrives."""
        return self._next_id()

    def send(self, request_id: int, method, args: tuple) -> None:
        self._queue.put((request_id, method, args))

    def get(self, path: str) -> int:
        request_id = self._next_id()
        self._queue.put((request_id, self.api.call_get, (path,)))
        return request_id

    def post(self, path: str, body: dict) -> int:
        request_id = self._next_id()
        self._queue.put((request_id, self.api.call_post, (path, body)))
        return request_id

    def delete(self, path: str) -> int:
        request_id = self._next_id()
        self._queue.put((request_id, self.api.call_delete, (path,)))
        return request_id

    def stop(self) -> None:
        self._running = False
        self._queue.put(None)

    def join(self, timeout: float = 2.0) -> None:
        """Wait for the worker thread to finish, but never forever."""
        self._thread.join(timeout)
