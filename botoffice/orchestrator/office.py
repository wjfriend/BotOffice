"""Office layout: desks, meeting room, leader office, and pathing.

Coordinates are ground-plane ``[x, z]`` with ``y`` always 0. The GUI uses
the same numbers, so a desk declared here lands in the same place in the
rendered office.

The office starts empty. Desks are handed out as roles are added and the
room grows with them, so there is no cap on how many characters the user
can create.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .roles import Role

# Fixed floor plan, in world units. The room never resizes: teams only get
# more desks, which fill the work area row by row.
#
#     meeting room (glass wall)
#     --------------------------
#     work area: two rows of desks        pantry (right)
#     --------------------------
#     boss office | entrance | lounge
ROOM = {"min_x": -14.0, "max_x": 14.0, "min_z": -12.0, "max_z": 12.0}

# Each zone: x/z is the near corner, w/d are the extents, color is the floor.
ZONES = {
    "meeting": {"x": -13.0, "z": -11.4, "w": 12.0, "d": 6.0, "color": "#c9772f"},
    "work": {"x": -7.0, "z": -4.0, "w": 16.0, "d": 9.0, "color": "#3f7f6f"},
    "boss": {"x": -13.2, "z": 6.0, "w": 5.0, "d": 5.2, "color": "#8a4a4a"},
    "lounge": {"x": 8.0, "z": -10.0, "w": 5.4, "d": 6.0, "color": "#8a6a52"},
    "pantry": {"x": 8.0, "z": 4.6, "w": 5.4, "d": 6.0, "color": "#d9d3c6"},
}

MEETING_ROOM_CENTER = (-7.0, -8.4)
MEETING_ROOM_RADIUS = 2.6

# The owner (the human using the app) sits in the boss office.
BOSS_ID = "me"
BOSS_SPOT = (-10.7, 8.6)

# Where people come in.
ENTRANCE = (0.0, 11.4)

WALK_SPEED = 6.0
MAX_WALK_SECONDS = 1.5

# Desks: two rows inside the work zone. A third row is pushed further back
# so the office can still hold a large team.
STEP_X = 3.4
ROW_Z = (-3.2, 0.2, 3.6)
FIRST_DESK_X = -5.4
DESKS_PER_ROW = 5


@dataclass(frozen=True)
class Point:
    x: float
    z: float

    def as_list(self) -> list[float]:
        return [self.x, self.z]

    def distance_to(self, other: "Point") -> float:
        return math.hypot(other.x - self.x, other.z - self.z)


def meeting_seat(index: int) -> Point:
    """Seat position around the meeting table, assigned in arrival order."""
    offsets = [
        (2.0, 0.0),
        (0.0, 2.0),
        (-2.0, 0.0),
        (0.0, -2.0),
        (2.0, 2.0),
        (-2.0, -2.0),
    ]
    dx, dz = offsets[index % len(offsets)]
    return Point(MEETING_ROOM_CENTER[0] + dx, MEETING_ROOM_CENTER[1] + dz)


def walk_seconds(origin: Point, target: Point) -> float:
    """How long the walk takes, used by both the backend and the animation."""
    return max(0.0, min(MAX_WALK_SECONDS, origin.distance_to(target) / WALK_SPEED))


def desk_position(index: int) -> list[float]:
    """World position of the nth desk.

    Two rows fill the work area; later rows continue further back so a large
    team still fits.
    """
    row = index // DESKS_PER_ROW
    column = index % DESKS_PER_ROW
    if row < len(ROW_Z):
        z = ROW_Z[row]
    else:
        z = ROW_Z[-1] + (row - len(ROW_Z) + 1) * 4.0
    return [round(FIRST_DESK_X + column * STEP_X, 2), round(z, 2)]


class Office:
    """Tracks which role sits where and where the landmarks are."""

    def __init__(self) -> None:
        self._desks: dict[str, list[float]] = {}
        self._order: list[str] = []

    def assign_desk(self, role: Role) -> list[float]:
        """Return the role's desk, assigning a free one on first use.

        The owner is not an employee: they stand in the leader office and do
        not consume a numbered desk.
        """
        if role.id in self._desks:
            return list(self._desks[role.id])
        if getattr(role, "kind", "") == "user":
            desk = list(BOSS_SPOT)
        else:
            used = sum(1 for role_id in self._order if role_id != BOSS_ID)
            desk = desk_position(used)
        self._desks[role.id] = desk
        self._order.append(role.id)
        return list(desk)

    def release_desk(self, role_id: str) -> None:
        """Free a desk. The next character added reuses that slot."""
        if role_id in self._desks:
            del self._desks[role_id]
        if role_id in self._order:
            self._order.remove(role_id)

    def desk_of(self, role_id: str) -> Point:
        desk = self._desks.get(role_id) or [0.0, 0.0]
        return Point(float(desk[0]), float(desk[1]))

    def set_desk(self, role_id: str, desk: list[float]) -> None:
        if role_id not in self._order:
            self._order.append(role_id)
        self._desks[role_id] = [float(desk[0]), float(desk[1])]

    def all_desks(self) -> dict[str, list[float]]:
        return {k: list(v) for k, v in self._desks.items()}

    def room_bounds(self) -> dict:
        """The fixed floor rectangle. The plan does not grow with the team."""
        return dict(ROOM)

    def landmarks(self) -> dict:
        """Anchor points and zones the scene draws."""
        return {
            "boss_office": list(BOSS_SPOT),
            "leader_office_door": list(BOSS_SPOT),
            "meeting_room_center": list(MEETING_ROOM_CENTER),
            "meeting_room_radius": MEETING_ROOM_RADIUS,
            "entrance": list(ENTRANCE),
            "zones": {key: dict(zone) for key, zone in ZONES.items()},
            "desks": self.all_desks(),
            "bounds": self.room_bounds(),
        }


class OfficeManager:
    """One office per team.

    Teams are independent: each has its own desks and its own scene, so
    switching team in the GUI switches the whole room.
    """

    def __init__(self) -> None:
        self._offices: dict[str, Office] = {}

    def office_for(self, team: str | None) -> Office:
        key = (team or "general").strip() or "general"
        if key not in self._offices:
            self._offices[key] = Office()
        return self._offices[key]

    def teams(self) -> list[str]:
        return sorted(self._offices)
