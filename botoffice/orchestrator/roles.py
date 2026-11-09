"""Role definitions.

A role is data, not code (constraint 13 in CLAUDE.md). It declares:

    who the agent is        -> name, responsibilities, department
    what it may remember   -> memory_read / memory_write scopes
    which tools it uses    -> scope.tools, a subset of the global tool registry
    which model it uses    -> llm.primary / llm.fallback / budget_tokens

The tool *implementations* are shared by everyone. Adding a role must never
require editing a Python or JavaScript file.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..llm.router import ModelBinding

KIND_BUILTIN = "builtin"
KIND_EXTERNAL = "external"
KIND_USER = "user"

# Rank decides who may do what (docs/rules.md section 5). The code enforces
# these; a model can never grant itself a permission by asking for it.
RANKS = ("owner", "lead", "manager", "member")

RANK_PERMISSIONS: dict[str, set[str]] = {
    "owner": {"assign", "hire", "fire", "review", "call_meeting", "library_write", "spawn_subagent"},
    "lead": {"assign", "hire", "fire", "review", "call_meeting", "library_write", "spawn_subagent"},
    "manager": {"assign", "review", "call_meeting", "library_write"},
    "member": set(),
}


def _atomic_write(path: Path, content: str) -> None:
    """Write a file atomically so a crash cannot leave it half written."""
    import os
    import tempfile

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


@dataclass
class RoleScope:
    """What a role is allowed to touch."""

    memory_read: list[str] = field(default_factory=lambda: ["global"])
    memory_write: list[str] = field(default_factory=lambda: ["global"])
    tools: list[str] = field(default_factory=list)  # empty means "all registered tools"

    def can_read(self, scope: str) -> bool:
        return scope in self.memory_read

    def can_write(self, scope: str) -> bool:
        return scope in self.memory_write

    def tool_allowed(self, tool_name: str) -> bool:
        """An empty tool list means every tool is available."""
        if not self.tools:
            return True
        return tool_name in self.tools


@dataclass
class Role:
    """One employee in the office."""

    id: str
    name: str
    role: str = ""
    kind: str = KIND_BUILTIN
    department: str = "general"
    team: str = "general"
    leader: bool = False
    rank: str = ""
    responsibilities: str = ""
    scope: RoleScope = field(default_factory=RoleScope)
    llm: ModelBinding = field(default_factory=ModelBinding)
    desk: list[float] = field(default_factory=lambda: [0.0, 0.0])
    avatar: str = ""
    hidden: bool = False
    external: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in (KIND_BUILTIN, KIND_EXTERNAL, KIND_USER):
            raise ValueError(f"role {self.id}: unknown kind {self.kind!r}")
        if isinstance(self.scope, dict):
            self.scope = RoleScope(**self.scope)
        if isinstance(self.llm, dict):
            self.llm = ModelBinding(**self.llm)
        self.desk = [float(x) for x in (self.desk or [0.0, 0.0])]
        # Keep the legacy leader flag and the newer rank field in sync, so
        # existing data files keep working without a migration.
        if not self.rank:
            self.rank = "lead" if self.leader else "member"
        if self.rank not in RANKS:
            raise ValueError(f"role {self.id}: unknown rank {self.rank!r}")
        self.leader = self.rank == "lead"

    def can(self, action: str) -> bool:
        """Whether this employee may perform an office action."""
        return action in RANK_PERMISSIONS.get(self.rank, set())

    def as_dict(self) -> dict:
        return asdict(self)


class RoleRegistry:
    """Loads and stores role definitions from a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._roles: dict[str, Role] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        with self._lock:
            self._roles.clear()
            for item in raw.get("roles", []):
                role = Role(**item)
                self._roles[role.id] = role

    def save(self) -> None:
        """Persist every role.

        The file is rewritten in full, so two processes editing the same file
        would overwrite each other. That is acceptable here because one
        desktop app owns one file; a file lock keeps concurrent writes from
        interleaving.
        """
        with self._lock:
            payload = {"roles": [role.as_dict() for role in self._roles.values()]}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    def add(self, role: Role) -> Role:
        with self._lock:
            self._roles[role.id] = role
        self.save()
        return role

    def remove(self, role_id: str) -> bool:
        with self._lock:
            existed = self._roles.pop(role_id, None) is not None
        if existed:
            self.save()
        return existed

    def get(self, role_id: str) -> Role:
        with self._lock:
            role = self._roles.get(role_id)
        if role is None:
            raise KeyError(f"unknown role {role_id!r}; known: {sorted(self._roles)}")
        return role

    def list(self) -> list[Role]:
        with self._lock:
            return list(self._roles.values())

    def leaders(self) -> list[Role]:
        return [r for r in self.list() if r.leader]

    def by_department(self, department: str) -> list[Role]:
        return [r for r in self.list() if r.department == department]
