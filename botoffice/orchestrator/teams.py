"""Teams and the working directory each one operates in.

A team is more than a label: it owns an office and a project folder. The
file tools resolve paths inside that folder, so two teams can work on two
different projects without seeing each other's files.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path


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


@dataclass
class Team:
    """One team: a name and the folder its agents work in."""

    id: str
    name: str = ""
    workspace: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "workspace": self.workspace}


class TeamRegistry:
    """Loads and stores teams from config/teams.json."""

    def __init__(self, path: Path, default_workspace: Path) -> None:
        self.path = Path(path)
        self.default_workspace = str(Path(default_workspace).resolve())
        self._lock = threading.RLock()
        self._teams: dict[str, Team] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        with self._lock:
            self._teams.clear()
            for item in raw.get("teams", []):
                team = Team(**item)
                if not team.name:
                    team.name = team.id
                if not team.workspace:
                    team.workspace = self.default_workspace
                self._teams[team.id] = team

    def save(self) -> None:
        with self._lock:
            payload = {"teams": [team.as_dict() for team in self._teams.values()]}
            _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2))

    def get(self, team_id: str | None) -> Team:
        """Return a team, creating it with the default workspace if unknown."""
        key = (team_id or "general").strip() or "general"
        with self._lock:
            team = self._teams.get(key)
            if team is None:
                team = Team(id=key, name=key, workspace=self.default_workspace)
                self._teams[key] = team
                self.save()
            return team

    def list(self) -> list[Team]:
        with self._lock:
            return list(self._teams.values())

    def set_workspace(self, team_id: str, workspace: str) -> Team:
        team = self.get(team_id)
        team.workspace = str(Path(workspace).expanduser())
        self.save()
        return team

    def ensure(self, team_id: str) -> Team:
        return self.get(team_id)
