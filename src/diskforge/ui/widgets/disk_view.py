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
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QPainter, QFontMetrics
import humanize

from diskforge.core.models import Disk, Partition, FileSystem


FILESYSTEM_COLORS = {
    FileSystem.NTFS: QColor(0, 120, 215),
    FileSystem.FAT32: QColor(255, 185, 0),
    FileSystem.EXFAT: QColor(255, 185, 0),
    FileSystem.EXT4: QColor(76, 175, 80),
    FileSystem.EXT3: QColor(76, 175, 80),
    FileSystem.XFS: QColor(156, 39, 176),
    FileSystem.BTRFS: QColor(255, 152, 0),
    FileSystem.SWAP: QColor(158, 158, 158),
    FileSystem.UNKNOWN: QColor(200, 200, 200),
}


def filesystem_color(filesystem: FileSystem) -> QColor:
    """Return the color associated with a filesystem."""
    return FILESYSTEM_COLORS.get(filesystem, QColor(200, 200, 200))


def is_dark_color(color: QColor) -> bool:
    """Determine if a color is dark for contrast."""
    return (color.redF() * 0.299 + color.greenF() * 0.587 + color.blueF() * 0.114) < 0.5


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
        color = filesystem_color(partition.filesystem)
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(40, 40, 40), 1))

        # Hover effects
        self.setAcceptHoverEvents(True)
        self._normal_brush = QBrush(color)
        self._hover_brush = QBrush(color.lighter(120))

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
        self.setBrush(self._hover_brush)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsItem.GraphicsItemChange) -> None:
        self.setBrush(self._normal_brush)
        super().hoverLeaveEvent(event)


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
            QPen(QColor(70, 70, 70), 1),
            QBrush(QColor(247, 247, 247)),
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
            label_text = f"<div align='center'><b>{label}</b><br>{fs_text} • {size_text}</div>"

            text_item = QGraphicsTextItem()
            text_item.setHtml(label_text)
            text_item.setFont(text_font)
            text_item.setTextWidth(max(part_width - 6, 10))
            text_item.setPos(current_x + 1, y_offset + 8)
            text_item.setZValue(2)

            if is_dark_color(part_item.brush().color()):
                text_item.setDefaultTextColor(Qt.white)
            else:
                text_item.setDefaultTextColor(QColor(30, 30, 30))

            text_height = text_metrics.height() * 2.2
            if part_width >= 48 and text_height < height:
                self._scene.addItem(text_item)

            current_x += part_width

        # Show unallocated space
        if self._disk.unallocated_bytes > 0:
            if unalloc_width > 5:
                unalloc_rect = self._scene.addRect(
                    current_x,
                    y_offset + 5,
                    unalloc_width - 2,
                    height - 10,
                    QPen(QColor(120, 120, 120), 1, Qt.DashLine),
                    QBrush(QColor(245, 245, 245)),
                )
                unalloc_rect.setZValue(1)

                size_text = humanize.naturalsize(self._disk.unallocated_bytes, binary=True)
                unalloc_label = QGraphicsTextItem(
                    f"<div align='center'><b>Unallocated</b><br>{size_text}</div>"
                )
                unalloc_label.setFont(text_font)
                unalloc_label.setDefaultTextColor(QColor(80, 80, 80))
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

    def __init__(self, text: str, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        swatch = QFrame()
        swatch.setFixedSize(14, 14)
        swatch.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid #444; border-radius: 2px;"
        )

        label = QLabel(text)
        label.setObjectName("legendLabel")

        layout.addWidget(swatch)
        layout.addWidget(label)


class DiskLegendWidget(QWidget):
    """Legend widget for disk map."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(14)
        self._layout.addStretch()

    def set_disk(self, disk: Disk | None) -> None:
        """Update legend entries based on the disk."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if disk is None:
            empty_label = QLabel("No disk selected")
            empty_label.setObjectName("legendEmpty")
            self._layout.addWidget(empty_label)
            self._layout.addStretch()
            return

        filesystems = []
        for partition in disk.partitions:
            if partition.filesystem not in filesystems:
                filesystems.append(partition.filesystem)

        for fs in filesystems:
            self._layout.addWidget(DiskLegendItem(fs.value, filesystem_color(fs)))

        if disk.unallocated_bytes > 0:
            self._layout.addWidget(DiskLegendItem("Unallocated", QColor(235, 235, 235)))

        self._layout.addStretch()


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
