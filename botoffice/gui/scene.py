"""Isometric (2.5D) office scene.

Drawn with QPainter on a plain widget: a real native window, not a browser
view, and the same code runs on Windows and Linux.

Projection: world coordinates are ground-plane (x, z). The camera is
isometric, so screen position is:

    sx = (x - z) * TILE_W / 2
    sy = (x + z) * TILE_H / 2 - height

Agents move by interpolating between two ground points. Depth sorting is by
(x + z) so figures overlap correctly.

Look and feel: a clean, toy-like isometric office. Warm wooden floor,
floor-to-ceiling windows onto a skyline, and a coloured rug under every
desk. Every surface is opaque; only shadows use transparency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from .assets import SpriteSet
from PySide6.QtGui import (
    QBrush,
    QTransform,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

# Isometric tile size. The scene scales these down when the room grows so
# that every desk stays visible without scrolling.
BASE_TILE_W = 46.0
BASE_TILE_H = 30.0
# How far the floor shifts sideways with depth. This is what makes the room
# read as an angled 3/4 view instead of a flat top-down plan.
OBLIQUE_SHEAR = 0.0
# The whole floor plane is rotated counter-clockwise a little, while the
# furniture sprites stay upright.
ROOM_ROTATION = math.radians(0.0)
WALK_FRAMES = 5

# Wall height in screen pixels (not scaled: it reads as a fixed ceiling).
WALL_H = 118.0

# --- palette -------------------------------------------------------------
# Warm wooden floor.
FLOOR_A = QColor("#c9a26b")
FLOOR_B = QColor("#bd9560")
FLOOR_SEAM = QColor("#a17a48")
FLOOR_EDGE = QColor("#8a663a")

# Walls and windows.
WALL = QColor("#ece8df")
WALL_LOWER = QColor("#ddd7cb")
WALL_EDGE = QColor("#b5aea1")
SKY_TOP = QColor("#7fb6e8")
SKY_BOTTOM = QColor("#d6ebfa")
CLOUD = QColor(255, 255, 255, 215)
CITY = QColor("#7d9cbb")
CITY_DARK = QColor("#66809b")
CITY_LIGHT = QColor("#ffe9a8")

# Furniture.
DESK_TOP = QColor("#a4713f")
DESK_SIDE = QColor("#845a31")
DESK_LEG = QColor("#5e3f22")
CHAIR = QColor("#3d4859")
CHAIR_DARK = QColor("#2c3542")
SOFA = QColor("#3f6b73")
SOFA_DARK = QColor("#31555c")
TABLE = QColor("#a97c4e")
SHELF = QColor("#7a5230")
COUNTER = QColor("#e6e0d3")
COUNTER_SIDE = QColor("#c6bfae")
FRIDGE = QColor("#eef2f5")
FRIDGE_SIDE = QColor("#cbd3da")
MONITOR = QColor("#39414f")
MONITOR_SCREEN = QColor("#7fd4c1")
GLASS_OFFICE = QColor("#bcd8e8")

# Characters.
SKIN = QColor("#f6d2b0")
SHIRT_COLORS = [
    QColor("#e8756a"), QColor("#5b8fd6"), QColor("#68b48b"),
    QColor("#d9a441"), QColor("#9b6bd1"), QColor("#4fb3bf"),
]
HAIR_COLORS = [
    QColor("#3b2f2a"), QColor("#5a4033"), QColor("#2f2a3a"),
    QColor("#6b4a2f"), QColor("#4a3a5a"), QColor("#2a3a3f"),
]
# Varied skin tones and trousers, so people read as individuals.
SKIN_TONES = [
    QColor("#f6d2b0"), QColor("#e8b98f"), QColor("#c98d63"),
    QColor("#9a6a45"), QColor("#f2c7a5"), QColor("#d9a273"),
]
PANTS_COLORS = [
    QColor("#3c4252"), QColor("#4a3b2f"), QColor("#2f3b4a"),
    QColor("#5a4a3a"), QColor("#33415c"), QColor("#3a3a3a"),
]
BLUSH = QColor(240, 140, 150, 110)

# Vivid rug colours, one per employee, so each workstation reads at a glance
# the way it does in a real office layout.
RUG_COLORS = [
    QColor("#7b4fd6"),
    QColor("#2f9e6e"),
    QColor("#2f6fd6"),
    QColor("#d08430"),
    QColor("#a03fb0"),
    QColor("#2fa3b5"),
]

# Outfit colours by agent runtime, so you can tell a Claude Code worker from a
# Codex worker at a glance.
OUTFIT_COLORS = {
    "claude-code": QColor("#d97757"),
    "codex": QColor("#ececec"),
    "opencode": QColor("#26262c"),
    "gemini-cli": QColor("#4285f4"),
}

# The user is a character too: a dark suit, distinct from every agent.
OWNER_SUIT = QColor("#2b3550")
OWNER_TIE = QColor("#d9a441")

# One colour per visible state, so the office reads at a glance.
STATE_COLORS = {
    "idle": QColor("#6fcf97"),
    "working": QColor("#ffb45e"),
    "waiting": QColor("#f2cd37"),
    "walking": QColor("#5b8fd6"),
    "interacting": QColor("#9b6bd1"),
    "meeting": QColor("#4fb3bf"),
    "returning": QColor("#5b8fd6"),
    "offline": QColor("#7b8395"),
}

# Appearance presets a user picks in the "new conversation" dialog. The value
# maps onto SHIRT_COLORS, so choosing a colour in the UI changes the avatar.
AVATAR_COLOR_INDEX = {
    "red": 0,
    "blue": 1,
    "green": 2,
    "amber": 3,
    "purple": 4,
    "teal": 5,
}


@dataclass
class Avatar:
    """One character standing in the office."""

    id: str
    name: str
    x: float = 0.0
    z: float = 0.0
    target_x: float = 0.0
    target_z: float = 0.0
    color_index: int = 0
    state: str = "idle"
    kind: str = "builtin"
    runtime: str = ""
    tag: str = ""
    rank: str = "member"
    walking: bool = False
    bubble: str = ""
    bubble_until: float = 0.0
    facing: int = 1
    bob: float = 0.0
    selected: bool = False

    @property
    def desk(self) -> tuple[float, float]:
        return (self.x, self.z)

    def move_to(self, x: float, z: float) -> None:
        self.target_x = x
        self.target_z = z
        self.walking = True

    def advance(self, dt: float, speed: float = 3.2) -> None:
        """Move toward the target point. Returns True when it arrived."""
        dx = self.target_x - self.x
        dz = self.target_z - self.z
        distance = math.hypot(dx, dz)
        if distance < 0.04:
            self.x, self.z = self.target_x, self.target_z
            self.walking = False
            self.bob = 0.0
            return True
        step = min(distance, speed * dt)
        self.x += dx / distance * step
        self.z += dz / distance * step
        self.bob += dt * 9.0
        if abs(dx) > 0.001:
            self.facing = 1 if dx > 0 else -1
        return False


@dataclass
class Furniture:
    """A desk, plant or table drawn in the scene."""

    kind: str
    x: float
    z: float
    width: float = 1.0
    depth: float = 1.0
    owner: str = ""
    extra: dict = field(default_factory=dict)


class OfficeScene:
    """Holds the world state and draws it."""

    def __init__(self) -> None:
        self.avatars: dict[str, Avatar] = {}
        self.furniture: list[Furniture] = []
        self.meeting_center = (-5.0, 6.0)
        self.leader_door = (8.0, 6.0)
        self.bounds = {"min_x": -11.0, "max_x": 12.0, "min_z": -6.0, "max_z": 11.0}
        self.dragging: str | None = None
        self.drop_target: str | None = None
        self.hovered: str | None = None
        self.on_drop: callable | None = None
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._time = 0.0
        self._view_w = 0.0
        self._view_h = 0.0
        self.stats: dict = {"working": 0, "idle": 0, "cost": 0.0}
        self.zones: dict = {}
        self.desk_slots: list[list[float]] = []
        self.entrance = (0.0, 11.8)
        self.tile_w = BASE_TILE_W
        self.tile_h = BASE_TILE_H
        self.antialias = True
        self.sprites = SpriteSet()

    def set_stats(self, stats: dict) -> None:
        """Numbers shown on the digital board on the wall."""
        self.stats = dict(stats)

    # ------------------------------------------------------------- building

    def set_desks(self, desks: dict[str, list[float]]) -> None:
        """Rebuild desk furniture from the layout the backend reports."""
        self.furniture = [
            Furniture("desk", float(pos[0]), float(pos[1]), owner=role_id)
            for role_id, pos in desks.items()
        ]

    def set_landmarks(self, landmarks: dict) -> None:
        if "meeting_room_center" in landmarks:
            self.meeting_center = tuple(landmarks["meeting_room_center"])  # type: ignore[assignment]
        if "leader_office_door" in landmarks:
            self.leader_door = tuple(landmarks["leader_office_door"])  # type: ignore[assignment]
        if "bounds" in landmarks:
            self.bounds = dict(landmarks["bounds"])
        if "zones" in landmarks:
            self.zones = dict(landmarks["zones"])
        if "entrance" in landmarks:
            self.entrance = tuple(landmarks["entrance"])
        if "desk_slots" in landmarks:
            self.desk_slots = [list(pos) for pos in landmarks["desk_slots"]]

    def ensure_avatar(self, role_id: str, name: str, desk: list[float], color_index: int,
                      kind: str = "builtin", runtime: str = "", tag: str = "",
                      rank: str = "member") -> Avatar:
        avatar = self.avatars.get(role_id)
        if avatar is None:
            avatar = Avatar(
                id=role_id, name=name, x=float(desk[0]), z=float(desk[1]),
                target_x=float(desk[0]), target_z=float(desk[1]), color_index=color_index,
            )
            self.avatars[role_id] = avatar
        avatar.name = name
        avatar.kind = kind
        avatar.runtime = runtime
        avatar.tag = tag
        avatar.rank = rank
        return avatar

    def remove_avatar(self, role_id: str) -> None:
        self.avatars.pop(role_id, None)

    # ------------------------------------------------------------ projection

    @property
    def avatar_scale(self) -> float:
        """How much the characters grow with the room, kept readable."""
        return max(0.8, min(1.55, self.tile_w / BASE_TILE_W))

    def _project_plane(self, x: float, z: float, height: float = 0.0) -> tuple[float, float]:
        """World -> screen before the camera offset is applied.

        The floor is sheared so it reads as an angled 3/4 view, then the whole
        plane is rotated slightly. Sprites are drawn upright afterwards, so
        the furniture keeps its own drawn angle while the room tilts.
        """
        sx = (x + z * OBLIQUE_SHEAR) * self.tile_w
        sy = z * self.tile_h - height
        cos_a = math.cos(ROOM_ROTATION)
        sin_a = math.sin(ROOM_ROTATION)
        return (sx * cos_a - sy * sin_a, sx * sin_a + sy * cos_a)

    def to_screen(self, x: float, z: float, height: float = 0.0) -> QPointF:
        rx, ry = self._project_plane(x, z, height)
        return QPointF(rx + self._offset_x, ry + self._offset_y)

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        dx = sx - self._offset_x
        dy = sy - self._offset_y
        cos_a = math.cos(ROOM_ROTATION)
        sin_a = math.sin(ROOM_ROTATION)
        px = dx * cos_a + dy * sin_a
        py = -dx * sin_a + dy * cos_a
        z = py / self.tile_h
        x = px / self.tile_w - z * OBLIQUE_SHEAR
        return (x, z)

    def fit_room(self, width: int, height: int) -> None:
        """Scale the tiles so the whole room fits the viewport."""
        b = self.bounds
        corners = [
            (b["min_x"], b["min_z"]), (b["max_x"], b["min_z"]),
            (b["max_x"], b["max_z"]), (b["min_x"], b["max_z"]),
        ]
        points = [self._project_plane(x, z) for x, z in corners]
        span_w = max(p[0] for p in points) - min(p[0] for p in points)
        span_h = max(p[1] for p in points) - min(p[1] for p in points)
        ratio_w = self.tile_w / BASE_TILE_W
        ratio_h = self.tile_h / BASE_TILE_H
        base_w = max(1.0, span_w / ratio_w)
        base_h = max(1.0, span_h / ratio_h)
        scale_w = (width - 170) / base_w
        scale_h = (height - 270) / base_h
        scale = min(1.9, scale_w, scale_h)
        scale = max(scale, 0.42)
        self.tile_w = BASE_TILE_W * scale
        self.tile_h = BASE_TILE_H * scale

    def center_on(self, width: int, height: int) -> None:
        """Centre the view on the room's rotated bounding box."""
        self.fit_room(width, height)
        b = self.bounds
        corners = [
            (b["min_x"], b["min_z"]), (b["max_x"], b["min_z"]),
            (b["max_x"], b["max_z"]), (b["min_x"], b["max_z"]),
        ]
        points = [self._project_plane(x, z) for x, z in corners]
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        self._offset_x = width / 2 - (min_x + max_x) / 2
        self._offset_y = height / 2 - (min_y + max_y) / 2 + 30

    # -------------------------------------------------------------- drawing

    def draw(self, painter: QPainter, width: int, height: int, dt: float = 0.016) -> None:
        self._time += dt
        self._view_w = float(width)
        self._view_h = float(height)
        self.center_on(width, height)
        painter.setRenderHint(QPainter.Antialiasing, self.antialias)

        # Room ambience behind the office.
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0.0, QColor("#26304a"))
        gradient.setColorAt(1.0, QColor("#10141d"))
        painter.fillRect(QRectF(0, 0, width, height), QBrush(gradient))

        self._draw_room(painter)
        self._draw_furniture(painter)
        for avatar in self._sorted_avatars():
            self._draw_avatar(painter, avatar)

        # A warm wash on top softens every surface without hiding detail.
        ambient = QLinearGradient(0, 0, 0, height)
        ambient.setColorAt(0.0, QColor(255, 226, 190, 18))
        ambient.setColorAt(0.55, QColor(255, 255, 255, 0))
        ambient.setColorAt(1.0, QColor(24, 30, 44, 26))
        painter.fillRect(QRectF(0, 0, width, height), QBrush(ambient))

        self._draw_overlays(painter)

    def _sorted_avatars(self) -> list[Avatar]:
        return sorted(self.avatars.values(), key=lambda a: a.z)

    # ------------------------------------------------------------ geometry

    def _quad(self, x: float, z: float, w: float, d: float, height: float = 0.0) -> QPolygonF:
        """A flat rectangle on the ground (or lifted to `height`)."""
        return QPolygonF([
            self.to_screen(x, z, height),
            self.to_screen(x + w, z, height),
            self.to_screen(x + w, z + d, height),
            self.to_screen(x, z + d, height),
        ])

    def _wall_quad(self, wall: str, a: float, b: float, coord: float,
                   h1: float, h2: float) -> QPolygonF:
        """A rectangle lying on one of the two back walls."""
        if wall == "z":
            points = [
                self.to_screen(a, coord, h1), self.to_screen(b, coord, h1),
                self.to_screen(b, coord, h2), self.to_screen(a, coord, h2),
            ]
        else:
            points = [
                self.to_screen(coord, a, h1), self.to_screen(coord, b, h1),
                self.to_screen(coord, b, h2), self.to_screen(coord, a, h2),
            ]
        return QPolygonF(points)

    def _sprite(self, painter: QPainter, name: str, x: float, z: float,
                world_width: float, flip: bool = False,
                height: float = 0.0) -> bool:
        """Draw assets/<name>.png anchored on the floor.

        Returns False when the file is missing so the caller can fall back
        to the vector shape.
        """
        pixmap = self.sprites.get(name)
        if pixmap is None:
            return False
        if flip:
            pixmap = pixmap.transformed(QTransform().scale(1, -1))
        target_w = max(1.0, world_width * self.tile_w)
        scale = target_w / pixmap.width()
        target_h = pixmap.height() * scale
        base = self.to_screen(x, z, height)
        painter.drawPixmap(
            QRectF(base.x() - target_w / 2, base.y() - target_h, target_w, target_h),
            pixmap,
            QRectF(pixmap.rect()),
        )
        return True

    def _shadow(self, painter: QPainter, x: float, z: float, rx: float, ry: float) -> None:
        """A soft contact shadow: stacked ellipses fake a blur."""
        centre = self.to_screen(x, z, 1)
        painter.setPen(Qt.NoPen)
        for scale, alpha in ((1.20, 16), (1.08, 24), (1.00, 34)):
            painter.setBrush(QBrush(QColor(0, 0, 0, alpha)))
            painter.drawEllipse(
                QPointF(centre.x(), centre.y()),
                rx * self.tile_w * scale,
                ry * self.tile_h * scale,
            )

    def _box(self, painter: QPainter, x: float, z: float, w: float, d: float,
             height: float, fill: QColor, edge: QColor | None = None) -> None:
        """A solid box: opaque top and two visible side faces.

        The two faces that face the camera are shaded differently, which is
        what makes the object read as a solid block. Nothing here is
        translucent.
        """
        edge = edge or fill.darker(145)
        top = [
            self.to_screen(x, z, height), self.to_screen(x + w, z, height),
            self.to_screen(x + w, z + d, height), self.to_screen(x, z + d, height),
        ]
        base = [
            self.to_screen(x, z), self.to_screen(x + w, z),
            self.to_screen(x + w, z + d), self.to_screen(x, z + d),
        ]
        # Faces at x+w (facing right) and z+d (facing the viewer).
        for index, shade in ((1, fill.darker(118)), (2, fill.darker(138))):
            painter.setBrush(QBrush(shade))
            painter.setPen(QPen(edge, 1))
            painter.drawPolygon(QPolygonF([
                base[index], base[(index + 1) % 4], top[(index + 1) % 4], top[index],
            ]))
        top_poly = QPolygonF(top)
        bounds = top_poly.boundingRect()
        shade = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        shade.setColorAt(0.0, fill.lighter(112))
        shade.setColorAt(1.0, fill)
        painter.setBrush(QBrush(shade))
        painter.setPen(QPen(edge, 1))
        painter.drawPolygon(top_poly)

    # ---------------------------------------------------------------- room

    def _draw_room(self, painter: QPainter) -> None:
        """The fixed floor plan: zones, walls, windows and the entrance."""
        b = self.bounds
        x0, x1 = b["min_x"], b["max_x"]
        z0, z1 = b["min_z"], b["max_z"]

        self._draw_floor(painter, x0, x1, z0, z1)

        for zone in self.zones.values():
            self._zone(painter, zone["x"], zone["z"], zone["w"], zone["d"],
                       QColor(zone["color"]))

        self._draw_wall(painter, (x0, z0), (x1, z0))
        self._draw_wall(painter, (x0, z0), (x0, z1))
        self._draw_window_band(painter, "z", x0 + 1.0, x1 - 1.0, z0)
        self._draw_window_band(painter, "x", z0 + 1.0, z1 - 1.0, x0)
        self._draw_digital_board(painter, "x", z0 + 1.4, z0 + 4.2, x0)
        self._draw_clock(painter, "z", x1 - 3.0, z0)

        self._draw_desk_rugs(painter)

        meeting = self.zones.get("meeting")
        if meeting:
            self._draw_meeting_room(painter, meeting)
        boss = self.zones.get("boss")
        if boss:
            self._draw_office_room(painter, boss["x"], boss["z"], boss["w"], boss["d"])
        pantry = self.zones.get("pantry")
        if pantry:
            self._draw_kitchen(painter, pantry["x"] + 0.4, pantry["z"] + 0.6)
        lounge = self.zones.get("lounge")
        if lounge:
            self._draw_lounge(painter, lounge["x"] + 0.6, lounge["z"] + 0.8)

        self._draw_entrance(painter)

        # Decor: trees, plants and a framed picture on the wall.
        self._sprite(painter, "tree", x0 + 1.6, z0 + 8.0, 1.6)
        self._sprite(painter, "plant_palm", x1 - 2.2, z1 - 2.4, 1.4)
        self._sprite(painter, "plant_snake", x0 + 3.0, z1 - 1.6, 1.2)
        self._sprite(painter, "artwork", x0 + 5.0, z0 + 0.3, 1.8, height=62)

        for px, pz in (
            (x0 + 1.4, z0 + 1.4),
            (x1 - 1.6, z1 - 1.6),
            (x0 + 1.4, z1 - 1.6),
        ):
            self._draw_plant(painter, px, pz)

    def _draw_meeting_room(self, painter: QPainter, zone: dict) -> None:
        """A long table with five chairs down each side, behind glass walls."""
        x, z, w, d = zone["x"], zone["z"], zone["w"], zone["d"]
        self._glass_wall(painter, x, z + d, w, 0.0, "x")
        self._glass_wall(painter, x + w, z, 0.0, d, "z")

        table_x = x + 1.8
        table_z = z + d / 2 - 0.7
        table_w = w - 3.6
        table_d = 1.4

        # The back row is drawn first so the table hides it.
        for index in range(5):
            cx = table_x + (index + 0.5) * table_w / 5
            self._sprite(painter, "chair_meeting", cx, table_z - 0.45, 0.95)

        self._shadow(painter, table_x + table_w / 2, table_z + table_d / 2, 4.0, 1.6)
        self._box(painter, table_x, table_z, table_w, table_d, 20, TABLE, DESK_LEG)
        self._sprite(painter, "projector", table_x + table_w / 2, table_z + table_d / 2, 1.1)

        for index in range(5):
            cx = table_x + (index + 0.5) * table_w / 5
            self._sprite(painter, "chair_meeting", cx, table_z + table_d + 0.55, 0.95, flip=True)

        # A whiteboard at the far right of the room.
        self._sprite(painter, "whiteboard", x + w - 2.4, z + 0.9, 1.8)

    def _glass_wall(self, painter: QPainter, x: float, z: float, w: float, d: float,
                    axis: str) -> None:
        """A translucent glass panel, used only where glass is intended."""
        height = 54.0
        if axis == "x":
            a = self.to_screen(x, z)
            b = self.to_screen(x + w, z)
        else:
            a = self.to_screen(x, z)
            b = self.to_screen(x, z + d)
        painter.setBrush(QBrush(QColor(176, 216, 232, 70)))
        painter.setPen(QPen(QColor("#f4f7fa"), 2))
        painter.drawPolygon(QPolygonF([
            a, b, QPointF(b.x(), b.y() - height), QPointF(a.x(), a.y() - height),
        ]))

    def _draw_entrance(self, painter: QPainter) -> None:
        """A sliding glass door at the front, plus the glass front wall."""
        ex, ez = self.entrance
        b = self.bounds
        height = 74.0

        # Glass front wall on both sides of the opening.
        for start_x, end_x in ((b["min_x"], ex - 2.0), (ex + 2.0, b["max_x"])):
            a = self.to_screen(start_x, ez)
            c = self.to_screen(end_x, ez)
            painter.setBrush(QBrush(QColor(176, 216, 232, 60)))
            painter.setPen(QPen(QColor("#f4f7fa"), 2))
            painter.drawPolygon(QPolygonF([
                a, c, QPointF(c.x(), c.y() - height), QPointF(a.x(), a.y() - height),
            ]))

        # Two sliding panels, parted in the middle.
        for offset in (-1.9, 1.9):
            a = self.to_screen(ex + offset - 1.7, ez)
            c = self.to_screen(ex + offset + 1.7, ez)
            painter.setBrush(QBrush(QColor(196, 228, 240, 120)))
            painter.setPen(QPen(QColor("#cfd8de"), 2))
            painter.drawPolygon(QPolygonF([
                a, c, QPointF(c.x(), c.y() - height), QPointF(a.x(), a.y() - height),
            ]))
            # Handle.
            mid = self.to_screen(ex + offset, ez)
            painter.setBrush(QBrush(QColor("#8d949c")))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(mid.x() - 1.5, mid.y() - 40, 3, 14))

        # Mat on the floor.
        painter.setBrush(QBrush(QColor("#c9772f")))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(self._quad(ex - 2.0, ez - 1.8, 4.0, 1.6, 0.8))

    # ------------------------------------------------------------ geometry

    def _quad(self, x: float, z: float, w: float, d: float, height: float = 0.0) -> QPolygonF:
        """A flat rectangle on the ground (or lifted to `height`)."""
        return QPolygonF([
            self.to_screen(x, z, height),
            self.to_screen(x + w, z, height),
            self.to_screen(x + w, z + d, height),
            self.to_screen(x, z + d, height),
        ])

    def _wall_quad(self, wall: str, a: float, b: float, coord: float,
                   h1: float, h2: float) -> QPolygonF:
        """A rectangle lying on one of the two back walls."""
        if wall == "z":
            points = [
                self.to_screen(a, coord, h1), self.to_screen(b, coord, h1),
                self.to_screen(b, coord, h2), self.to_screen(a, coord, h2),
            ]
        else:
            points = [
                self.to_screen(coord, a, h1), self.to_screen(coord, b, h1),
                self.to_screen(coord, b, h2), self.to_screen(coord, a, h2),
            ]
        return QPolygonF(points)

    def _sprite(self, painter: QPainter, name: str, x: float, z: float,
                world_width: float, flip: bool = False,
                height: float = 0.0) -> bool:
        """Draw assets/<name>.png anchored on the floor.

        Returns False when the file is missing so the caller can fall back
        to the vector shape.
        """
        pixmap = self.sprites.get(name)
        if pixmap is None:
            return False
        if flip:
            pixmap = pixmap.transformed(QTransform().scale(1, -1))
        target_w = max(1.0, world_width * self.tile_w)
        scale = target_w / pixmap.width()
        target_h = pixmap.height() * scale
        base = self.to_screen(x, z, height)
        painter.drawPixmap(
            QRectF(base.x() - target_w / 2, base.y() - target_h, target_w, target_h),
            pixmap,
            QRectF(pixmap.rect()),
        )
        return True

    def _shadow(self, painter: QPainter, x: float, z: float, rx: float, ry: float) -> None:
        """A soft contact shadow: stacked ellipses fake a blur."""
        centre = self.to_screen(x, z, 1)
        painter.setPen(Qt.NoPen)
        for scale, alpha in ((1.20, 16), (1.08, 24), (1.00, 34)):
            painter.setBrush(QBrush(QColor(0, 0, 0, alpha)))
            painter.drawEllipse(
                QPointF(centre.x(), centre.y()),
                rx * self.tile_w * scale,
                ry * self.tile_h * scale,
            )

    def _box(self, painter: QPainter, x: float, z: float, w: float, d: float,
             height: float, fill: QColor, edge: QColor | None = None) -> None:
        """A solid box: opaque top and two visible side faces.

        The two faces that face the camera are shaded differently, which is
        what makes the object read as a solid block. Nothing here is
        translucent.
        """
        edge = edge or fill.darker(145)
        top = [
            self.to_screen(x, z, height), self.to_screen(x + w, z, height),
            self.to_screen(x + w, z + d, height), self.to_screen(x, z + d, height),
        ]
        base = [
            self.to_screen(x, z), self.to_screen(x + w, z),
            self.to_screen(x + w, z + d), self.to_screen(x, z + d),
        ]
        # Faces at x+w (facing right) and z+d (facing the viewer).
        for index, shade in ((1, fill.darker(118)), (2, fill.darker(138))):
            painter.setBrush(QBrush(shade))
            painter.setPen(QPen(edge, 1))
            painter.drawPolygon(QPolygonF([
                base[index], base[(index + 1) % 4], top[(index + 1) % 4], top[index],
            ]))
        top_poly = QPolygonF(top)
        bounds = top_poly.boundingRect()
        shade = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        shade.setColorAt(0.0, fill.lighter(112))
        shade.setColorAt(1.0, fill)
        painter.setBrush(QBrush(shade))
        painter.setPen(QPen(edge, 1))
        painter.drawPolygon(top_poly)

    # ---------------------------------------------------------------- room

    def _draw_room(self, painter: QPainter) -> None:
        """The fixed floor plan: zones, walls, windows and the entrance."""
        b = self.bounds
        x0, x1 = b["min_x"], b["max_x"]
        z0, z1 = b["min_z"], b["max_z"]

        self._draw_floor(painter, x0, x1, z0, z1)

        for zone in self.zones.values():
            self._zone(painter, zone["x"], zone["z"], zone["w"], zone["d"],
                       QColor(zone["color"]))

        self._draw_wall(painter, (x0, z0), (x1, z0))
        self._draw_wall(painter, (x0, z0), (x0, z1))
        self._draw_window_band(painter, "z", x0 + 1.0, x1 - 1.0, z0)
        self._draw_window_band(painter, "x", z0 + 1.0, z1 - 1.0, x0)
        self._draw_digital_board(painter, "x", z0 + 1.4, z0 + 4.2, x0)
        self._draw_clock(painter, "z", x1 - 3.0, z0)

        self._draw_desk_rugs(painter)

        meeting = self.zones.get("meeting")
        if meeting:
            self._draw_meeting_room(painter, meeting)
        boss = self.zones.get("boss")
        if boss:
            self._draw_office_room(painter, boss["x"], boss["z"], boss["w"], boss["d"])
        pantry = self.zones.get("pantry")
        if pantry:
            self._draw_kitchen(painter, pantry["x"] + 0.4, pantry["z"] + 0.6)
        lounge = self.zones.get("lounge")
        if lounge:
            self._draw_lounge(painter, lounge["x"] + 0.6, lounge["z"] + 0.8)

        self._draw_entrance(painter)

        # Decor: trees, plants and a framed picture on the wall.
        self._sprite(painter, "tree", x0 + 1.6, z0 + 8.0, 1.6)
        self._sprite(painter, "plant_palm", x1 - 2.2, z1 - 2.4, 1.4)
        self._sprite(painter, "plant_snake", x0 + 3.0, z1 - 1.6, 1.2)
        self._sprite(painter, "artwork", x0 + 5.0, z0 + 0.3, 1.8, height=62)

        for px, pz in (
            (x0 + 1.4, z0 + 1.4),
            (x1 - 1.6, z1 - 1.6),
            (x0 + 1.4, z1 - 1.6),
        ):
            self._draw_plant(painter, px, pz)

    def _draw_meeting_room(self, painter: QPainter, zone: dict) -> None:
        """A long table with five chairs down each side, behind glass walls."""
        x, z, w, d = zone["x"], zone["z"], zone["w"], zone["d"]
        self._glass_wall(painter, x, z + d, w, 0.0, "x")
        self._glass_wall(painter, x + w, z, 0.0, d, "z")

        table_x = x + 1.8
        table_z = z + d / 2 - 0.7
        table_w = w - 3.6
        table_d = 1.4

        # The back row is drawn first so the table hides it.
        for index in range(5):
            cx = table_x + (index + 0.5) * table_w / 5
            self._sprite(painter, "chair_meeting", cx, table_z - 0.45, 0.95)

        self._shadow(painter, table_x + table_w / 2, table_z + table_d / 2, 4.0, 1.6)
        self._box(painter, table_x, table_z, table_w, table_d, 20, TABLE, DESK_LEG)
        self._sprite(painter, "projector", table_x + table_w / 2, table_z + table_d / 2, 1.1)

        for index in range(5):
            cx = table_x + (index + 0.5) * table_w / 5
            self._sprite(painter, "chair_meeting", cx, table_z + table_d + 0.55, 0.95, flip=True)

        # A whiteboard at the far right of the room.
        self._sprite(painter, "whiteboard", x + w - 2.4, z + 0.9, 1.8)

    def _glass_wall(self, painter: QPainter, x: float, z: float, w: float, d: float,
                    axis: str) -> None:
        """A translucent glass panel, used only where glass is intended."""
        height = 54.0
        if axis == "x":
            a = self.to_screen(x, z)
            b = self.to_screen(x + w, z)
        else:
            a = self.to_screen(x, z)
            b = self.to_screen(x, z + d)
        painter.setBrush(QBrush(QColor(176, 216, 232, 70)))
        painter.setPen(QPen(QColor("#f4f7fa"), 2))
        painter.drawPolygon(QPolygonF([
            a, b, QPointF(b.x(), b.y() - height), QPointF(a.x(), a.y() - height),
        ]))

    def _draw_floor(self, painter: QPainter, x0: float, x1: float, z0: float, z1: float) -> None:
        """Wooden planks running along x."""
        painter.setPen(Qt.NoPen)
        for i in range(int(z0), int(z1)):
            painter.setBrush(QBrush(FLOOR_A if i % 2 == 0 else FLOOR_B))
            painter.drawPolygon(self._quad(x0, float(i), x1 - x0, 1.0))

        # Plank seams.
        painter.setPen(QPen(FLOOR_SEAM, 1))
        for i in range(int(z0), int(z1) + 1):
            painter.drawLine(self.to_screen(x0, float(i)), self.to_screen(x1, float(i)))

        # Slab edge, so the room reads as a solid block.
        slab_h = 18.0
        for start, end in (
            ((x1, z0), (x1, z1)),
            ((x1, z1), (x0, z1)),
        ):
            a = self.to_screen(*start)
            b = self.to_screen(*end)
            painter.setBrush(QBrush(FLOOR_EDGE))
            painter.setPen(QPen(FLOOR_SEAM, 1))
            painter.drawPolygon(QPolygonF([
                a, b, QPointF(b.x(), b.y() + slab_h), QPointF(a.x(), a.y() + slab_h),
            ]))

    def _draw_wall(self, painter: QPainter, start: tuple[float, float],
                   end: tuple[float, float]) -> None:
        """A wall standing straight up from one floor edge."""
        a = self.to_screen(*start)
        b = self.to_screen(*end)
        painter.setBrush(QBrush(WALL))
        painter.setPen(QPen(WALL_EDGE, 1))
        painter.drawPolygon(QPolygonF([
            a, b, QPointF(b.x(), b.y() - WALL_H), QPointF(a.x(), a.y() - WALL_H),
        ]))
        # Lower band, so the wall has a base like a real room.
        painter.setBrush(QBrush(WALL_LOWER))
        painter.drawPolygon(QPolygonF([
            a, b, QPointF(b.x(), b.y() - 16), QPointF(a.x(), a.y() - 16),
        ]))

    def _draw_window_band(self, painter: QPainter, wall: str, a: float, b: float,
                          coord: float) -> None:
        """A floor-to-ceiling window with sky, clouds and a skyline.

        Everything is positioned by interpolating inside the wall rectangle
        instead of clipping. Clip paths combined with brushes were crashing
        Qt intermittently, and this is both simpler and faster.
        """
        low, high = 18.0, WALL_H - 12.0

        def point(u: float, v: float) -> QPointF:
            x = a + (b - a) * u
            h = low + (high - low) * v
            if wall == "z":
                return self.to_screen(x, coord, h)
            return self.to_screen(coord, x, h)

        def quad(u0: float, v0: float, u1: float, v1: float) -> QPolygonF:
            return QPolygonF([point(u0, v0), point(u1, v0), point(u1, v1), point(u0, v1)])

        # Sky, in two flat bands.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(SKY_TOP))
        painter.drawPolygon(quad(0.0, 0.0, 1.0, 0.45))
        painter.setBrush(QBrush(SKY_BOTTOM))
        painter.drawPolygon(quad(0.0, 0.45, 1.0, 1.0))

        # Clouds.
        painter.setBrush(QBrush(CLOUD))
        for u, v, radius in ((0.18, 0.20, 9), (0.26, 0.27, 6), (0.66, 0.16, 7)):
            painter.drawEllipse(point(u, v), radius, radius * 0.55)

        # Skyline along the bottom of the window.
        step = 1.0 / 9.0
        for i in range(9):
            height = 0.16 + 0.20 * ((i * 37) % 5) / 4.0
            u0 = i * step + step * 0.12
            u1 = u0 + step * 0.74
            painter.setBrush(QBrush(CITY if i % 2 else CITY_DARK))
            painter.drawPolygon(quad(u0, 1.0 - height, u1, 1.0))
            painter.setBrush(QBrush(CITY_LIGHT))
            for row in range(3):
                for col in range(2):
                    cu = u0 + (u1 - u0) * (0.22 + col * 0.36)
                    cw = (u1 - u0) * 0.16
                    v0 = 1.0 - height + 0.05 + row * 0.10
                    painter.drawPolygon(quad(cu, v0, cu + cw, v0 + 0.035))

        # Frame and mullions.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#f4f4f4"), 3))
        painter.drawPolygon(quad(0.0, 0.0, 1.0, 1.0))
        painter.setPen(QPen(QColor("#f4f4f4"), 2))
        for k in (1, 2, 3):
            f = k / 4.0
            painter.drawLine(point(f, 0.0), point(f, 1.0))

    def _draw_desk_rugs(self, painter: QPainter) -> None:
        """A coloured plate under every desk, like a status rug."""
        for item in self.furniture:
            if item.kind != "desk":
                continue
            avatar = self.avatars.get(item.owner)
            index = avatar.color_index if avatar else 0
            color = RUG_COLORS[index % len(RUG_COLORS)]
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color.darker(150), 1))
            painter.drawPolygon(self._quad(item.x - 1.45, item.z - 1.05, 2.9, 2.1, 1.0))
            painter.setBrush(QBrush(color.lighter(118)))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(self._quad(item.x - 1.25, item.z - 0.9, 2.5, 1.8, 1.6))

    def _zone(self, painter: QPainter, x: float, z: float, w: float, d: float,
              color: QColor) -> None:
        """A coloured floor plate marking one area of the office."""
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(color.darker(112), 1))
        painter.drawPolygon(self._quad(x, z, w, d, 0.6))

    def _draw_zones(self, painter: QPainter, x0: float, x1: float,
                    z0: float, z1: float) -> None:
        """Work, kitchen and lounge areas, each with its own floor colour."""
        self._zone(painter, x0 + 2.4, z0 + 0.4, (x1 - x0) - 8.4, 7.4, QColor("#5c8a80"))
        self._zone(painter, x0 + 0.3, z0 + 8.6, 4.8, 5.2, QColor("#d9d3c6"))
        self._zone(painter, x1 - 7.2, z1 - 4.4, 6.6, 4.2, QColor("#b08a7a"))

    def _draw_digital_board(self, painter: QPainter, wall: str, a: float, b: float,
                            coord: float) -> None:
        """A wall screen showing the office numbers."""
        panel = self._wall_quad(wall, a, b, coord, 30, 96)
        painter.setBrush(QBrush(QColor("#161f2c")))
        painter.setPen(QPen(QColor("#0c121b"), 3))
        painter.drawPolygon(panel)

        rect = panel.boundingRect()
        painter.save()
        path = QPainterPath()
        path.addPolygon(panel)
        path.closeSubpath()
        painter.setClipPath(path)

        painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
        painter.setPen(QPen(QColor("#7fd4c1")))
        painter.drawText(QRectF(rect.left() + 6, rect.top() + 4, rect.width() - 12, 12),
                         Qt.AlignLeft | Qt.AlignVCenter, "OFFICE")
        rows = (
            ("Working", str(self.stats.get("working", 0)), QColor("#ffb45e")),
            ("Idle", str(self.stats.get("idle", 0)), QColor("#6fcf97")),
            ("Cost", f"{self.stats.get('cost', 0):.2f}", QColor("#8ab4f8")),
        )
        y = rect.top() + 20
        for label, value, color in rows:
            painter.setPen(QPen(QColor("#93a0b8")))
            painter.drawText(QRectF(rect.left() + 6, y, rect.width() * 0.6, 12),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setPen(QPen(color))
            painter.drawText(QRectF(rect.left() + rect.width() * 0.5, y,
                                    rect.width() * 0.45, 12),
                             Qt.AlignRight | Qt.AlignVCenter, value)
            y += 14
        painter.restore()

    def _draw_poster(self, painter: QPainter, wall: str, a: float, b: float,
                     coord: float) -> None:
        panel = self._wall_quad(wall, a, b, coord, 46, 76)
        painter.setBrush(QBrush(QColor("#e8c9a8")))
        painter.setPen(QPen(QColor("#b99a78"), 2))
        painter.drawPolygon(panel)

    def _draw_bin(self, painter: QPainter, x: float, z: float) -> None:
        self._shadow(painter, x, z, 0.7, 0.7)
        self._box(painter, x - 0.25, z - 0.25, 0.5, 0.5, 12,
                  QColor("#5a6270"), QColor("#3f4652"))
        top = self.to_screen(x, z, 12)
        painter.setBrush(QBrush(QColor("#2f3640")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(top, 4.5, 2.2)

    def _draw_coat_rack(self, painter: QPainter, x: float, z: float) -> None:
        base = self.to_screen(x, z)
        painter.setPen(QPen(QColor("#6b4a2c"), 2))
        painter.drawLine(base, QPointF(base.x(), base.y() - 44))
        painter.setPen(QPen(QColor("#6b4a2c"), 1.5))
        painter.drawLine(QPointF(base.x() - 7, base.y() - 40),
                         QPointF(base.x() + 7, base.y() - 40))
        painter.setBrush(QBrush(QColor("#3f6b73")))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(base.x() - 9, base.y() - 40, 7, 18), 2, 2)

    def _draw_boxes(self, painter: QPainter, x: float, z: float) -> None:
        self._box(painter, x, z, 0.7, 0.7, 10, QColor("#c9a26b"), QColor("#a17a48"))
        self._box(painter, x + 0.55, z + 0.45, 0.6, 0.6, 8,
                  QColor("#d8b07a"), QColor("#a17a48"))

    def _draw_tv(self, painter: QPainter, x: float, z: float) -> None:
        self._box(painter, x, z, 1.2, 0.4, 14, QColor("#6b4a2c"), QColor("#4a3018"))
        screen = self.to_screen(x + 0.6, z + 0.2, 30)
        painter.setBrush(QBrush(QColor("#1b2433")))
        painter.setPen(QPen(QColor("#0f1620"), 2))
        painter.drawRoundedRect(QRectF(screen.x() - 14, screen.y() - 12, 28, 17), 2, 2)
        painter.setBrush(QBrush(QColor("#3a6ea8")))
        painter.drawRoundedRect(QRectF(screen.x() - 12, screen.y() - 10, 24, 13), 1, 1)

    def _draw_coffee_table(self, painter: QPainter, x: float, z: float) -> None:
        self._box(painter, x, z, 1.2, 0.7, 10, QColor("#a97c4e"), QColor("#6b4a2c"))

    def _draw_armchair(self, painter: QPainter, x: float, z: float) -> None:
        self._shadow(painter, x + 0.45, z + 0.4, 1.2, 1.2)
        self._box(painter, x, z, 0.9, 0.8, 13, SOFA, SOFA_DARK)
        self._box(painter, x, z - 0.2, 0.9, 0.3, 24, SOFA, SOFA_DARK)

    # ------------------------------------------------------- wall decor

    def _draw_clock(self, painter: QPainter, wall: str, a: float, coord: float) -> None:
        centre = (
            self.to_screen(a, coord, WALL_H - 34) if wall == "z"
            else self.to_screen(coord, a, WALL_H - 34)
        )
        painter.setBrush(QBrush(QColor("#f4efe4")))
        painter.setPen(QPen(QColor("#8a7f6c"), 2))
        painter.drawEllipse(centre, 9, 9)
        painter.setPen(QPen(QColor("#3a3630"), 1.5))
        painter.drawLine(centre, QPointF(centre.x(), centre.y() - 6))
        painter.drawLine(centre, QPointF(centre.x() + 4, centre.y() + 1))

    def _draw_whiteboard(self, painter: QPainter, wall: str, a: float, b: float,
                         coord: float) -> None:
        panel = self._wall_quad(wall, a, b, coord, 34, WALL_H - 16)
        painter.setBrush(QBrush(QColor("#f7f7f2")))
        painter.setPen(QPen(QColor("#9aa0a6"), 2))
        painter.drawPolygon(panel)
        painter.setPen(Qt.NoPen)
        for k in range(3):
            height = WALL_H - 28 - k * 10
            line = self._wall_quad(wall, a + 0.2, b - 0.4 - k * 0.25, coord, height, height + 1.6)
            painter.setBrush(QBrush(QColor("#7a8fa6")))
            painter.drawPolygon(line)

    def _draw_bulletin(self, painter: QPainter, wall: str, a: float, b: float,
                       coord: float) -> None:
        board = self._wall_quad(wall, a, b, coord, 44, WALL_H - 18)
        painter.setBrush(QBrush(QColor("#c8a06a")))
        painter.setPen(QPen(QColor("#8a6a3f"), 2))
        painter.drawPolygon(board)
        painter.setPen(Qt.NoPen)
        notes = ((0.15, 0.45, 0.62, "#f2e6a8"), (0.5, 0.8, 0.7, "#f2b8b5"),
                 (0.2, 0.4, 0.38, "#bfe0f0"), (0.55, 0.85, 0.46, "#c7e6c0"))
        for start, end, frac, color in notes:
            height = 44 + (WALL_H - 62) * frac
            note = self._wall_quad(
                wall, a + (b - a) * start, a + (b - a) * end, coord, height, height + 10,
            )
            painter.setBrush(QBrush(QColor(color)))
            painter.drawPolygon(note)

    # ----------------------------------------------------------- furniture

    def _draw_kitchen(self, painter: QPainter, x: float, z: float) -> None:
        self._shadow(painter, x + 0.5, z + 1.6, 3.4, 3.4)
        self._box(painter, x, z, 1.0, 3.2, 24, COUNTER, COUNTER_SIDE)
        self._box(painter, x + 0.15, z + 0.25, 0.7, 0.7, 17, CHAIR, CHAIR_DARK)
        self._draw_water_cooler(painter, x + 0.5, z + 2.9)
        if not self._sprite(painter, "fridge", x + 0.5, z + 4.1, 1.1):
            self._box(painter, x, z + 3.6, 1.0, 1.0, 36, FRIDGE, FRIDGE_SIDE)

    def _draw_water_cooler(self, painter: QPainter, x: float, z: float) -> None:
        if self._sprite(painter, "cooler", x, z, 0.9):
            return
        self._box(painter, x - 0.35, z - 0.35, 0.7, 0.7, 26, QColor("#dfe6ea"), QColor("#aab6bd"))
        top = self.to_screen(x, z, 26)
        painter.setBrush(QBrush(QColor("#8ec8dd")))
        painter.setPen(QPen(QColor("#5f9db3"), 1))
        painter.drawEllipse(QRectF(top.x() - 7, top.y() - 20, 14, 20))

    def _draw_lounge(self, painter: QPainter, x: float, z: float) -> None:
        if self._sprite(painter, "sofa", x + 1.3, z + 0.5, 3.2):
            return
        painter.setBrush(QBrush(QColor("#b98a7a")))
        painter.setPen(QPen(QColor("#9a6f62"), 1))
        painter.drawPolygon(self._quad(x - 0.5, z - 0.6, 4.3, 3.0, 1.0))

        self._shadow(painter, x + 1.3, z + 0.6, 3.0, 2.0)
        self._box(painter, x, z, 2.6, 0.9, 15, SOFA, SOFA_DARK)
        self._box(painter, x, z - 0.35, 2.6, 0.35, 28, SOFA, SOFA_DARK)
        self._box(painter, x + 3.0, z, 0.7, 0.7, 17, TABLE, DESK_LEG)

        base = self.to_screen(x - 0.6, z + 0.3)
        painter.setPen(QPen(QColor("#5a5f6b"), 2))
        painter.drawLine(base, QPointF(base.x(), base.y() - 46))
        painter.setBrush(QBrush(QColor("#ffe6a8")))
        painter.setPen(QPen(QColor("#c9a24a"), 1))
        painter.drawPolygon(QPolygonF([
            QPointF(base.x() - 9, base.y() - 46), QPointF(base.x() + 9, base.y() - 46),
            QPointF(base.x() + 6, base.y() - 60), QPointF(base.x() - 6, base.y() - 60),
        ]))

    def _draw_bookshelf(self, painter: QPainter, x: float, z: float) -> None:
        if self._sprite(painter, "shelf", x + 0.45, z + 1.0, 1.4):
            return
        self._shadow(painter, x + 0.45, z + 1.0, 1.6, 2.6)
        self._box(painter, x, z, 0.9, 2.0, 42, SHELF, DESK_LEG)
        book_colors = ("#d9534f", "#5bc0de", "#5cb85c", "#f0ad4e", "#9b6bd1", "#e8756a")
        count = 7
        painter.setPen(Qt.NoPen)
        for i in range(count):
            t0 = i / count + 0.015
            t1 = (i + 1) / count - 0.015
            for shelf, base_h in enumerate((12.0, 26.0)):
                painter.setBrush(QBrush(QColor(book_colors[(i + shelf) % len(book_colors)])))
                painter.drawPolygon(QPolygonF([
                    self.to_screen(x + 0.9 * t0, z + 2.0, base_h),
                    self.to_screen(x + 0.9 * t1, z + 2.0, base_h),
                    self.to_screen(x + 0.9 * t1, z + 2.0, base_h + 9),
                    self.to_screen(x + 0.9 * t0, z + 2.0, base_h + 9),
                ]))

    def _draw_printer(self, painter: QPainter, x: float, z: float) -> None:
        if self._sprite(painter, "printer", x + 0.45, z + 0.4, 1.2):
            return
        self._shadow(painter, x + 0.45, z + 0.4, 1.3, 1.2)
        self._box(painter, x, z, 0.9, 0.8, 20, QColor("#e8ecf0"), QColor("#b3bcc6"))
        top = self.to_screen(x + 0.45, z + 0.4, 20)
        painter.setBrush(QBrush(QColor("#cfd6de")))
        painter.setPen(QPen(QColor("#9aa4ae"), 1))
        painter.drawRoundedRect(QRectF(top.x() - 6, top.y() - 4, 12, 4), 1, 1)

    def _draw_office_room(self, painter: QPainter, x: float, z: float,
                          w: float, d: float) -> None:
        """The leader's office: a solid light-blue room with an open front."""
        # Floor plate.
        painter.setBrush(QBrush(QColor("#cfe4ef")))
        painter.setPen(QPen(QColor("#a9c6d6"), 1))
        painter.drawPolygon(self._quad(x, z, w, d, 1.0))

        wall_h = 46.0
        # Back wall (z side) and left wall (x side); the front stays open.
        self._box(painter, x, z, w, 0.18, wall_h, GLASS_OFFICE, QColor("#8fb6c9"))
        self._box(painter, x, z, 0.18, d, wall_h, GLASS_OFFICE, QColor("#8fb6c9"))
        self._box(painter, x + w - 0.18, z, 0.18, d, wall_h, GLASS_OFFICE, QColor("#8fb6c9"))

        # A desk inside.
        self._box(painter, x + 0.6, z + 0.8, 1.6, 0.7, 14, DESK_TOP, DESK_SIDE)
        screen = self.to_screen(x + 1.4, z + 0.95, 26)
        painter.setBrush(QBrush(MONITOR))
        painter.setPen(QPen(CHAIR_DARK, 1))
        painter.drawRoundedRect(QRectF(screen.x() - 9, screen.y() - 8, 18, 13), 2, 2)
        painter.setBrush(QBrush(MONITOR_SCREEN))
        painter.drawRoundedRect(QRectF(screen.x() - 7, screen.y() - 6, 14, 9), 1, 1)

    def _draw_meeting_set(self, painter: QPainter, mx: float, mz: float) -> None:
        top = self.to_screen(mx, mz, 20)
        rx = 1.7 * self.tile_w / 2
        ry = 1.7 * self.tile_h / 2
        painter.setPen(QPen(DESK_LEG, 3))
        painter.drawLine(QPointF(top.x(), top.y()), QPointF(top.x(), top.y() + 20))
        painter.setBrush(QBrush(DESK_LEG))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(top.x(), top.y() + 20), rx, ry)
        painter.setBrush(QBrush(TABLE))
        painter.setPen(QPen(DESK_LEG, 2))
        painter.drawEllipse(top, rx, ry)
        for dx, dz in ((2.3, 0.0), (-2.3, 0.0), (0.0, 2.0), (0.0, -2.0)):
            seat = self.to_screen(mx + dx, mz + dz, 9)
            painter.setBrush(QBrush(CHAIR))
            painter.setPen(QPen(CHAIR_DARK, 1))
            painter.drawRoundedRect(QRectF(seat.x() - 6, seat.y() - 5, 12, 9), 3, 3)
            painter.drawRoundedRect(QRectF(seat.x() - 6, seat.y() - 12, 12, 4), 2, 2)

    def _draw_plant(self, painter: QPainter, x: float, z: float) -> None:
        if self._sprite(painter, "plant", x, z, 1.3):
            return
        base = self.to_screen(x, z)
        painter.setBrush(QBrush(QColor("#a9764e")))
        painter.setPen(QPen(QColor("#7d563a"), 1))
        painter.drawRoundedRect(QRectF(base.x() - 8, base.y() - 14, 16, 14), 3, 3)
        for offset, height in ((-6, 30), (0, 38), (6, 28)):
            tip = self.to_screen(x + offset / 14.0, z, height)
            painter.setBrush(QBrush(QColor("#4f8f4f") if offset else QColor("#3f7a3f")))
            painter.setPen(QPen(QColor("#356635"), 1))
            painter.drawEllipse(tip, 7, 11)

    def _draw_furniture(self, painter: QPainter) -> None:
        # Every planned workstation is drawn, occupied or not, so the office
        # looks like an office rather than a few floating desks.
        occupied = {(round(item.x, 2), round(item.z, 2)) for item in self.furniture}
        empty = [
            (pos[0], pos[1]) for pos in self.desk_slots
            if (round(pos[0], 2), round(pos[1], 2)) not in occupied
        ]
        for x, z in sorted(empty, key=lambda pair: pair[1]):
            self._draw_desk(painter, x, z, "")
        for item in sorted(self.furniture, key=lambda f: f.z):
            if item.kind != "desk":
                continue
            self._draw_desk(painter, item.x, item.z, item.owner)

    def _draw_desk(self, painter: QPainter, x: float, z: float, owner: str) -> None:
        if self._sprite(painter, "desk", x, z + 0.1, 2.6):
            self._sprite(painter, "monitor", x, z - 0.35, 0.95)
            return
        self._shadow(painter, x, z + 0.2, 2.2, 1.6)

        # Filing cabinet beside the desk, as in a real office layout.
        self._box(painter, x + 1.0, z - 0.35, 0.45, 0.7, 18,
                  QColor("#b9bfc7"), QColor("#8d949c"))
        cabinet = self.to_screen(x + 1.45, z + 0.35, 18)
        painter.setPen(QPen(QColor("#8d949c"), 1))
        for offset in (5, 10):
            painter.drawLine(
                QPointF(cabinet.x() - 5, cabinet.y() + offset),
                QPointF(cabinet.x() + 5, cabinet.y() + offset),
            )

        # Desk body.
        self._box(painter, x - 0.8, z - 0.5, 1.6, 1.0, 14, DESK_TOP, DESK_SIDE)
        for dx in (-0.7, 0.7):
            foot = self.to_screen(x + dx, z + 0.4)
            painter.setPen(QPen(DESK_LEG, 3))
            painter.drawLine(QPointF(foot.x(), foot.y()), QPointF(foot.x(), foot.y() - 14))

        # Chair behind the desk.
        chair = self.to_screen(x, z + 0.95, 9)
        painter.setBrush(QBrush(CHAIR))
        painter.setPen(QPen(CHAIR_DARK, 1))
        painter.drawRoundedRect(QRectF(chair.x() - 8, chair.y() - 6, 16, 15), 4, 4)
        painter.drawRoundedRect(QRectF(chair.x() - 8, chair.y() - 16, 16, 5), 3, 3)

        # Monitor.
        screen = self.to_screen(x, z - 0.25, 28)
        painter.setBrush(QBrush(MONITOR))
        painter.setPen(QPen(CHAIR_DARK, 1))
        painter.drawRoundedRect(QRectF(screen.x() - 9, screen.y() - 8, 18, 13), 2, 2)
        painter.setBrush(QBrush(MONITOR_SCREEN))
        painter.drawRoundedRect(QRectF(screen.x() - 7, screen.y() - 6, 14, 9), 1, 1)

        # Keyboard, mug and papers on the desk.
        keyboard = self.to_screen(x, z + 0.15, 15)
        painter.setBrush(QBrush(QColor("#dfe3ea")))
        painter.setPen(QPen(QColor("#aab2bf"), 1))
        painter.drawRoundedRect(QRectF(keyboard.x() - 7, keyboard.y() - 3, 14, 5), 1.5, 1.5)
        cup = self.to_screen(x + 0.62, z - 0.15, 15)
        painter.setBrush(QBrush(QColor("#f2f5fb")))
        painter.setPen(QPen(QColor("#c2c8d2"), 1))
        painter.drawEllipse(QRectF(cup.x() - 2.2, cup.y() - 3.5, 4.4, 5))
        papers = self.to_screen(x - 0.58, z + 0.28, 15)
        painter.setBrush(QBrush(QColor("#fbfaf6")))
        painter.setPen(QPen(QColor("#d6d2c6"), 1))
        painter.drawRoundedRect(QRectF(papers.x() - 4, papers.y() - 3, 8, 5), 1, 1)

    # -------------------------------------------------------------- avatars

    def _draw_avatar(self, painter: QPainter, avatar: Avatar) -> None:
        state = (avatar.state or "idle").lower()
        s = self.avatar_scale
        bob = math.sin(avatar.bob) * 1.8 if avatar.walking else 0.0
        if not avatar.walking and state in ("idle", "working"):
            bob += math.sin(self._time * 1.8 + avatar.color_index) * 1.0
        base = self.to_screen(avatar.x, avatar.z, bob)

        runtime = (avatar.runtime or "").lower()
        if avatar.kind == "user":
            shirt = OWNER_SUIT
        elif runtime in OUTFIT_COLORS:
            shirt = OUTFIT_COLORS[runtime]
        else:
            shirt = SHIRT_COLORS[avatar.color_index % len(SHIRT_COLORS)]
        skin = SKIN_TONES[avatar.color_index % len(SKIN_TONES)]
        hair_color = HAIR_COLORS[avatar.color_index % len(HAIR_COLORS)]
        pants = PANTS_COLORS[avatar.color_index % len(PANTS_COLORS)]

        # Contact shadow.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 55)))
        painter.drawEllipse(QPointF(base.x(), base.y()), 9.5 * s, 4.2 * s)

        # Legs, or a skirt for the female variant.
        female = avatar.color_index % 2 == 1
        painter.setBrush(QBrush(pants))
        painter.setPen(QPen(pants.darker(130), 1))
        if female:
            painter.drawPolygon(QPolygonF([
                QPointF(base.x() - 6.0 * s, base.y() - 14 * s),
                QPointF(base.x() + 6.0 * s, base.y() - 14 * s),
                QPointF(base.x() + 8.2 * s, base.y() - 4.0 * s),
                QPointF(base.x() - 8.2 * s, base.y() - 4.0 * s),
            ]))
            painter.setBrush(QBrush(skin))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(
                QRectF(base.x() - 4.6 * s, base.y() - 5 * s, 3.2 * s, 5 * s), 1.2 * s, 1.2 * s
            )
            painter.drawRoundedRect(
                QRectF(base.x() + 1.4 * s, base.y() - 5 * s, 3.2 * s, 5 * s), 1.2 * s, 1.2 * s
            )
        else:
            painter.drawRoundedRect(
                QRectF(base.x() - 5.2 * s, base.y() - 12 * s, 4.4 * s, 12 * s), 1.2 * s, 1.2 * s
            )
            painter.drawRoundedRect(
                QRectF(base.x() + 0.8 * s, base.y() - 12 * s, 4.4 * s, 12 * s), 1.2 * s, 1.2 * s
            )

        # Torso: a block.
        painter.setBrush(QBrush(shirt))
        painter.setPen(QPen(shirt.darker(135), 1))
        painter.drawRoundedRect(
            QRectF(base.x() - 7.2 * s, base.y() - 30 * s, 14.4 * s, 19 * s), 2.2 * s, 2.2 * s
        )

        # Arms.
        painter.setBrush(QBrush(shirt.darker(112)))
        painter.setPen(QPen(shirt.darker(135), 1))
        painter.drawRoundedRect(
            QRectF(base.x() - 10.4 * s, base.y() - 29 * s, 3.6 * s, 12 * s), 1.4 * s, 1.4 * s
        )
        painter.drawRoundedRect(
            QRectF(base.x() + 6.8 * s, base.y() - 29 * s, 3.6 * s, 12 * s), 1.4 * s, 1.4 * s
        )

        # Hands.
        painter.setBrush(QBrush(skin))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(base.x() - 8.6 * s, base.y() - 17.5 * s), 1.8 * s, 1.8 * s)
        painter.drawEllipse(QPointF(base.x() + 8.6 * s, base.y() - 17.5 * s), 1.8 * s, 1.8 * s)

        # The owner wears a white shirt and a gold tie.
        if avatar.kind == "user":
            painter.setBrush(QBrush(QColor("#f4f4f4")))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygonF([
                QPointF(base.x() - 3.2 * s, base.y() - 30 * s),
                QPointF(base.x() + 3.2 * s, base.y() - 30 * s),
                QPointF(base.x(), base.y() - 20 * s),
            ]))
            painter.setBrush(QBrush(OWNER_TIE))
            painter.drawPolygon(QPolygonF([
                QPointF(base.x() - 1.3 * s, base.y() - 22 * s),
                QPointF(base.x() + 1.3 * s, base.y() - 22 * s),
                QPointF(base.x(), base.y() - 12 * s),
            ]))

        # Typing hands while working.
        if state == "working":
            phase = math.sin(self._time * 11.0) * 2.0 * s
            painter.setBrush(QBrush(skin))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                QPointF(base.x() - 5.5 * s, base.y() - 16 * s + phase), 2.1 * s, 2.1 * s
            )
            painter.drawEllipse(
                QPointF(base.x() + 5.5 * s, base.y() - 16 * s - phase), 2.1 * s, 2.1 * s
            )

        # Head: a block, like the reference art.
        head = QRectF(base.x() - 7.0 * s, base.y() - 47 * s, 14.0 * s, 17.0 * s)
        painter.setBrush(QBrush(skin))
        painter.setPen(QPen(skin.darker(115), 1))
        painter.drawRoundedRect(head, 2.4 * s, 2.4 * s)

        # Hair, four styles.
        style = avatar.color_index % 4
        painter.setBrush(QBrush(hair_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(
            QRectF(head.left() - 0.6 * s, head.top() - 1.2 * s,
                   head.width() + 1.2 * s, 6.0 * s), 1.8 * s, 1.8 * s
        )
        if female:
            # Long hair down both sides, plus a small bow.
            painter.drawRoundedRect(
                QRectF(head.left() - 1.4 * s, head.top() + 2.0 * s, 3.2 * s, 12.0 * s),
                1.6 * s, 1.6 * s,
            )
            painter.drawRoundedRect(
                QRectF(head.right() - 1.8 * s, head.top() + 2.0 * s, 3.2 * s, 12.0 * s),
                1.6 * s, 1.6 * s,
            )
            painter.setBrush(QBrush(QColor("#e8756a")))
            painter.drawEllipse(QPointF(head.right() - 1.0 * s, head.top() + 0.6 * s),
                                2.8 * s, 2.2 * s)
        if style == 1:
            # Side part: a fringe over one side.
            painter.drawRoundedRect(
                QRectF(head.left() + 7.6 * s, head.top() + 3.4 * s, 6.0 * s, 5.0 * s),
                1.2 * s, 1.2 * s,
            )
        elif style == 2:
            # Bun.
            painter.drawEllipse(QPointF(head.center().x(), head.top() - 3.6 * s), 3.4 * s, 3.0 * s)
        elif style == 3:
            # Cap.
            painter.setBrush(QBrush(QColor("#d9534f")))
            painter.drawRoundedRect(
                QRectF(head.left() - 1.2 * s, head.top() - 2.4 * s,
                       head.width() + 2.4 * s, 6.4 * s), 1.8 * s, 1.8 * s
            )
            painter.drawRoundedRect(
                QRectF(head.left() + 4.6 * s, head.top() + 3.6 * s, 10.0 * s, 2.6 * s),
                1.0 * s, 1.0 * s,
            )

        # Eyes.
        blinking = math.sin(self._time * 1.7 + avatar.color_index * 2.1) > 0.985
        eye_y = head.top() + 8.0 * s
        for sign in (-1, 1):
            ex = head.center().x() + sign * 3.4 * s
            if blinking:
                painter.setPen(QPen(QColor("#2b2320"), 1.3))
                painter.drawLine(QPointF(ex - 1.5 * s, eye_y), QPointF(ex + 1.5 * s, eye_y))
            else:
                painter.setBrush(QBrush(QColor("#2b2320")))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(
                    QRectF(ex - 1.1 * s, eye_y - 1.4 * s, 2.2 * s, 2.8 * s), 0.8 * s, 0.8 * s
                )

        # Smile.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#8a5a3c"), 1.2))
        painter.drawArc(
            QRectF(head.center().x() - 2.2 * s, head.top() + 10.0 * s, 4.4 * s, 3.2 * s),
            200 * 16,
            140 * 16,
        )

        # A sub-agent wears an antenna, so it reads as a spawned tool worker.
        antenna_top = None
        if avatar.rank == "member":
            ax = head.center().x()
            ay = head.top() - 2.0 * s
            if style == 2:
                ax += 5.0 * s
            painter.setPen(QPen(QColor("#9aa4ae"), 1.6))
            painter.drawLine(QPointF(ax, ay), QPointF(ax, ay - 9.0 * s))
            painter.setBrush(QBrush(STATE_COLORS.get(state, STATE_COLORS["idle"])))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(ax, ay - 9.0 * s), 2.5 * s, 2.5 * s)
            antenna_top = ay - 11.5 * s

        # Selection ring.
        if avatar.selected or avatar.id == self.hovered:
            painter.setBrush(Qt.NoBrush)
            ring = QColor("#ffb45e") if avatar.selected else QColor(255, 255, 255, 90)
            painter.setPen(QPen(ring, 2))
            painter.drawEllipse(QPointF(base.x(), base.y()), 12 * s, 6 * s)

        # Name plate above the head: nickname-role-model.
        text = avatar.tag or avatar.name
        font = QFont("Segoe UI", 7)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        lift = 16.0
        if antenna_top is not None:
            lift = (head.top() - antenna_top) / s + 8.0
        stagger = 10.0 * (avatar.color_index % 3)
        plate = QRectF(
            base.x() - text_width / 2 - 5,
            head.top() - (lift + stagger) * s,
            text_width + 10,
            metrics.height() + 3,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(18, 22, 31, 205)))
        painter.drawRoundedRect(plate, 4, 4)
        painter.setPen(QPen(QColor("#f2f5fb")))
        painter.drawText(plate, Qt.AlignCenter, text)

        # Status dot on the plate.
        status_color = STATE_COLORS.get(state, STATE_COLORS["idle"])
        painter.setPen(QPen(QColor(18, 22, 31, 200), 1))
        painter.setBrush(QBrush(status_color))
        painter.drawEllipse(QPointF(plate.left() - 5.0, plate.center().y()), 3.0, 3.0)

        if avatar.bubble:
            self._draw_bubble(painter, avatar, base)

    def _draw_bubble(self, painter: QPainter, avatar: Avatar, base: QPointF) -> None:
        text = avatar.bubble
        if len(text) > 28:
            text = text[:27] + "…"
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 14
        height = metrics.height() + 8
        rect = QRectF(base.x() - width / 2, base.y() - 82 * self.avatar_scale, width, height)
        painter.setBrush(QBrush(QColor(252, 252, 248, 238)))
        painter.setPen(QPen(QColor("#b8b2a4"), 1))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QPen(QColor("#2b2b28")))
        painter.drawText(rect, Qt.AlignCenter, text)

    # ------------------------------------------------------------- overlays

    def _draw_overlays(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#8f9bb0")))
        painter.setFont(QFont("Segoe UI", 9, QFont.Bold))

        mx, mz = self.meeting_center
        label = self.to_screen(mx, mz + 3.2, 0)
        painter.drawText(QRectF(label.x() - 60, label.y() - 10, 120, 18),
                         Qt.AlignCenter, "Meeting Room")

        lx, lz = self.leader_door
        label = self.to_screen(lx, lz - 1.0, 74)
        painter.drawText(QRectF(label.x() - 70, label.y() - 10, 140, 18),
                         Qt.AlignCenter, "Boss Office")

        self._draw_legend(painter)

    def _draw_legend(self, painter: QPainter) -> None:
        """Status legend in the bottom-left corner, like a game HUD."""
        items = (
            ("idle", "Idle"),
            ("working", "Working"),
            ("waiting", "Waiting"),
            ("walking", "Walking"),
            ("interacting", "Talking"),
            ("meeting", "Meeting"),
            ("offline", "Offline"),
        )
        painter.setFont(QFont("Segoe UI", 8))
        base_x = 18.0
        base_y = self._view_h - 62.0
        for index, (state, label) in enumerate(items):
            column = index % 3
            row = index // 3
            cx = base_x + column * 84
            cy = base_y + row * 18
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(STATE_COLORS[state]))
            painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
            painter.setPen(QPen(QColor("#9aa6b8")))
            painter.drawText(QRectF(cx + 8, cy - 8, 72, 16), Qt.AlignVCenter, label)

    # ------------------------------------------------------------ hit tests

    def avatar_at(self, sx: float, sy: float) -> str | None:
        """Which avatar is under a screen point."""
        reach = 26 * self.avatar_scale
        for avatar in reversed(self._sorted_avatars()):
            base = self.to_screen(avatar.x, avatar.z)
            if (sx - base.x()) ** 2 + (sy - (base.y() - 20 * self.avatar_scale)) ** 2 < reach ** 2:
                return avatar.id
        return None

    def desk_owner_at(self, sx: float, sy: float) -> str | None:
        """Which desk is under a screen point."""
        for item in self.furniture:
            if item.kind != "desk":
                continue
            polygon = self._quad(item.x - 0.8, item.z - 0.5, 1.6, 1.0, 14)
            if polygon.containsPoint(QPointF(sx, sy), Qt.OddEvenFill):
                return item.owner
        return None
