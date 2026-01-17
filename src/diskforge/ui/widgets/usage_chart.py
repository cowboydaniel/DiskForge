"""
Usage donut widget for DiskForge.

Displays used vs total storage as a compact ring visualization.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class UsageDonutWidget(QWidget):
    """A small donut chart showing used vs total capacity."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._used_bytes: int | None = None
        self._total_bytes: int | None = None
        self._label: str | None = None
        self.setMinimumSize(140, 140)
        self.setMaximumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(150, 150)

    def set_usage(self, used_bytes: int | None, total_bytes: int | None, label: str | None = None) -> None:
        """Set the usage values."""
        self._used_bytes = used_bytes
        self._total_bytes = total_bytes
        self._label = label
        self.update()

    @property
    def usage_ratio(self) -> float | None:
        if self._used_bytes is None or self._total_bytes in (None, 0):
            return None
        return max(0.0, min(1.0, self._used_bytes / self._total_bytes))

    def paintEvent(self, event: object) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(8, 8, -8, -8)
        ring_width = 12

        base_color = QColor("#e3e7ef")
        accent = QColor("#1a69d4")
        empty_pen = QPen(base_color, ring_width, Qt.SolidLine, Qt.RoundCap)
        accent_pen = QPen(accent, ring_width, Qt.SolidLine, Qt.RoundCap)

        painter.setPen(empty_pen)
        painter.drawArc(rect, 0, 360 * 16)

        ratio = self.usage_ratio
        if ratio is not None:
            painter.setPen(accent_pen)
            painter.drawArc(rect, 90 * 16, int(-360 * ratio * 16))

        painter.setPen(QColor("#1f2a44"))
        font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font)
        text = "N/A" if ratio is None else f"{ratio * 100:.0f}%"
        painter.drawText(self.rect(), Qt.AlignCenter, text)

        if self._label:
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QColor("#6f7f9b"))
            label_rect = self.rect().adjusted(8, 8, -8, -8)
            painter.drawText(label_rect, Qt.AlignBottom | Qt.AlignHCenter, self._label)
