"""Lucide line icons (assets/ui/icons, ISC licence), tinted at runtime."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

ICON_DIR = Path(__file__).resolve().parents[3] / "assets" / "ui" / "icons"


@lru_cache(maxsize=None)
def _svg_source(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _svg_bytes(name: str, color: str, stroke: float, opacity: float) -> QByteArray:
    source = _svg_source(name)
    source = source.replace("currentColor", color)
    source = re.sub(r'stroke-width="[^"]*"', f'stroke-width="{stroke:g}"', source)
    if opacity < 1.0:
        source = source.replace("<svg ", f'<svg stroke-opacity="{opacity:.3f}" ', 1)
    return QByteArray(source.encode("utf-8"))


def _device_ratio() -> float:
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    try:
        return max(1.0, float(screen.devicePixelRatio())) if screen is not None else 1.0
    except Exception:
        return 1.0


@lru_cache(maxsize=2048)
def _pixmap(
    name: str, color: str, opacity: float, size: int, stroke: float, ratio: float
) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer

    side = max(1, round(size * ratio))
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.transparent)
    renderer = QSvgRenderer(_svg_bytes(name, color, stroke, opacity))
    if renderer.isValid():
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, side, side))
        painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def pixmap(name: str, color: QColor | str, size: int = 18, stroke: float = 1.9) -> QPixmap:
    value = QColor(color)
    opacity = round(value.alphaF(), 3)
    return _pixmap(name, value.name(), opacity, int(size), float(stroke), _device_ratio())


def icon(name: str, color: QColor | str, size: int = 18, stroke: float = 1.9) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, color, size, stroke))
    return result


@lru_cache(maxsize=1024)
def _renderer(name: str, color: str, opacity: float, stroke: float):
    from PySide6.QtSvg import QSvgRenderer

    return QSvgRenderer(_svg_bytes(name, color, stroke, opacity))


def paint(
    painter: QPainter, rect: QRectF, name: str, color: QColor | str, stroke: float = 1.9
) -> None:
    """Draw an icon into ``rect`` (logical pixels) with the painter.

    Drawn as lines at the screen's own resolution: a small picture scaled to
    125 % / 150 % made thin strokes uneven, and the tick of a check box
    looked broken at its corner (Leo 2026-11-09 「這個勾感覺像斷掉」)."""
    value = QColor(color)
    side = min(rect.width(), rect.height())
    renderer = _renderer(name, value.name(), round(value.alphaF(), 3), float(stroke))
    if not renderer.isValid():
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(rect.x(), rect.y(), side, side))
    painter.restore()


def icon_size(size: int) -> QSize:
    return QSize(size, size)
