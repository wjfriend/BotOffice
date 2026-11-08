"""Desktop application entry point.

The backend runs as an in-process background thread so the user sees a
single native window: no console, no browser, no manual port.

Run:  python -m botoffice.gui
"""

from __future__ import annotations

import gc
import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from ..app import OfficeContext, create_app
from .client import BackgroundCaller, OfficeApi
from .main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent.parent


def find_free_port() -> int:
    """Ask the OS for a free port so two instances never collide."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BackgroundServer:
    """Runs the FastAPI app on a worker thread."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.context = OfficeContext(ROOT)
        self.app = create_app(self.context)
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("backend did not start within 30s")

    def stop(self) -> None:
        self._server.should_exit = True


class Bridge(QObject):
    """Carries results from the worker thread onto the UI thread."""

    result = Signal(int, object)
    error = Signal(int, str)


class StreamBridge(QObject):
    """Carries bus events from the SSE thread onto the UI thread."""

    event = Signal(object)


class CallbackOffice:
    """The window's view of the backend: every call carries its callback."""

    def __init__(self, caller: BackgroundCaller, bridge: Bridge) -> None:
        self._caller = caller
        self._bridge = bridge
        self._handlers: dict[int, object] = {}

    def get(self, path: str, handler=None) -> None:
        # The worker thread can answer before this method returns, so the
        # handler must be registered before the request is sent. Reserving
        # the id first guarantees that.
        request_id = self._caller.reserve()
        if handler:
            self._handlers[request_id] = handler
        self._caller.send(request_id, self._caller.api.call_get, (path,))

    def post(self, path: str, body: dict, handler=None) -> None:
        request_id = self._caller.reserve()
        if handler:
            self._handlers[request_id] = handler
        self._caller.send(request_id, self._caller.api.call_post, (path, body))

    def delete(self, path: str, handler=None) -> None:
        request_id = self._caller.reserve()
        if handler:
            self._handlers[request_id] = handler
        self._caller.send(request_id, self._caller.api.call_delete, (path,))

    def dispatch(self, request_id: int, value: object) -> None:
        handler = self._handlers.pop(request_id, None)
        if callable(handler):
            handler(value)

    def report_error(self, request_id: int, message: str) -> None:
        self._handlers.pop(request_id, None)
        print(f"[gui] backend error: {message}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    port = find_free_port()
    server = BackgroundServer(port)
    server.start()

    # Hook scripts read this to find the hub without any configuration.
    try:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "hub.port").write_text(str(port), encoding="utf-8")
    except OSError:
        pass

    api = OfficeApi(f"http://127.0.0.1:{port}")
    bridge = Bridge()
    office = CallbackOffice(BackgroundCaller(api, bridge.result.emit, bridge.error.emit), bridge)

    window = MainWindow(office)
    window.show()

    # Cyclic collection running in a worker thread while the UI thread
    # imports or paints crashes CPython 3.14 on Windows. Reference counting
    # still frees everything without cycles, so the cyclic collector is
    # switched off for the life of the app.
    gc.disable()

    bridge.result.connect(office.dispatch)
    bridge.error.connect(office.report_error)

    # The event stream drives the scene animation. Events arrive on the SSE
    # thread, so they are re-emitted through a Qt signal and handled on the
    # UI thread where touching widgets is safe.
    stream_bridge = StreamBridge()

    def apply_event(event: dict) -> None:
        event_type = event.get("type")
        scene = window.scene_widget.scene
        agent_id = event.get("id")
        window.record_activity(event)
        if event_type == "agent.move" and agent_id in scene.avatars:
            avatar = scene.avatars[agent_id]
            target = event.get("to") or [0.0, 0.0]
            avatar.move_to(float(target[0]), float(target[1]))
        elif event_type == "agent.say" and agent_id in scene.avatars:
            avatar = scene.avatars[agent_id]
            avatar.bubble = event.get("text", "")[:40]
            avatar.bubble_until = time.time() + 6
        elif event_type == "agent.state" and agent_id in scene.avatars:
            scene.avatars[agent_id].state = event.get("state", "idle")
            window.refresh_staff()
        elif event_type == "employee.hired":
            window.refresh_all()
        elif event_type in (
            "task.created", "task.assigned", "handoff.done",
            "meeting.started", "meeting.ended",
            "interact.started", "interact.ended",
        ):
            window.refresh_board()

    stream_bridge.event.connect(apply_event)
    stream_stop = threading.Event()

    def on_event(event: dict) -> None:
        # The listener thread must not emit into a window that is going away.
        if stream_stop.is_set():
            return
        stream_bridge.event.emit(event)

    stream_thread: threading.Thread | None = None

    def start_stream() -> None:
        nonlocal stream_thread

        def run() -> None:
            api.listen(on_event, stream_stop)

        stream_thread = threading.Thread(target=run, daemon=True)
        stream_thread.start()

    QTimer.singleShot(600, start_stream)
    window.refresh_all()

    def shutdown() -> None:
        """Stop the background threads before Qt destroys the widgets."""
        stream_stop.set()
        try:
            stream_bridge.event.disconnect(apply_event)
        except (RuntimeError, TypeError):
            pass
        office._caller.stop()
        server.stop()

    app.aboutToQuit.connect(shutdown)

    window._server = server
    exit_code = app.exec()
    stream_stop.set()
    if stream_thread is not None:
        stream_thread.join(timeout=1.5)
    office._caller.join(1.5)
    # A network thread may still be blocked on a read. Exiting hard avoids
    # interpreter teardown crashing on a half-finished asyncio loop.
    os._exit(exit_code)


if __name__ == "__main__":
    sys.exit(main())
