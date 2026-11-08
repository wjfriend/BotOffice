"""Optional image sprites for the office.

Drop PNG files into ``assets/`` and the scene draws them instead of the
built-in vector shapes. Missing files fall back to the vector version, so
the app always runs, with or without an art pack.

Expected file names (every one is optional):

    floor.png        one floor tile, drawn across the room
    desk.png         a workstation
    chair.png        an office chair
    plant.png        a potted plant
    sofa.png         a sofa
    table.png        a meeting or coffee table
    fridge.png       a fridge
    cooler.png       a water cooler
    shelf.png        a bookshelf
    printer.png      a printer
    door.png         the entrance door
    whiteboard.png   a whiteboard
    board.png        a bulletin board
    clock.png        a wall clock

Sprites are anchored at the ground point: the image's bottom centre sits on
the floor, and its width is scaled to the world width the caller passes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPixmap

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "assets"


class SpriteSet:
    """Loads sprites lazily and caches the misses as well as the hits."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory or DEFAULT_DIR)
        self._cache: dict[str, QPixmap | None] = {}

    def get(self, name: str) -> QPixmap | None:
        if name in self._cache:
            return self._cache[name]
        path = self.directory / f"{name}.png"
        pixmap: QPixmap | None = None
        if path.exists():
            candidate = QPixmap(str(path))
            pixmap = candidate if not candidate.isNull() else None
        self._cache[name] = pixmap
        return pixmap

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def clear(self) -> None:
        self._cache.clear()
