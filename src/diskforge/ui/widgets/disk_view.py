"""
DiskForge Disk Graphics View.

Visual representation of disk layout.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsItem,
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QPainter
import humanize

from diskforge.core.models import Disk, Partition, FileSystem


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
        fs_colors = {
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

        color = fs_colors.get(partition.filesystem, QColor(200, 200, 200))
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.black, 1))

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
        self.setMinimumHeight(100)
        self.setMaximumHeight(150)

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
        width = self.width() - 20
        height = 80
        x_offset = 10
        y_offset = 10

        # Draw disk background
        disk_rect = self._scene.addRect(
            x_offset,
            y_offset,
            width,
            height,
            QPen(Qt.black, 2),
            QBrush(QColor(240, 240, 240)),
        )

        # Calculate partition positions
        total_size = self._disk.size_bytes
        if total_size == 0:
            return

        current_x = x_offset

        for partition in self._disk.partitions:
            # Calculate width proportional to size
            part_width = (partition.size_bytes / total_size) * width
            part_width = max(part_width, 20)  # Minimum width

            # Create partition rectangle
            rect = QRectF(current_x, y_offset + 5, part_width - 2, height - 10)
            part_item = PartitionRectItem(partition, rect)
            part_item.setFlag(QGraphicsItem.ItemIsSelectable)
            self._scene.addItem(part_item)
            self._partition_items.append(part_item)

            # Add label
            label_text = f"#{partition.number}"
            if partition.label:
                label_text = partition.label[:8]
            elif partition.mountpoint:
                label_text = partition.mountpoint[:8]

            label = QGraphicsTextItem(label_text)
            label.setFont(QFont("Arial", 8))
            label.setPos(current_x + 2, y_offset + 5)
            self._scene.addItem(label)

            # Add size label
            size_text = humanize.naturalsize(partition.size_bytes, binary=True)
            size_label = QGraphicsTextItem(size_text)
            size_label.setFont(QFont("Arial", 7))
            size_label.setPos(current_x + 2, y_offset + height - 25)
            self._scene.addItem(size_label)

            current_x += part_width

        # Show unallocated space
        if self._disk.unallocated_bytes > 0:
            unalloc_width = (self._disk.unallocated_bytes / total_size) * width
            if unalloc_width > 5:
                unalloc_rect = self._scene.addRect(
                    current_x,
                    y_offset + 5,
                    unalloc_width - 2,
                    height - 10,
                    QPen(Qt.gray, 1, Qt.DashLine),
                    QBrush(Qt.NoBrush),
                )

                unalloc_label = QGraphicsTextItem("Unallocated")
                unalloc_label.setFont(QFont("Arial", 8))
                unalloc_label.setDefaultTextColor(Qt.gray)
                unalloc_label.setPos(current_x + 2, y_offset + height // 2 - 10)
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
