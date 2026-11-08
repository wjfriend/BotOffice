"""Scene widget: hosts the isometric office and handles mouse interaction.

Dragging one avatar onto another triggers a conversation. The widget only
reports the intent; the backend decides what happens (constraint 10).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from .scene import OfficeScene


class SceneWidget(QWidget):
    """The office view."""

    drop_requested = Signal(str, str)  # dragged avatar id, target avatar id
    avatar_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.scene = OfficeScene()

        self._drag_id: str | None = None
        self._drag_offset = QPointF()
        self._press_pos: QPointF | None = None
        self._last_time = 0
        self.pixel_scale = 1  # 1 = crisp vector; >1 = pixel-art downscale

        # Animation timer: about 30 fps is enough for this style.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ------------------------------------------------------------ animation

    def _tick(self) -> None:
        for avatar in self.scene.avatars.values():
            avatar.advance(0.033)
        self.update()

    # -------------------------------------------------------------- drawing

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)

        if self.pixel_scale <= 1:
            self.scene.antialias = True
            self.scene.draw(painter, self.width(), self.height())
            painter.end()
            return

        # Render small, then blow it up with nearest-neighbour sampling.
        # That is what turns the vector scene into crisp pixel art without
        # needing a single image asset.
        width = max(1, self.width() // self.pixel_scale)
        height = max(1, self.height() // self.pixel_scale)
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.black)
        inner = QPainter(image)
        self.scene.antialias = False
        self.scene.draw(inner, width, height)
        inner.end()

        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(self.rect(), image)
        painter.end()

    # --------------------------------------------------------------- mouse

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = QPointF(event.position())
        self._press_pos = pos
        if event.button() != Qt.LeftButton:
            return
        avatar_id = self.scene.avatar_at(pos.x(), pos.y())
        if avatar_id:
            self._drag_id = avatar_id
            avatar = self.scene.avatars[avatar_id]
            self._drag_offset = QPointF(pos.x() - self.scene.to_screen(avatar.x, avatar.z).x(),
                                       pos.y() - self.scene.to_screen(avatar.x, avatar.z).y())
            avatar.selected = True
            for other in self.scene.avatars.values():
                if other.id != avatar_id:
                    other.selected = False
            self.avatar_clicked.emit(avatar_id)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = QPointF(event.position())
        hovered = self.scene.avatar_at(pos.x(), pos.y())
        if hovered != self.scene.hovered:
            self.scene.hovered = hovered
            self.update()
        if self._drag_id:
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._drag_id:
            return
        pos = QPointF(event.position())
        dragged = self._drag_id
        self._drag_id = None

        avatar = self.scene.avatars.get(dragged)
        if avatar:
            avatar.selected = False

        target = self.scene.avatar_at(pos.x(), pos.y())
        if target and target != dragged:
            self.drop_requested.emit(dragged, target)
            self.update()
            return

        # Dropped on empty floor: walk there.
        world = self.scene.to_world(pos.x(), pos.y())
        if avatar:
            avatar.move_to(world[0], world[1])
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        pass
