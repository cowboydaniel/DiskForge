"""Ribbon-style command area for the DiskForge UI."""

from __future__ import annotations

from typing import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class RibbonWidget(QFrame):
    """AOMEI-style ribbon with tabs and grouped actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ribbon")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("ribbonTabs")
        self._tabs.setUsesScrollButtons(True)

        layout.addWidget(self._tabs)

    def add_tab(self, title: str, groups: Sequence[tuple[str, Iterable[QAction]]]) -> None:
        """Add a tab with action groups."""
        tab = QWidget()
        tab_layout = QHBoxLayout(tab)
        tab_layout.setContentsMargins(6, 6, 6, 6)
        tab_layout.setSpacing(10)

        for group_title, actions in groups:
            group_box = QGroupBox(group_title)
            group_layout = QVBoxLayout(group_box)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setSpacing(6)

            for action in actions:
                button = QToolButton()
                button.setDefaultAction(action)
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setAutoRaise(True)
                button.setMinimumWidth(120)
                group_layout.addWidget(button)

            group_layout.addStretch()
            tab_layout.addWidget(group_box)

        tab_layout.addStretch()
        self._tabs.addTab(tab, title)
