"""Install the BotOffice hook into this machine's Claude Code settings.

The hook tells the office what Claude Code is doing: it posts one small
JSON object to the local hub whenever a tool runs or a session stops.

Safety:
  - the settings file is backed up before anything is written;
  - the edit is only additive (existing keys are kept as they are);
  - running it twice does nothing the second time;
  - the write goes to a temp file that is validated before it replaces
    the original.

Run: python scripts/install_claude_hooks.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = ROOT / "scripts" / "hooks" / "botoffice-hook.py"
MARKER = "botoffice-hook.py"

# Which Claude Code events should reach the office.
HOOK_EVENTS = ("PostToolUse", "Stop", "SessionStart")


def hook_command() -> str:
    """The interpreter that will run the hook script."""
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = ROOT / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else "python"
    return f'"{python}" "{HOOK_SCRIPT}"'


def already_installed(event_hooks: list) -> bool:
    for group in event_hooks:
        for entry in group.get("hooks", []):
            if MARKER in str(entry.get("command", "")):
                return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the BotOffice hook")
    parser.add_argument("--dry-run", action="store_true", help="print only")
    args = parser.parse_args(argv)

    if not SETTINGS.exists():
        print(f"no settings file at {SETTINGS}")
        return 1
    if not HOOK_SCRIPT.exists():
        print(f"hook script missing at {HOOK_SCRIPT}")
        return 1

    original = SETTINGS.read_text(encoding="utf-8")
    settings = json.loads(original)
    hooks = settings.setdefault("hooks", {})

    changed = []
    for event in HOOK_EVENTS:
        group = hooks.setdefault(event, [])
        if already_installed(group):
            continue
        group.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": hook_command()}],
            }
        )
        changed.append(event)

    if not changed:
        print("already installed: " + ", ".join(sorted(hooks)))
        return 0

    rendered = json.dumps(settings, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(f"dry run, would add: {', '.join(changed)}")
        print(rendered)
        return 0

    backup = SETTINGS.with_suffix(f".json.bak-{os.getpid()}")
    shutil.copyfile(SETTINGS, backup)

    directory = SETTINGS.parent
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        json.loads(Path(tmp_name).read_text(encoding="utf-8"))
        os.replace(tmp_name, SETTINGS)
    except BaseException:
        shutil.copyfile(backup, SETTINGS)
        raise

    print(f"backup: {backup}")
    print(f"added hooks: {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
