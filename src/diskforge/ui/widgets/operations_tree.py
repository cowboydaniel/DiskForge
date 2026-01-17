"""
DiskForge operations navigation tree.

AOMEI-style navigation categories with actions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView, QStyle, QWidget


class OperationsTreeWidget(QTreeView):
    """Navigation tree for quick operations."""

    def __init__(self, actions: dict[str, QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._actions = actions
        self.setHeaderHidden(True)
        self.setSelectionBehavior(QTreeView.SelectRows)
        self.setUniformRowHeights(True)
        self.setEditTriggers(QTreeView.NoEditTriggers)
        self.setRootIsDecorated(True)
        self.setExpandsOnDoubleClick(True)

        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self._build_tree()
        self.expandAll()

        self.activated.connect(self._handle_activation)

    def _icon(self, theme_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        icon = QIcon.fromTheme(theme_name)
        if icon.isNull():
            icon = self.style().standardIcon(fallback)
        return icon

    def _build_tree(self) -> None:
        self._model.clear()

        wizard_icon = self._icon("applications-system", QStyle.SP_ComputerIcon)
        partition_icon = self._icon("drive-harddisk", QStyle.SP_DriveHDIcon)
        backup_icon = self._icon("document-save", QStyle.SP_DialogSaveButton)
        tools_icon = self._icon("preferences-system", QStyle.SP_ToolBarHorizontalExtensionButton)
        cleanup_icon = self._icon("user-trash", QStyle.SP_TrashIcon)

        self._add_category(
            "Wizards",
            wizard_icon,
            [
                (
                    "Copy Disk Wizard (Advanced)",
                    "clone_disk",
                    self._icon("drive-harddisk", QStyle.SP_DriveHDIcon),
                ),
                (
                    "Copy Partition Wizard (Advanced)",
                    "clone_partition",
                    self._icon("drive-removable-media", QStyle.SP_DriveFDIcon),
                ),
            ],
        )

        self._add_category(
            "Partition Operations",
            partition_icon,
            [
                ("Create Partition", "create_partition", self._icon("list-add", QStyle.SP_FileDialogNewFolder)),
                (
                    "Format Partition",
                    "format_partition",
                    self._icon("edit-clear", QStyle.SP_DialogResetButton),
                ),
                ("Delete Partition", "delete_partition", self._icon("edit-delete", QStyle.SP_TrashIcon)),
                ("Resize/Move", "resize_move_partition", self._icon("transform-move", QStyle.SP_ArrowUp)),
                ("Extend", "extend_partition", self._icon("zoom-in", QStyle.SP_ArrowUp)),
                ("Shrink", "shrink_partition", self._icon("zoom-out", QStyle.SP_ArrowDown)),
                ("Allocate Free Space", "allocate_free_space", self._icon("view-refresh", QStyle.SP_BrowserReload)),
                ("One-Click Adjust Space", "one_click_adjust_space", self._icon("system-run", QStyle.SP_MediaPlay)),
                ("Merge", "merge_partitions", self._icon("list-add", QStyle.SP_FileDialogNewFolder)),
                ("Split", "split_partition", self._icon("list-remove", QStyle.SP_TrashIcon)),
                ("Align 4K", "align_4k", self._icon("view-refresh", QStyle.SP_BrowserReload)),
                ("Convert Filesystem (NTFS/FAT32)", "convert_filesystem", self._icon("edit-clear", QStyle.SP_DialogResetButton)),
                ("Convert Primary/Logical", "convert_partition_role", self._icon("object-flip-horizontal", QStyle.SP_ArrowRight)),
                ("Edit Partition Attributes", "edit_partition_attributes", self._icon("document-edit", QStyle.SP_FileDialogDetailedView)),
            ],
        )

        self._add_category(
            "Dynamic Volume Operations",
            partition_icon,
            [
                ("Resize/Move Dynamic Volume", "resize_move_dynamic_volume", self._icon("transform-move", QStyle.SP_ArrowUp)),
                ("Extend Dynamic Volume", "extend_dynamic_volume", self._icon("zoom-in", QStyle.SP_ArrowUp)),
                ("Shrink Dynamic Volume", "shrink_dynamic_volume", self._icon("zoom-out", QStyle.SP_ArrowDown)),
            ],
        )

        self._add_category(
            "Backup & Restore",
            backup_icon,
            [
                (
                    "Disk Backup (Advanced)",
                    "create_backup",
                    self._icon("document-save", QStyle.SP_DialogSaveButton),
                ),
                ("Disk Restore", "restore_backup", self._icon("document-open", QStyle.SP_DirOpenIcon)),
            ],
        )

        self._add_category(
            "Storage Cleanup",
            cleanup_icon,
            [
                ("Free Up Space", "free_space", self._icon("view-refresh", QStyle.SP_BrowserReload)),
                ("Junk File Cleanup", "junk_cleanup", self._icon("edit-delete", QStyle.SP_TrashIcon)),
                ("Large File Finder", "large_files", self._icon("document-open", QStyle.SP_FileDialogDetailedView)),
                ("Duplicate File Finder", "duplicate_files", self._icon("edit-copy", QStyle.SP_FileDialogContentsView)),
                ("Move Applications", "move_applications", self._icon("transform-move", QStyle.SP_ArrowUp)),
            ],
        )

        self._add_category(
            "Tools",
            tools_icon,
            [
                ("Refresh", "refresh", self._icon("view-refresh", QStyle.SP_BrowserReload)),
                ("Defragment Disk", "defrag_disk", self._icon("view-refresh", QStyle.SP_BrowserReload)),
                ("Defragment Partition", "defrag_partition", self._icon("view-refresh", QStyle.SP_BrowserReload)),
                ("Wipe/Secure Erase", "wipe_device", self._icon("edit-delete", QStyle.SP_TrashIcon)),
                ("SSD Secure Erase", "secure_erase_ssd", self._icon("edit-delete", QStyle.SP_TrashIcon)),
                ("System Disk Wipe", "wipe_system_disk", self._icon("edit-delete", QStyle.SP_TrashIcon)),
                ("Partition Recovery", "partition_recovery", self._icon("edit-undo", QStyle.SP_ArrowBack)),
                ("File Recovery", "file_recovery", self._icon("document-open", QStyle.SP_DirOpenIcon)),
                ("Shred Files/Folders", "shred_files", self._icon("edit-delete", QStyle.SP_TrashIcon)),
                ("Convert MBR/GPT", "convert_partition_style", self._icon("object-flip-horizontal", QStyle.SP_ArrowRight)),
                ("Convert System Disk MBR/GPT", "convert_system_partition_style", self._icon("object-flip-horizontal", QStyle.SP_ArrowRight)),
                ("Convert Dynamic/Basic", "convert_disk_layout", self._icon("object-flip-horizontal", QStyle.SP_ArrowRight)),
                ("Quick Partition", "quick_partition", self._icon("list-add", QStyle.SP_FileDialogNewFolder)),
                ("Initialize Disk", "initialize_disk", self._icon("drive-harddisk", QStyle.SP_DriveHDIcon)),
                ("OS/System Migration", "migrate_system", self._icon("system-run", QStyle.SP_MediaPlay)),
                (
                    "Make Bootable Media",
                    "rescue_media",
                    self._icon("media-optical", QStyle.SP_DriveCDIcon),
                ),
                (
                    "Toggle Danger Mode",
                    "danger_mode",
                    self._icon("dialog-warning", QStyle.SP_MessageBoxWarning),
                ),
                ("About DiskForge", "about", self._icon("help-about", QStyle.SP_MessageBoxInformation)),
                ("Exit", "exit", self._icon("application-exit", QStyle.SP_DialogCloseButton)),
            ],
        )

    def _add_category(
        self,
        label: str,
        icon: QIcon,
        children: list[tuple[str, str, QIcon]],
    ) -> None:
        category_item = QStandardItem(icon, label)
        category_item.setEditable(False)
        category_item.setSelectable(False)
        for child_label, action_key, child_icon in children:
            child_item = QStandardItem(child_icon, child_label)
            child_item.setEditable(False)
            child_item.setData(action_key, Qt.UserRole)
            category_item.appendRow(child_item)
        self._model.appendRow(category_item)

    def _handle_activation(self, index) -> None:
        if not index.isValid():
            return
        item = self._model.itemFromIndex(index)
        action_key = item.data(Qt.UserRole)
        if not action_key:
            return
        action = self._actions.get(action_key)
        if action is not None:
            action.trigger()
