"""Application logging: JSON Lines files under log/ with size-based rotation.

Constraint: runtime logs may only be written under log/ (constraint 7 in
CLAUDE.md). Writing a log must never break the main flow, so every failure
here is swallowed and reported on stderr only.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

_configured = False


class JsonLineFormatter(logging.Formatter):
    """Render each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> Path:
    """Configure the root logger once; return the log directory."""
    global _configured
    if _configured:
        return LOG_DIR

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / "app.log", maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(JsonLineFormatter())
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        _configured = True
    except Exception as exc:  # noqa: BLE001 - logging must never break the app
        print(f"[logging] file logging unavailable: {exc!r}", file=sys.stderr)
        root = logging.getLogger()
        if not root.handlers:
            root.addHandler(logging.StreamHandler(sys.stderr))
    return LOG_DIR


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
