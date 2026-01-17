"""
DiskForge Disk Model.

Qt models for displaying disk and partition information.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex, Signal
from PySide6.QtGui import QColor, QBrush
import humanize

from diskforge.core.models import Disk, DiskInventory, Partition


class DiskTreeItem:
    """Tree item for disk/partition hierarchy."""

    def __init__(
        self,
        data: Disk | Partition | None = None,
        parent: DiskTreeItem | None = None,
    ) -> None:
        self._data = data
        self._parent = parent
        self._children: list[DiskTreeItem] = []

    def appendChild(self, child: DiskTreeItem) -> None:
        self._children.append(child)

    def child(self, row: int) -> DiskTreeItem | None:
        if 0 <= row < len(self._children):
            return self._children[row]
        return None

    def childCount(self) -> int:
        return len(self._children)

    def row(self) -> int:
        if self._parent:
            return self._parent._children.index(self)
        return 0

    def columnCount(self) -> int:
        return 11

    def data(self, column: int) -> Any:
        if self._data is None:
            return None

        if isinstance(self._data, Disk):
            disk = self._data
            columns = [
                disk.device_path,
                disk.model[:30] if disk.model else "Unknown",
                humanize.naturalsize(disk.size_bytes, binary=True),
                "",
                "",
                disk.disk_type.name,
                disk.smart_info.status_text if disk.smart_info else "Unknown",
                "",
                disk.partition_style.name,
                "",
                "SYSTEM" if disk.is_system_disk else "",
            ]
        else:
            part = self._data
            alignment_status = ""
            if self._parent and isinstance(self._parent._data, Disk):
                disk = self._parent._data
                if disk.sector_size:
                    alignment_sectors = max(1, 4096 // disk.sector_size)
                    aligned = part.start_sector % alignment_sectors == 0
                    alignment_status = "4K Aligned" if aligned else "Unaligned"
            status_bits = []
            if part.is_mounted:
                status_bits.append("Mounted")
            if part.is_system:
                status_bits.append("System")
            if part.is_boot:
                status_bits.append("Boot")
            status_text = ", ".join(status_bits)
            columns = [
                part.device_path,
                part.label or "",
                humanize.naturalsize(part.size_bytes, binary=True),
                humanize.naturalsize(part.used_space_bytes, binary=True)
                if part.used_space_bytes is not None
                else "",
                humanize.naturalsize(part.free_space_bytes, binary=True)
                if part.free_space_bytes is not None
                else "",
                part.filesystem.value,
                status_text,
                alignment_status,
                "",
                part.mountpoint or "",
                ", ".join(f.name for f in part.flags[:2]) if part.flags else "",
            ]

        return columns[column] if column < len(columns) else None

    def parent(self) -> DiskTreeItem | None:
        return self._parent

    def itemData(self) -> Disk | Partition | None:
        return self._data

    def isDisk(self) -> bool:
        return isinstance(self._data, Disk)

    def isPartition(self) -> bool:
        return isinstance(self._data, Partition)


class DiskModel(QAbstractItemModel):
    """Qt model for disk inventory tree view."""

    inventoryChanged = Signal()

    HEADERS = [
        "Device",
        "Model/Label",
        "Size",
        "Used Space",
        "Free Space",
        "Type/FS",
        "Status",
        "Alignment",
        "Style",
        "Mount",
        "Flags",
    ]

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._root = DiskTreeItem()
        self._inventory: DiskInventory | None = None

    def setInventory(self, inventory: DiskInventory) -> None:
        """Set the disk inventory to display."""
        self.beginResetModel()

        self._inventory = inventory
        self._root = DiskTreeItem()

        for disk in inventory.disks:
            disk_item = DiskTreeItem(disk, self._root)
            self._root.appendChild(disk_item)

            for partition in disk.partitions:
                part_item = DiskTreeItem(partition, disk_item)
                disk_item.appendChild(part_item)

        self.endResetModel()
        self.inventoryChanged.emit()

    def getInventory(self) -> DiskInventory | None:
        """Get the current inventory."""
        return self._inventory

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parent_item = self._root
        else:
            parent_item = parent.internalPointer()

        return parent_item.childCount()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        item: DiskTreeItem = index.internalPointer()

        if role == Qt.DisplayRole:
            return item.data(index.column())

        if role == Qt.BackgroundRole:
            if item.isDisk():
                data = item.itemData()
                if isinstance(data, Disk) and data.is_system_disk:
                    return QBrush(QColor(255, 255, 200))

        if role == Qt.ForegroundRole:
            if item.isPartition():
                data = item.itemData()
                if isinstance(data, Partition) and data.is_mounted:
                    return QBrush(QColor(0, 100, 0))

        if role == Qt.UserRole:
            return item.itemData()

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section] if section < len(self.HEADERS) else None
        return None

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parent_item = self._root
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)

        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()

        child_item: DiskTreeItem = index.internalPointer()
        parent_item = child_item.parent()

        if parent_item is None or parent_item == self._root:
            return QModelIndex()

        return self.createIndex(parent_item.row(), 0, parent_item)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def getItemAtIndex(self, index: QModelIndex) -> Disk | Partition | None:
        """Get the disk or partition at the given index."""
        if not index.isValid():
            return None
        item: DiskTreeItem = index.internalPointer()
        return item.itemData()


class PartitionModel(QAbstractItemModel):
    """Flat model for partition list (for specific disk)."""

    HEADERS = ["#", "Device", "Size", "Filesystem", "Label", "Mount", "Flags"]

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._partitions: list[Partition] = []

    def setPartitions(self, partitions: list[Partition]) -> None:
        """Set the partitions to display."""
        self.beginResetModel()
        self._partitions = partitions
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._partitions)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._partitions):
            return None

        partition = self._partitions[index.row()]

        if role == Qt.DisplayRole:
            columns = [
                str(partition.number),
                partition.device_path,
                humanize.naturalsize(partition.size_bytes, binary=True),
                partition.filesystem.value,
                partition.label or "",
                partition.mountpoint or "",
                ", ".join(f.name for f in partition.flags[:2]) if partition.flags else "",
            ]
            return columns[index.column()] if index.column() < len(columns) else None

        if role == Qt.UserRole:
            return partition

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section] if section < len(self.HEADERS) else None
        return None

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if parent.isValid() or not self.hasIndex(row, column, parent):
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, index: QModelIndex) -> QModelIndex:
        return QModelIndex()

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable
