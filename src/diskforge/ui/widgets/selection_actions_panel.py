"""
Selection actions panel for DiskForge.

Displays context-aware actions for the selected disk or partition.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DISK_ACTION_KEYS: tuple[str, ...] = (
    "clone_disk",
    "create_backup",
    "system_backup",
    "restore_backup",
    "initialize_disk",
    "convert_partition_style",
    "convert_disk_layout",
    "defrag_disk",
    "disk_health_check",
    "disk_speed_test",
    "bad_sector_scan",
    "surface_test",
    "wipe_device",
    "secure_erase_ssd",
)

PARTITION_ACTION_KEYS: tuple[str, ...] = (
    "clone_partition",
    "format_partition",
    "delete_partition",
    "resize_move_partition",
    "extend_partition",
    "shrink_partition",
    "merge_partitions",
    "split_partition",
    "align_4k",
    "convert_filesystem",
    "convert_partition_role",
    "edit_partition_attributes",
    "defrag_partition",
    "bitlocker_status",
    "bitlocker_enable",
    "bitlocker_disable",
)


class SelectionActionsPanel(QWidget):
    """Panel that lists actions relevant to the current selection."""

    propertiesRequested = Signal()

    def __init__(self, actions: dict[str, QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions = actions
        self._selection_label = QLabel("No selection")
        self._selection_label.setObjectName("selectionActionsSubtitle")

        self._properties_button = QPushButton("Properties")
        self._properties_button.setObjectName("selectionPropertiesButton")
        self._properties_button.setEnabled(False)
        self._properties_button.clicked.connect(self.propertiesRequested)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self._selection_label)
        header_layout.addStretch()
        header_layout.addWidget(self._properties_button)

        self._actions_container = QWidget()
        self._actions_layout = QVBoxLayout(self._actions_container)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(6)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setWidget(self._actions_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self._scroll_area)

        self._set_placeholder("Select a disk or partition to view actions.")

    def set_selection(self, selection_type: str | None, label: str | None = None) -> None:
        """Update the panel based on the current selection."""
        if selection_type == "disk":
            self._selection_label.setText(label or "Disk selected")
            self._properties_button.setEnabled(True)
            self._populate_actions(DISK_ACTION_KEYS)
            return

        if selection_type == "partition":
            self._selection_label.setText(label or "Partition selected")
            self._properties_button.setEnabled(True)
            self._populate_actions(PARTITION_ACTION_KEYS)
            return

        self._selection_label.setText("No selection")
        self._properties_button.setEnabled(False)
        self._set_placeholder("Select a disk or partition to view actions.")

    def _populate_actions(self, action_keys: tuple[str, ...]) -> None:
        self._clear_actions()
        for action_key in action_keys:
            action = self._actions.get(action_key)
            if action is None:
                continue
            button = QToolButton()
            button.setObjectName("selectionActionButton")
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setIcon(action.icon())
            button.setText(action.text())
            button.setToolTip(action.statusTip() or action.toolTip())
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(action.trigger)
            self._actions_layout.addWidget(button)
        self._actions_layout.addStretch()

    def _set_placeholder(self, message: str) -> None:
        self._clear_actions()
        placeholder = QLabel(message)
        placeholder.setWordWrap(True)
        placeholder.setObjectName("selectionActionsPlaceholder")
        self._actions_layout.addWidget(placeholder)
        self._actions_layout.addStretch()

    def _clear_actions(self) -> None:
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
