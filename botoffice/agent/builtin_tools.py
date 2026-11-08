"""Built-in tools shared by every role.

These are the capabilities that need no external dependency: talking to the
office, reading and writing files, and running a command in a workspace.

Security notes:
- File tools are confined to a workspace root; paths that escape it are
  rejected.
- Command execution runs with that root as the working directory and is
  disabled unless the operator explicitly enables it.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from .tools import Tool, ToolRegistry

DEFAULT_WORKSPACE = "workspace"
MAX_READ_BYTES = 200_000
COMMAND_TIMEOUT = 120


def _safe_path(workspace: Path, raw: str) -> Path:
    """Resolve a path inside the workspace, refusing to escape it."""
    candidate = (workspace / raw).resolve()
    root = workspace.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path {raw!r} is outside the workspace")
    return candidate


def register_files_tools(
    registry: ToolRegistry, workspace: Path, allow_commands: bool = False
) -> None:
    """Register file and command tools bound to a workspace directory."""

    def files_list(**kwargs: object) -> str:
        base = workspace
        if kwargs.get("path"):
            base = _safe_path(workspace, str(kwargs["path"]))
        if not base.exists():
            return f"no such directory: {base}"
        lines = []
        for path in sorted(base.rglob("*")):
            if any(part.startswith(".") for part in path.parts):
                continue
            kind = "dir" if path.is_dir() else "file"
            lines.append(f"{kind}: {path.relative_to(workspace).as_posix()}")
            if len(lines) >= 200:
                lines.append("... (truncated)")
                break
        return "\n".join(lines) or "(empty)"

    def files_read(**kwargs: object) -> dict:
        target = _safe_path(workspace, str(kwargs.get("path", "")))
        if not target.is_file():
            return {"ok": False, "error": f"not a file: {target}"}
        data = target.read_bytes()[:MAX_READ_BYTES]
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary file, {len(data)} bytes>"

    def files_write(**kwargs: object) -> str:
        target = _safe_path(workspace, str(kwargs.get("path", "")))
        content = str(kwargs.get("content", ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {target.relative_to(workspace).as_posix()}"

    def run_command(**kwargs: object) -> str:
        if not allow_commands:
            return "command execution is disabled on this installation"
        command = str(kwargs.get("command", "")).strip()
        if not command:
            return "no command given"
        return _run_shell(command, workspace)

    registry.register(
        Tool(
            name="files_list",
            description="List files and folders in the workspace.",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "relative path"}},
            },
            handler=files_list,
            category="files",
        )
    )
    registry.register(
        Tool(
            name="files_read",
            description="Read a text file from the workspace.",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "relative path"}},
                "required": ["path"],
            },
            handler=files_read,
            category="files",
        )
    )
    registry.register(
        Tool(
            name="files_write",
            description="Write text into a workspace file, creating folders as needed.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "relative path"},
                    "content": {"type": "string", "description": "full file content"},
                },
                "required": ["path", "content"],
            },
            handler=files_write,
            category="files",
        )
    )
    registry.register(
        Tool(
            name="run_command",
            description="Run a shell command inside the workspace.",
            schema={
                "type": "object",
                "properties": {"command": {"type": "string", "description": "shell command"}},
                "required": ["command"],
            },
            handler=run_command,
            category="system",
            requires="operator opt-in",
        )
    )


def _run_shell(command: str, workspace: Path) -> str:
    """Run a command with the workspace as cwd.

    On Windows the command goes through cmd.exe, elsewhere through sh, so the
    same tool works on both platforms (constraint 18).
    """
    try:
        if platform.system() == "Windows":
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
                encoding="utf-8",
                errors="replace",
            )
        else:
            completed = subprocess.run(
                shlex.split(command),
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )
    except subprocess.TimeoutExpired:
        return f"command timed out after {COMMAND_TIMEOUT}s"
    except OSError as exc:
        return f"command failed to start: {exc}"

    parts = []
    if completed.stdout:
        parts.append(completed.stdout.strip())
    if completed.stderr:
        parts.append(f"[stderr]\n{completed.stderr.strip()}")
    parts.append(f"[exit {completed.returncode}]")
    return "\n".join(parts)[:MAX_READ_BYTES]


async def register_browser_tools(registry: ToolRegistry, profile: str = "default") -> bool:
    """Register the Browser Use tool if the package is installed.

    Browser Use drives a real Chrome. Concurrent use of the same profile
    breaks sessions and can trip a site's abuse detection, so calls on one
    profile are serialised through the registry lock (constraint 12).

    Returns True when the tool was registered.
    """
    try:
        from browser_use import Agent as BrowserAgent  # noqa: F401
    except ImportError:
        return False

    state: dict[str, object] = {"agent": None, "profile": profile}

    async def browser_run(**kwargs: object) -> dict:
        """Run a browser task. Serialised per profile by the registry lock."""
        task = str(kwargs.get("task", "")).strip()
        if not task:
            return {"ok": False, "error": "no task given"}

        try:
            from browser_use import Agent, Browser, BrowserConfig  # noqa: F401
        except ImportError as exc:
            return {"ok": False, "error": f"browser_use is not installed: {exc}"}

        llm = kwargs.get("llm")
        if llm is None:
            return {
                "ok": False,
                "error": "browser_run needs an llm instance; the office supplies it per role",
            }

        agent = BrowserAgent(task=task, llm=llm)
        history = await agent.run()
        return {
            "ok": True,
            "result": getattr(history, "final_result", lambda: "")() or str(history),
        }

    registry.register(
        Tool(
            name="browser_run",
            description=(
                "Open a real browser and complete a web task (search, fill forms, "
                "click, extract text). Serialised per browser profile."
            ),
            schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "what to do in the browser"}
                },
                "required": ["task"],
            },
            handler=browser_run,
            category="browser",
            requires="pip install browser-use",
            metadata={"profile": profile},
        )
    )
    return True


async def register_tarsier_tools(registry: ToolRegistry) -> bool:
    """Register the Tarsier desktop tool if the package is installed.

    Tarsier must run in an isolated desktop session (constraint 11); the
    check here is only about availability, isolation is the operator's job.
    """
    try:
        import tarsier  # noqa: F401
    except ImportError:
        return False

    async def desktop_tree(**kwargs: object) -> str:
        """Read the accessibility tree of the focused window as YAML."""
        try:
            from tarsier import Tarsier  # type: ignore
        except ImportError as exc:
            return f"tarsier is not installed: {exc}"
        try:
            snapshot = Tarsier().get_accessibility_tree()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            return f"tarsier failed: {type(exc).__name__}: {exc}"
        return str(snapshot)[:MAX_READ_BYTES]

    registry.register(
        Tool(
            name="desktop_tree",
            description=(
                "Read the semantic accessibility tree of the focused desktop "
                "window. Requires an isolated desktop session."
            ),
            schema={"type": "object", "properties": {}},
            handler=desktop_tree,
            category="desktop",
            requires="pip install tarsier-ai, isolated desktop session",
        )
    )
    return True
