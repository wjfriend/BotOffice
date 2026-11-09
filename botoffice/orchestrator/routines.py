"""Routines: work that runs on its own, without anyone asking.

A routine is a prompt plus a schedule. The store keeps them in
config/routines.json (no database), and a background thread runs whatever is
due, so the office can do daily reports or hourly checks without the user
sitting there.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHECK_INTERVAL_SECONDS = 30.0


def _minute_floor(moment: "time.struct_time") -> float:
    """Start of the minute a schedule fired in, so it fires once per minute."""
    return time.mktime(
        (moment.tm_year, moment.tm_mon, moment.tm_mday, moment.tm_hour,
         moment.tm_min, 0, 0, 0, -1)
    )


def _match_field(expression: str, value: int) -> bool:
    """Match one cron field: * a-b a,b */n and plain numbers."""
    if expression == "*":
        return True
    if "," in expression:
        return any(_match_field(part, value) for part in expression.split(","))
    if "/" in expression:
        base, _, step_text = expression.partition("/")
        try:
            step = int(step_text)
            if step <= 0:
                return False
            base_value = value if base == "*" else int(base)
        except ValueError:
            return False
        return value % step == 0 and (base == "*" or base_value <= value)
    if "-" in expression:
        low, _, high = expression.partition("-")
        try:
            return int(low) <= value <= int(high)
        except ValueError:
            return False
    try:
        return int(expression) == value
    except ValueError:
        return False


def cron_matches(expression: str, moment: "time.struct_time") -> bool:
    """Match a five-field cron expression (minute hour dom month dow)."""
    fields = expression.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    # Cron uses 0 for Sunday; struct_time tm_wday is 0 for Monday.
    sunday_first = (moment.tm_wday + 1) % 7
    return all((
        _match_field(minute, moment.tm_min),
        _match_field(hour, moment.tm_hour),
        _match_field(dom, moment.tm_mday),
        _match_field(month, moment.tm_mon),
        _match_field(dow, sunday_first),
    ))


@dataclass
class Routine:
    id: str
    name: str
    prompt: str
    every_minutes: int = 0
    at_hour: int = -1
    at_minute: int = 0
    crons: list[str] = field(default_factory=list)
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = round(self.created_at, 3)
        data["last_run"] = round(self.last_run, 3)
        data["crons"] = list(self.crons)
        return data


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


class RoutineStore:
    """Loads and stores routines from a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._routines: dict[str, Routine] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        with self._lock:
            self._routines.clear()
            for item in raw.get("routines", []):
                routine = Routine(**item)
                self._routines[routine.id] = routine

    def save(self) -> None:
        with self._lock:
            payload = {"routines": [routine.as_dict() for routine in self._routines.values()]}
            _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    def add(self, name: str, prompt: str, every_minutes: int = 0,
            at_hour: int = -1, at_minute: int = 0,
            crons: list[str] | None = None) -> Routine:
        routine = Routine(
            id=f"rt-{uuid.uuid4().hex[:8]}",
            name=name,
            prompt=prompt,
            every_minutes=int(every_minutes),
            at_hour=int(at_hour),
            at_minute=int(at_minute),
            crons=list(crons or []),
        )
        with self._lock:
            self._routines[routine.id] = routine
            self.save()
        return routine

    def remove(self, routine_id: str) -> bool:
        with self._lock:
            existed = self._routines.pop(routine_id, None) is not None
        if existed:
            self.save()
        return existed

    def set_enabled(self, routine_id: str, enabled: bool) -> Routine:
        routine = self.get(routine_id)
        routine.enabled = enabled
        self.save()
        return routine

    def get(self, routine_id: str) -> Routine:
        with self._lock:
            routine = self._routines.get(routine_id)
        if routine is None:
            raise KeyError(f"unknown routine {routine_id!r}")
        return routine

    def list(self) -> list[dict]:
        with self._lock:
            routines = sorted(self._routines.values(), key=lambda item: item.created_at)
        return [routine.as_dict() for routine in routines]

    def mark_run(self, routine_id: str) -> None:
        with self._lock:
            routine = self._routines.get(routine_id)
            if routine is None:
                return
            routine.last_run = time.time()
            routine.run_count += 1
            self.save()

    def due(self, now: float | None = None) -> list[Routine]:
        """Routines whose schedule says they should run now."""
        moment = time.localtime(now if now is not None else time.time())
        with self._lock:
            routines = list(self._routines.values())
        due: list[Routine] = []
        for routine in routines:
            if not routine.enabled:
                continue
            if routine.every_minutes > 0:
                elapsed = (time.time() - routine.last_run) / 60.0
                if routine.last_run and elapsed < routine.every_minutes:
                    continue
                due.append(routine)
            elif routine.at_hour >= 0:
                if (moment.tm_hour, moment.tm_min) < (routine.at_hour, routine.at_minute):
                    continue
                today = time.mktime(
                    (moment.tm_year, moment.tm_mon, moment.tm_mday, 0, 0, 0, 0, 0, -1)
                )
                if routine.last_run >= today:
                    continue
                due.append(routine)
        return due


class RoutineRunner:
    """Background thread that runs whatever is due."""

    def __init__(self, store: RoutineStore, run_callback) -> None:
        self.store = store
        self.run_callback = run_callback
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            for routine in self.store.due():
                try:
                    self.run_callback(routine)
                    self.store.mark_run(routine.id)
                except Exception:  # noqa: BLE001 - a failed routine must not stop the loop
                    pass
            self._stop.wait(CHECK_INTERVAL_SECONDS)
