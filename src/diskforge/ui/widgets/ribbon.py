"""Ribbon-style command area for the DiskForge UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QMenu,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from diskforge.ui.assets import DiskForgeIcons


class RibbonWidget(QFrame):
    """AOMEI-style ribbon with tabs and grouped actions."""

    LARGE_ICON_SIZE = DiskForgeIcons.RIBBON_SIZE
    SMALL_ICON_SIZE = DiskForgeIcons.MENU_SIZE
    LARGE_MIN_WIDTH = 96
    SMALL_MIN_WIDTH = 140

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

    def add_tab(self, title: str, groups: Sequence["RibbonGroup"]) -> None:
        """Add a tab with action groups."""
        tab = QWidget()
        tab_layout = QHBoxLayout(tab)
        tab_layout.setContentsMargins(6, 6, 6, 6)
        tab_layout.setSpacing(10)

        for group in groups:
            group_box = QGroupBox(group.title)
            group_layout = QGridLayout(group_box)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setHorizontalSpacing(10)
            group_layout.setVerticalSpacing(4)

            max_rows = max((len(column) for column in group.columns), default=1)
            for column_index, column in enumerate(group.columns):
                if len(column) == 1 and column[0].size == "large":
                    button = self._build_button(column[0])
                    group_layout.addWidget(button, 0, column_index, max_rows, 1)
                    continue

                for row_index, item in enumerate(column):
                    button = self._build_button(item)
                    group_layout.addWidget(button, row_index, column_index)

            group_layout.setRowStretch(max_rows, 1)
            tab_layout.addWidget(group_box)

            if group.separator_after:
                separator = QFrame()
                separator.setFrameShape(QFrame.VLine)
                separator.setFrameShadow(QFrame.Sunken)
                tab_layout.addWidget(separator)

        tab_layout.addStretch()
        self._tabs.addTab(tab, title)

    def _build_button(self, item: "RibbonButton") -> QToolButton:
        button = QToolButton()
        button.setDefaultAction(item.action)
        button.setAutoRaise(True)

        if item.size == "small":
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setIconSize(self.SMALL_ICON_SIZE)
            button.setMinimumWidth(item.min_width or self.SMALL_MIN_WIDTH)
        else:
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIconSize(self.LARGE_ICON_SIZE)
            button.setMinimumWidth(item.min_width or self.LARGE_MIN_WIDTH)

        if item.split_actions:
            menu = QMenu(button)
            for action in item.split_actions:
                menu.addAction(action)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.MenuButtonPopup)

        return button


@dataclass(frozen=True)
class RibbonButton:
    action: QAction
    size: str = "large"
    split_actions: Sequence[QAction] | None = None
    min_width: int | None = None


@dataclass(frozen=True)
class RibbonGroup:
    title: str
    columns: Sequence[Sequence[RibbonButton]]
    separator_after: bool = False
