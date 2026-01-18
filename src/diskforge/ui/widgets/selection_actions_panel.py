"""
Selection actions panel for DiskForge.

Displays context-aware actions for the selected disk or partition.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

@dataclass(frozen=True)
class ActionEntry:
    """Config for a selection action button."""

    label: str
    disk_action: str | None = None
    partition_action: str | None = None
    requires_selection: bool = True


class SelectionActionsPanel(QWidget):
    """Panel that lists actions relevant to the current selection."""

    propertiesRequested = Signal()

    def __init__(self, actions: dict[str, QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions = actions
        self._selection_type: str | None = None

        self._title_label = QLabel("Actions")
        self._title_label.setObjectName("sectionTitle")

        self._selection_label = QLabel("Selected: None")
        self._selection_label.setObjectName("selectionActionsSubtitle")

        self._actions_container = QWidget()
        self._actions_layout = QVBoxLayout(self._actions_container)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(6)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("selectionActionsScroll")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setWidget(self._actions_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title_label)
        layout.addWidget(self._selection_label)
        layout.addWidget(self._scroll_area)

        self._action_entries = self._build_action_entries()
        self._action_buttons: dict[str, QToolButton] = {}
        self._build_action_buttons()
        self._update_action_states()

    def set_selection(self, selection_type: str | None, label: str | None = None) -> None:
        """Update the panel based on the current selection."""
        self._selection_type = selection_type
        if selection_type:
            self._selection_label.setText(f"Selected: {label or selection_type.title()}")
        else:
            self._selection_label.setText("Selected: None")
        self._update_action_states()

    def _build_action_entries(self) -> tuple[ActionEntry, ...]:
        return (
            ActionEntry("Resize/Move", partition_action="resize_move_partition"),
            ActionEntry("Split", partition_action="split_partition"),
            ActionEntry("Format", partition_action="format_partition"),
            ActionEntry("Delete", partition_action="delete_partition"),
            ActionEntry("Wipe", disk_action="wipe_device", partition_action="wipe_device"),
            ActionEntry("Clone", disk_action="clone_disk", partition_action="clone_partition"),
            ActionEntry("Check", disk_action="disk_health_check", partition_action="defrag_partition"),
            ActionEntry("Properties", requires_selection=True),
        )

    def _build_action_buttons(self) -> None:
        for entry in self._action_entries:
            button = QToolButton()
            button.setObjectName("selectionActionButton")
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setText(entry.label)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False, key=entry.label: self._trigger_action(key))
            self._actions_layout.addWidget(button)
            self._action_buttons[entry.label] = button
        self._actions_layout.addStretch()

    def _update_action_states(self) -> None:
        for entry in self._action_entries:
            button = self._action_buttons.get(entry.label)
            if not button:
                continue
            action_key = self._resolve_action_key(entry)
            action = self._actions.get(action_key) if action_key else None
            if entry.label == "Properties":
                about_action = self._actions.get("about")
                button.setIcon(about_action.icon() if about_action else QIcon())
                button.setToolTip("View properties for the current selection.")
                enabled = bool(self._selection_type)
            else:
                if action:
                    button.setIcon(action.icon())
                    button.setToolTip(action.statusTip() or action.toolTip())
                else:
                    button.setIcon(QIcon())
                    button.setToolTip("")
                enabled = bool(self._selection_type) and action_key is not None
            button.setEnabled(enabled)

    def _resolve_action_key(self, entry: ActionEntry) -> str | None:
        if self._selection_type == "disk":
            return entry.disk_action
        if self._selection_type == "partition":
            return entry.partition_action
        return None

    def _trigger_action(self, label: str) -> None:
        entry = next((item for item in self._action_entries if item.label == label), None)
        if entry is None:
            return
        if label == "Properties":
            if self._selection_type:
                self.propertiesRequested.emit()
            return
        action_key = self._resolve_action_key(entry)
        action = self._actions.get(action_key) if action_key else None
        if action and action.isEnabled():
            action.trigger()
