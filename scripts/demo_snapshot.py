"""Render a demo office and save a screenshot.

This is a development aid, not part of the product. It boots the same
in-process stack the real app uses, seeds a few employees, runs one
drag-to-talk interaction so speech bubbles appear, then saves a PNG.

Run: python scripts/demo_snapshot.py [output.png]
"""

from __future__ import annotations

import gc
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from botoffice.gui.app import (  # noqa: E402
    BackgroundServer,
    Bridge,
    CallbackOffice,
    StreamBridge,
    find_free_port,
)
from botoffice.gui.client import BackgroundCaller, OfficeApi  # noqa: E402
from botoffice.gui.main_window import MainWindow  # noqa: E402

EMPLOYEES = [
    {"id": "lead", "name": "Lead", "role": "Team Lead", "runtime": "builtin",
     "provider": "mock", "department": "general", "avatar": "amber",
     "responsibilities": "Breaks down work, hires, and reviews."},
    {"id": "alice", "name": "Alice", "role": "Frontend Engineer", "runtime": "builtin",
     "provider": "mock", "department": "frontend", "avatar": "red",
     "responsibilities": "Owns the UI and component library."},
    {"id": "bob", "name": "Bob", "role": "Backend Engineer", "runtime": "claude-code",
     "department": "backend", "avatar": "blue",
     "responsibilities": "Owns the API and data."},
    {"id": "carol", "name": "Carol", "role": "Data Analyst", "runtime": "codex",
     "department": "data", "avatar": "green",
     "responsibilities": "Owns the dashboards."},
]


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "office-demo.png"

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    port = find_free_port()
    server = BackgroundServer(port)
    server.start()

    api = OfficeApi(f"http://127.0.0.1:{port}")
    bridge = Bridge()
    office = CallbackOffice(
        BackgroundCaller(api, bridge.result.emit, bridge.error.emit), bridge
    )
    window = MainWindow(office)
    window.show()

    # Cyclic collection running in a worker thread while the UI thread
    # imports or paints crashes CPython 3.14 on Windows. Reference counting
    # still frees everything without cycles, so the cyclic collector is
    # switched off for the life of the app.
    gc.disable()
    bridge.result.connect(office.dispatch)
    bridge.error.connect(office.report_error)

    stream_bridge = StreamBridge()

    def apply_event(event: dict) -> None:
        event_type = event.get("type")
        scene = window.scene_widget.scene
        window.record_activity(event)
        agent_id = event.get("id")
        if event_type == "agent.move" and agent_id in scene.avatars:
            target = event.get("to") or [0.0, 0.0]
            scene.avatars[agent_id].move_to(float(target[0]), float(target[1]))
        elif event_type == "agent.say" and agent_id in scene.avatars:
            avatar = scene.avatars[agent_id]
            avatar.bubble = event.get("text", "")[:40]
            avatar.bubble_until = time.time() + 6
        elif event_type == "agent.state" and agent_id in scene.avatars:
            scene.avatars[agent_id].state = event.get("state", "idle")
            window.refresh_staff()
            window.refresh_stats()
        elif event_type in ("task.created", "task.assigned", "interact.started", "interact.ended"):
            window.refresh_board()

    stream_bridge.event.connect(apply_event)
    stream_stop = threading.Event()

    def on_event(event: dict) -> None:
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

    QTimer.singleShot(500, start_stream)

    def seed() -> None:
        office.post("/api/boss", {}, lambda _result: None)
        for payload in EMPLOYEES:
            office.post("/api/employees", payload, lambda _result: None)
        QTimer.singleShot(1200, window.refresh_all)

    QTimer.singleShot(700, seed)

    def talk() -> None:
        office.post(
            "/api/interactions/interact",
            {"from_id": "lead", "to_id": "alice", "note": "sync on progress"},
            lambda _result: None,
        )

    QTimer.singleShot(2600, talk)

    def snap() -> None:
        window.refresh_board()
        QTimer.singleShot(400, lambda: _save(window, output, app))

    QTimer.singleShot(7000, snap)

    def shutdown() -> None:
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
    os._exit(exit_code)


def _save(window: MainWindow, output: Path, app: QApplication) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(output))
    print(f"saved {output}")
    app.quit()


if __name__ == "__main__":
    sys.exit(main())
