"""
DiskForge Disk Graphics View.

Visual representation of disk layout.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsItem,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import (
    QColor,
    QBrush,
    QPen,
    QFont,
    QPainter,
    QFontMetrics,
    QLinearGradient,
)
import humanize

from diskforge.core.models import Disk, Partition, FileSystem


FILESYSTEM_COLORS = {
    FileSystem.NTFS: QColor(46, 119, 210),
    FileSystem.FAT32: QColor(240, 178, 52),
    FileSystem.EXFAT: QColor(240, 178, 52),
    FileSystem.EXT4: QColor(84, 179, 109),
    FileSystem.EXT3: QColor(84, 179, 109),
    FileSystem.XFS: QColor(147, 95, 204),
    FileSystem.BTRFS: QColor(240, 140, 48),
    FileSystem.SWAP: QColor(140, 140, 140),
    FileSystem.UNKNOWN: QColor(193, 193, 193),
}

HIGHLIGHT_COLOR = QColor(47, 132, 214)
HIGHLIGHT_GLOW = QColor(255, 255, 255, 150)


def filesystem_color(filesystem: FileSystem) -> QColor:
    """Return the color associated with a filesystem."""
    return FILESYSTEM_COLORS.get(filesystem, QColor(200, 200, 200))


def is_dark_color(color: QColor) -> bool:
    """Determine if a color is dark for contrast."""
    return (color.redF() * 0.299 + color.greenF() * 0.587 + color.blueF() * 0.114) < 0.5


def gradient_qss(color: QColor) -> str:
    """Return a QSS linear gradient for a color swatch."""
    top = color.lighter(125).name()
    bottom = color.darker(115).name()
    return (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {top}, stop:1 {bottom})"
    )


class PartitionRectItem(QGraphicsRectItem):
    """Graphics item representing a partition."""

    def __init__(
        self,
        partition: Partition,
        rect: QRectF,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(rect, parent)
        self.partition = partition

        # Set color based on filesystem
        self._base_color = filesystem_color(partition.filesystem)
        self._border_pen = QPen(QColor(78, 92, 124), 1)

        # Hover effects
        self.setAcceptHoverEvents(True)
        self._hovered = False

        # Tooltip
        tooltip = (
            f"Partition {partition.number}\n"
            f"Device: {partition.device_path}\n"
            f"Size: {humanize.naturalsize(partition.size_bytes, binary=True)}\n"
            f"Filesystem: {partition.filesystem.value}\n"
        )
        if partition.label:
            tooltip += f"Label: {partition.label}\n"
        if partition.mountpoint:
            tooltip += f"Mount: {partition.mountpoint}\n"
        self.setToolTip(tooltip)

    def hoverEnterEvent(self, event: QGraphicsItem.GraphicsItemChange) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsItem.GraphicsItemChange) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def _partition_gradient(self, rect: QRectF) -> QBrush:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, self._base_color.lighter(125))
        gradient.setColorAt(0.55, self._base_color)
        gradient.setColorAt(1.0, self._base_color.darker(115))
        return QBrush(gradient)

    def paint(self, painter: QPainter, option: QGraphicsItem, widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        radius = 2

        painter.setPen(self._border_pen)
        painter.setBrush(self._partition_gradient(rect))
        painter.drawRoundedRect(rect, radius, radius)

        band_height = min(max(rect.height() * 0.22, 6), 14)
        band_rect = QRectF(rect.left(), rect.top(), rect.width(), band_height)
        painter.fillRect(band_rect, self._base_color.darker(120))
        painter.setPen(QPen(QColor(255, 255, 255, 130), 1))
        painter.drawLine(band_rect.left() + 1, band_rect.bottom(), band_rect.right() - 1, band_rect.bottom())

        if self._hovered or self.isSelected():
            highlight_pen = QPen(HIGHLIGHT_COLOR, 2)
            painter.setPen(highlight_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

            if self._hovered and not self.isSelected():
                painter.setPen(QPen(HIGHLIGHT_GLOW, 1))
                painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius, radius)


class DiskGraphicsView(QGraphicsView):
    """Graphics view showing disk layout."""

    partitionSelected = Signal(Partition)

    def __init__(self, parent: QGraphicsView | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMinimumHeight(110)
        self.setMaximumHeight(170)

        # Style
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing, True)

        self._disk: Disk | None = None
        self._partition_items: list[PartitionRectItem] = []

    def setDisk(self, disk: Disk | None) -> None:
        """Set the disk to display."""
        self._disk = disk
        self._scene.clear()
        self._partition_items.clear()

        if disk is None:
            return

        self._draw_disk()

    def _draw_disk(self) -> None:
        """Draw the disk and its partitions."""
        if self._disk is None:
            return

        # Get available width
        width = max(self.viewport().width() - 20, 100)
        height = 70
        x_offset = 10
        y_offset = 10

        # Draw disk background
        disk_rect = self._scene.addRect(
            x_offset,
            y_offset,
            width,
            height,
            QPen(QColor(164, 182, 211), 1),
            QBrush(QColor(250, 252, 255)),
        )
        disk_rect.setZValue(0)

        # Calculate partition positions
        total_size = self._disk.size_bytes
        if total_size == 0:
            return

        current_x = x_offset
        min_width = 26
        widths = []
        for partition in self._disk.partitions:
            part_width = (partition.size_bytes / total_size) * width
            widths.append(max(part_width, min_width))

        unalloc_width = 0.0
        if self._disk.unallocated_bytes > 0:
            unalloc_width = (self._disk.unallocated_bytes / total_size) * width
            unalloc_width = max(unalloc_width, min_width)

        total_width = sum(widths) + unalloc_width
        if total_width > width:
            scale = width / total_width
            widths = [max(w * scale, 8) for w in widths]
            unalloc_width = max(unalloc_width * scale, 8) if unalloc_width else 0.0

        text_font = QFont("Segoe UI", 8)
        text_metrics = QFontMetrics(text_font)

        for partition, part_width in zip(self._disk.partitions, widths, strict=False):
            if part_width <= 0:
                continue

            # Create partition rectangle
            rect = QRectF(current_x, y_offset + 5, part_width - 2, height - 10)
            part_item = PartitionRectItem(partition, rect)
            part_item.setFlag(QGraphicsItem.ItemIsSelectable)
            self._scene.addItem(part_item)
            self._partition_items.append(part_item)

            label = partition.label or partition.mountpoint or f"Partition {partition.number}"
            size_text = humanize.naturalsize(partition.size_bytes, binary=True)
            fs_text = partition.filesystem.value

            band_height = min(max((height - 10) * 0.22, 6), 14)
            padding_x = 6
            label_item = QGraphicsTextItem(f"<b>{label}</b>")
            label_item.setFont(text_font)
            label_item.setTextWidth(max(part_width - padding_x * 2, 10))
            label_item.setPos(current_x + padding_x, y_offset + 6)
            label_item.setZValue(2)
            label_item.setDefaultTextColor(Qt.white)

            meta_item = QGraphicsTextItem(f"{fs_text} • {size_text}")
            meta_item.setFont(text_font)
            meta_item.setTextWidth(max(part_width - padding_x * 2, 10))
            meta_item.setPos(current_x + padding_x, y_offset + 6 + band_height + 4)
            meta_item.setZValue(2)
            meta_item.setDefaultTextColor(
                Qt.white if is_dark_color(part_item._base_color) else QColor(38, 38, 38)
            )

            label_height = text_metrics.height() + band_height
            meta_height = text_metrics.height() * 1.4
            if part_width >= 62 and (label_height + meta_height) < height:
                self._scene.addItem(label_item)
                self._scene.addItem(meta_item)
            elif part_width >= 46:
                label_item.setPos(current_x + padding_x, y_offset + 12)
                self._scene.addItem(label_item)

            current_x += part_width

        # Show unallocated space
        if self._disk.unallocated_bytes > 0:
            if unalloc_width > 5:
                unalloc_gradient = QLinearGradient(0, y_offset + 5, 0, y_offset + height - 5)
                unalloc_gradient.setColorAt(0.0, QColor(248, 248, 248))
                unalloc_gradient.setColorAt(1.0, QColor(232, 232, 232))
                unalloc_rect = self._scene.addRect(
                    current_x,
                    y_offset + 5,
                    unalloc_width - 2,
                    height - 10,
                    QPen(QColor(140, 140, 140), 1, Qt.DashLine),
                    QBrush(unalloc_gradient),
                )
                unalloc_rect.setZValue(1)

                size_text = humanize.naturalsize(self._disk.unallocated_bytes, binary=True)
                unalloc_label = QGraphicsTextItem(
                    f"<div align='center'><b>Unallocated</b><br>{size_text}</div>"
                )
                unalloc_label.setFont(text_font)
                unalloc_label.setDefaultTextColor(QColor(84, 94, 112))
                unalloc_label.setTextWidth(max(unalloc_width - 6, 10))
                unalloc_label.setPos(current_x + 1, y_offset + 8)
                unalloc_label.setZValue(2)
                if unalloc_width >= 48:
                    self._scene.addItem(unalloc_label)

        # Fit scene to view
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event: QGraphicsView) -> None:
        """Handle resize to redraw disk."""
        super().resizeEvent(event)
        self._draw_disk()

    def mousePressEvent(self, event: QGraphicsView) -> None:
        """Handle mouse click to select partition."""
        super().mousePressEvent(event)

        item = self.itemAt(event.pos())
        if isinstance(item, PartitionRectItem):
            self.partitionSelected.emit(item.partition)


class DiskLegendItem(QWidget):
    """Legend item showing a color swatch and label."""

    def __init__(self, text: str, meta: str, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        swatch = QFrame()
        swatch.setObjectName("legendSwatch")
        swatch.setFixedSize(16, 16)
        swatch.setStyleSheet(
            "border: 1px solid #4b5a7a; border-radius: 2px; "
            f"background: {gradient_qss(color)};"
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        label = QLabel(text)
        label.setObjectName("legendLabel")
        meta_label = QLabel(meta)
        meta_label.setObjectName("legendMeta")

        text_layout.addWidget(label)
        text_layout.addWidget(meta_label)

        layout.addWidget(swatch)
        layout.addLayout(text_layout)


class DiskLegendWidget(QWidget):
    """Legend widget for disk map."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diskLegend")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(6)

        self._meta_layout = QHBoxLayout()
        self._meta_layout.setSpacing(10)
        self._layout.addLayout(self._meta_layout)

        self._items_layout = QHBoxLayout()
        self._items_layout.setSpacing(16)
        self._layout.addLayout(self._items_layout)
        self._items_layout.addStretch()

    def _clear_layout(self, layout: QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def set_disk(self, disk: Disk | None) -> None:
        """Update legend entries based on the disk."""
        self._clear_layout(self._meta_layout)
        self._clear_layout(self._items_layout)
        self._items_layout.addStretch()

        if disk is None:
            empty_label = QLabel("No disk selected")
            empty_label.setObjectName("legendEmpty")
            self._meta_layout.addWidget(empty_label)
            self._meta_layout.addStretch()
            return

        disk_name = QLabel("Disk:")
        disk_name.setObjectName("legendTitle")
        disk_value = QLabel(disk.display_name)
        disk_value.setObjectName("legendValue")
        capacity_name = QLabel("Capacity:")
        capacity_name.setObjectName("legendTitle")
        capacity_value = QLabel(humanize.naturalsize(disk.size_bytes, binary=True))
        capacity_value.setObjectName("legendValue")

        self._meta_layout.addWidget(disk_name)
        self._meta_layout.addWidget(disk_value)
        self._meta_layout.addSpacing(12)
        self._meta_layout.addWidget(capacity_name)
        self._meta_layout.addWidget(capacity_value)

        if disk.unallocated_bytes > 0:
            unalloc_value = QLabel(humanize.naturalsize(disk.unallocated_bytes, binary=True))
            unalloc_value.setObjectName("legendValue")
            unalloc_title = QLabel("Unallocated:")
            unalloc_title.setObjectName("legendTitle")
            self._meta_layout.addSpacing(12)
            self._meta_layout.addWidget(unalloc_title)
            self._meta_layout.addWidget(unalloc_value)

        self._meta_layout.addStretch()

        for partition in disk.partitions:
            label = partition.label or partition.mountpoint or f"Partition {partition.number}"
            size_text = humanize.naturalsize(partition.size_bytes, binary=True)
            meta = f"{partition.filesystem.value} • {size_text}"
            if partition.mountpoint and partition.label:
                meta = f"{meta} • {partition.mountpoint}"
            self._items_layout.insertWidget(
                self._items_layout.count() - 1,
                DiskLegendItem(label, meta, filesystem_color(partition.filesystem)),
            )

        if disk.unallocated_bytes > 0:
            size_text = humanize.naturalsize(disk.unallocated_bytes, binary=True)
            self._items_layout.insertWidget(
                self._items_layout.count() - 1,
                DiskLegendItem("Unallocated", size_text, QColor(220, 220, 220)),
            )


class DiskMapWidget(QWidget):
    """Composite widget with disk map and legend."""

    partitionSelected = Signal(Partition)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._disk_view = DiskGraphicsView()
        self._legend = DiskLegendWidget()
        self._legend.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._disk_view.partitionSelected.connect(self.partitionSelected.emit)

        layout.addWidget(self._disk_view)
        layout.addWidget(self._legend)

    def setDisk(self, disk: Disk | None) -> None:
        """Set the disk to display in the map and legend."""
        self._disk_view.setDisk(disk)
        self._legend.set_disk(disk)

    @property
    def disk_view(self) -> DiskGraphicsView:
        """Access the underlying graphics view."""
        return self._disk_view
