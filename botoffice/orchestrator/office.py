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

# Landmark anchors. The scene places its meshes on these points.
LEADER_OFFICE_DOOR = (8.0, 6.0)
MEETING_ROOM_CENTER = (-5.0, 6.0)
MEETING_ROOM_RADIUS = 2.6

# The owner (the human using the app) stands inside the leader office.
BOSS_ID = "me"
BOSS_SPOT = (8.0, 4.2)

WALK_SPEED = 6.0
MAX_WALK_SECONDS = 1.5

# Desk spacing in world units. Desks form a single line along the x axis:
# in an isometric view that direction maps to a screen diagonal where the
# spacing stays wide enough for the figures not to overlap. A row-per-line
# layout would put them 30 px apart, which is narrower than a figure.
STEP_X = 3.5
STEP_Z = 3.0

# The first desk position.
FIRST_DESK_X = -6.0
FIRST_DESK_Z = -3.6
DESKS_PER_ROW = 6


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
    """World position of the nth desk. Rows grow as needed, so the count is
    unlimited."""
    row = index // DESKS_PER_ROW
    column = index % DESKS_PER_ROW
    return [
        round(FIRST_DESK_X + column * STEP_X, 2),
        round(FIRST_DESK_Z + row * STEP_Z, 2),
    ]


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
        """The floor rectangle, sized to hold every desk plus the landmarks.

        The GUI draws the room from these numbers, so a bigger office simply
        means a bigger floor. The leader office and the meeting room are
        included, otherwise furniture would sit outside the floor.
        """
        xs = [pos[0] for pos in self._desks.values()]
        zs = [pos[1] for pos in self._desks.values()]
        # Meeting room rug.
        xs += [MEETING_ROOM_CENTER[0] - 3.0, MEETING_ROOM_CENTER[0] + 3.0]
        zs += [MEETING_ROOM_CENTER[1] - 2.0, MEETING_ROOM_CENTER[1] + 2.0]
        # Leader office box (1.5 units each side of the door, 4 deep).
        xs += [LEADER_OFFICE_DOOR[0] - 1.5, LEADER_OFFICE_DOOR[0] + 1.5]
        zs += [LEADER_OFFICE_DOOR[1] - 3.0, LEADER_OFFICE_DOOR[1] + 1.0]
        return {
            "min_x": round(min(xs) - 2.6, 2),
            "max_x": round(max(xs) + 2.6, 2),
            "min_z": round(min(zs) - 2.6, 2),
            "max_z": round(max(zs) + 2.6, 2),
        }

    def landmarks(self) -> dict:
        """Anchor points the scene needs."""
        return {
            "leader_office_door": list(LEADER_OFFICE_DOOR),
            "meeting_room_center": list(MEETING_ROOM_CENTER),
            "meeting_room_radius": MEETING_ROOM_RADIUS,
            "desks": self.all_desks(),
            "bounds": self.room_bounds(),
        }
