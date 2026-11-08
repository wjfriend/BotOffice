"""Agent Bus hook: forward one CLI event to BotOffice.

Wire this into a CLI's hook system (for example Claude Code's PostToolUse and
Stop hooks). It reads the hook payload from stdin, posts it to the local hub
and exits.

Hard rules, learned from pixtuoid:

* never block the host CLI - the request has a 200 ms timeout;
* always exit 0, even when BotOffice is closed or the port file is missing;
* never write to stdout, so the host's own output stays clean.

Run: python scripts/hooks/botoffice-hook.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

TIMEOUT_SECONDS = 0.2

ROOT = Path(__file__).resolve().parents[2]
PORT_FILE = ROOT / "data" / "hub.port"

# CLIs name their hooks differently. Keys are compared without separators, so
# "PostToolUse", "post-tool-use" and "post_tool_use" all match.
CLI_EVENTS = {
    "sessionstart": "session_start",
    "sessionend": "session_end",
    "pretooluse": "tool_use",
    "posttooluse": "tool_use",
    "stop": "task_complete",
    "subagentstop": "task_complete",
    "notification": "permission_request",
}

OUR_EVENTS = {
    "session_start",
    "session_end",
    "tool_use",
    "task_complete",
    "heartbeat",
    "permission_request",
}


def hub_url() -> str:
    """Where the hub listens: env override first, then the port file."""
    override = os.environ.get("BOTOFFICE_URL")
    if override:
        return override.rstrip("/")
    try:
        port = PORT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not port:
        return ""
    return f"http://127.0.0.1:{port}"


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return 0

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    payload.setdefault("runtime", os.environ.get("BOTOFFICE_RUNTIME", "claude-code"))
    payload.setdefault("agent", payload.get("session_id") or payload["runtime"])

    # Normalise the host's own hook names onto our bus events. Anything we do
    # not recognise becomes a heartbeat, so a CLI update cannot break the hook.
    raw_event = payload.get("event") or payload.get("hook_event_name") or ""
    key = str(raw_event).replace("_", "").replace("-", "").strip().lower()
    mapped = CLI_EVENTS.get(key) or str(raw_event).strip().lower()
    payload["event"] = mapped if mapped in OUR_EVENTS else "heartbeat"
    if not payload.get("tool") and payload.get("tool_name"):
        payload["tool"] = payload["tool_name"]
    if not payload.get("message") and payload.get("tool_name"):
        payload["message"] = f"used {payload['tool_name']}"

    base = hub_url()
    if not base:
        return 0

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/api/bus/events",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(1024)
    except Exception:  # noqa: BLE001 - the host must never see this fail
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
