"""MCP: an agent can use tools that live outside this process.

A server is a command plus its arguments. The client speaks JSON-RPC over the
child's stdio, which is how MCP's stdio transport works, so any MCP server
from the community can be plugged in without an adapter.

Nothing here is required for the office to run: servers are configured
per install, and a failure to connect only marks that server unavailable.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

# The protocol revision this client speaks.
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30.0


class McpError(RuntimeError):
    """A server could not be reached or answered something unusable."""


@dataclass
class McpServer:
    """How to start and reach one MCP server."""

    id: str
    name: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    endpoint: str = ""
    connected: bool = False
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "endpoint": self.endpoint,
            "connected": self.connected,
            "error": self.error,
        }


class McpClient:
    """One connection to one MCP server over stdio."""

    def __init__(self, server: McpServer, working_dir: Path | None = None) -> None:
        self.server = server
        self.working_dir = working_dir
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def connect(self) -> list[dict]:
        """Start the process and run the MCP handshake."""
        if not self.server.command:
            raise McpError(f"{self.server.id}: no command configured")
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (self.server.env or {}).items()})
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.server.command,
                *self.server.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                cwd=str(self.working_dir) if self.working_dir else None,
            )
        except (OSError, FileNotFoundError) as exc:
            raise McpError(f"{self.server.id}: cannot start: {exc}") from exc

        reply = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "botoffice", "version": "0.1.0"},
            },
        )
        if reply.get("error"):
            raise McpError(f"{self.server.id}: {reply['error']}")
        await self.notify("notifications/initialized")
        return (await self.list_tools())["tools"]

    async def list_tools(self) -> dict:
        reply = await self.request("tools/list", {})
        if reply.get("error"):
            raise McpError(f"{self.server.id}: {reply['error']}")
        return reply.get("result") or {"tools": []}

    async def call_tool(self, name: str, arguments: dict) -> dict:
        reply = await self.request("tools/call", {"name": name, "arguments": arguments})
        if reply.get("error"):
            raise McpError(f"{self.server.id}: {reply['error']}")
        result = reply.get("result") or {}
        # MCP returns either a text result or a content list; normalise both.
        if "content" in result:
            parts = [
                part.get("text", "")
                for part in result.get("content", [])
                if isinstance(part, dict)
            ]
            text = "".join(parts)
            if result.get("isError"):
                return {"ok": False, "error": text or "tool reported an error"}
            return {"ok": True, "result": text}
        return result

    async def notify(self, method: str) -> None:
        await self._write({"jsonrpc": "2.0", "method": method})

    async def request(self, method: str, params: dict) -> dict:
        if self._proc is None:
            raise McpError(f"{self.server.id}: not connected")
        async with self._lock:
            request_id = self._next_id
            self._next_id += 1
            await self._write(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            return await self._read_reply(request_id)

    async def _write(self, payload: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpError(f"{self.server.id}: not running")
        try:
            self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise McpError(f"{self.server.id}: pipe closed") from exc

    async def _read_reply(self, request_id: int) -> dict:
        if self._proc is None or self._proc.stdout is None:
            raise McpError(f"{self.server.id}: not running")
        deadline = asyncio.get_event_loop().time() + DEFAULT_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise McpError(f"{self.server.id}: timed out waiting for {request_id}")
            try:
                line = await asyncio.wait_for(self._proc.stdout.readline(), remaining)
            except asyncio.TimeoutError as exc:
                raise McpError(f"{self.server.id}: timed out waiting for {request_id}") from exc
            if not line:
                raise McpError(f"{self.server.id}: server closed its output")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue  # a notification, not our reply
            return message

    async def close(self) -> None:
        proc = self._proc
        self._proc = None
        self.server.connected = False
        self.server.error = ""
        if proc is None:
            return
        # Close the handle cleanly: tearing the transport down before the
        # interpreter collects it avoids a Windows pipe-access traceback.
        try:
            if proc.stdin:
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
            pass
        try:
            if proc.returncode is None:
                proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError, OSError):
            pass


class McpRegistry:
    """Servers on disk, plus the ones currently running."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._servers: dict[str, McpServer] = {}
        self._clients: dict[str, McpClient] = {}
        self._tools: dict[str, list[dict]] = {}

    # --------------------------------------------------------------- store

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        with self._lock:
            self._servers.clear()
            for item in raw.get("servers", []):
                server = McpServer(**item)
                self._servers[server.id] = server

    def save(self) -> None:
        with self._lock:
            payload = {
                "servers": [
                    {
                        "id": server.id,
                        "name": server.name,
                        "transport": server.transport,
                        "command": server.command,
                        "args": list(server.args),
                        "env": server.env,
                        "endpoint": server.endpoint,
                    }
                    for server in self._servers.values()
                ]
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def add(self, server: McpServer) -> McpServer:
        with self._lock:
            self._servers[server.id] = server
            self.save()
        return server

    def remove(self, server_id: str) -> bool:
        with self._lock:
            existed = self._servers.pop(server_id, None) is not None
        # The connection itself is async; it is closed when the app shuts
        # down (see aclose_all) rather than blocking this call.
        self._clients.pop(server_id, None)
        self._tools.pop(server_id, None)
        if existed:
            self.save()
        return existed

    async def aclose_all(self) -> None:
        """Close every running server, called on shutdown."""
        for client in list(self._clients.values()):
            try:
                await client.close()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
        self._clients.clear()

    def list(self) -> list[dict]:
        with self._lock:
            servers = [
                server.as_dict() | {"tools": self._tools.get(server.id, [])}
                for server in self._servers.values()
            ]
        return servers

    def get(self, server_id: str) -> McpServer:
        with self._lock:
            server = self._servers.get(server_id)
        if server is None:
            raise KeyError(f"unknown MCP server {server_id!r}")
        return server

    # ------------------------------------------------------------ connect

    def tools_for(self, server_id: str) -> list[dict]:
        with self._lock:
            return list(self._tools.get(server_id, []))

    async def connect(self, server_id: str, working_dir: Path | None = None) -> list[dict]:
        """Start a server and read the tools it offers."""
        server = self.get(server_id)
        await self.disconnect(server_id)
        client = McpClient(server, working_dir=working_dir)
        try:
            tools = await client.connect()
        except McpError as exc:
            server.connected = False
            server.error = str(exc)
            raise
        server.connected = True
        server.error = ""
        self._clients[server_id] = client
        self._tools[server_id] = [
            {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "schema": tool.get("inputSchema", {}),
            }
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        ]
        return self._tools[server_id]

    async def disconnect(self, server_id: str) -> None:
        client = self._clients.pop(server_id, None)
        if client is not None:
            await client.close()

    def call(self, server_id: str, tool_name: str, arguments: dict):
        """Callable for the office tool registry: always returns a result dict."""
        client = self._clients.get(server_id)
        if client is None:
            return {"ok": False, "error": f"MCP server {server_id!r} is not connected"}
        return client.call_tool(tool_name, arguments)

    def connected_clients(self) -> dict[str, McpClient]:
        with self._lock:
            return dict(self._clients)
