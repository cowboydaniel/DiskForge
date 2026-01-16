"""
DiskForge Main Window.

The main application window with disk tree, actions, and job queue.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTreeView,
    QTableView,
    QToolBar,
    QStatusBar,
    QLabel,
    QMessageBox,
    QFileDialog,
    QMenu,
    QMenuBar,
    QGroupBox,
    QComboBox,
    QPushButton,
    QInputDialog,
    QHeaderView,
    QFrame,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Slot, QModelIndex
from PySide6.QtGui import QAction, QIcon
import humanize

from diskforge import __version__
from diskforge.core.models import Disk, FileSystem, Partition
from diskforge.core.safety import DangerMode
from diskforge.core.session import Session
from diskforge.ui.models.disk_model import DiskModel
from diskforge.ui.models.job_model import JobModel
from diskforge.ui.theme import aomei_qss
from diskforge.ui.widgets.confirmation_dialog import ConfirmationDialog
from diskforge.ui.widgets.disk_view import DiskGraphicsView
from diskforge.ui.widgets.progress_widget import ProgressWidget


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session

        self.setWindowTitle(f"DiskForge v{__version__}")
        self.setMinimumSize(1000, 700)

        # Models
        self._disk_model = DiskModel(self)
        self._job_model = JobModel(session.job_runner, self)

        # Set up UI
        self._apply_aomei_theme()
        self._setup_menubar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_statusbar()
        self._update_danger_mode_indicator()

        # Refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_inventory)
        self._refresh_timer.start(session.config.ui.refresh_interval_ms)

        # Initial load
        self._refresh_inventory()

    def _setup_menubar(self) -> None:
        """Set up the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        refresh_action = QAction("&Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_inventory)
        file_menu.addAction(refresh_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Operations menu
        ops_menu = menubar.addMenu("&Operations")

        clone_disk_action = QAction("Clone &Disk...", self)
        clone_disk_action.triggered.connect(self._on_clone_disk)
        ops_menu.addAction(clone_disk_action)

        clone_part_action = QAction("Clone &Partition...", self)
        clone_part_action.triggered.connect(self._on_clone_partition)
        ops_menu.addAction(clone_part_action)

        ops_menu.addSeparator()

        backup_action = QAction("Create &Backup...", self)
        backup_action.triggered.connect(self._on_create_backup)
        ops_menu.addAction(backup_action)

        restore_action = QAction("&Restore Backup...", self)
        restore_action.triggered.connect(self._on_restore_backup)
        ops_menu.addAction(restore_action)

        ops_menu.addSeparator()

        rescue_action = QAction("Create &Rescue Media...", self)
        rescue_action.triggered.connect(self._on_create_rescue)
        ops_menu.addAction(rescue_action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        danger_mode_action = QAction("Toggle &Danger Mode", self)
        danger_mode_action.triggered.connect(self._toggle_danger_mode)
        tools_menu.addAction(danger_mode_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self) -> None:
        """Set up the toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Refresh button
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._refresh_inventory)
        toolbar.addAction(refresh_action)

        toolbar.addSeparator()

        # Quick actions
        create_part_action = QAction("Create Partition", self)
        create_part_action.triggered.connect(self._on_create_partition)
        toolbar.addAction(create_part_action)

        format_action = QAction("Format", self)
        format_action.triggered.connect(self._on_format_partition)
        toolbar.addAction(format_action)

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self._on_delete_partition)
        toolbar.addAction(delete_action)

    def _setup_central_widget(self) -> None:
        """Set up the central widget."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header_bar = QFrame()
        header_bar.setObjectName("headerBar")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)

        title_block = QVBoxLayout()
        title_label = QLabel("DiskForge")
        title_label.setObjectName("appTitle")
        subtitle_label = QLabel("Disk management workspace")
        subtitle_label.setObjectName("appSubtitle")
        title_block.addWidget(title_label)
        title_block.addWidget(subtitle_label)
        title_block.setSpacing(2)

        header_layout.addLayout(title_block)
        header_layout.addStretch()

        self._danger_label = QLabel("SAFE MODE")
        self._danger_label.setObjectName("modeBadge")
        self._danger_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        header_layout.addWidget(self._danger_label)

        main_layout.addWidget(header_bar)

        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_layout.setSpacing(8)

        sidebar_title = QLabel("Operations")
        sidebar_title.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(sidebar_title)

        def add_sidebar_button(text: str, slot: Any, primary: bool = False) -> None:
            button = QPushButton(text)
            if primary:
                button.setObjectName("primaryAction")
            button.clicked.connect(slot)
            sidebar_layout.addWidget(button)

        add_sidebar_button("Refresh Inventory", self._refresh_inventory, primary=True)
        add_sidebar_button("Create Partition", self._on_create_partition)
        add_sidebar_button("Format Partition", self._on_format_partition)
        add_sidebar_button("Delete Partition", self._on_delete_partition)
        add_sidebar_button("Clone Disk", self._on_clone_disk)
        add_sidebar_button("Clone Partition", self._on_clone_partition)
        add_sidebar_button("Create Backup", self._on_create_backup)
        add_sidebar_button("Restore Backup", self._on_restore_backup)
        add_sidebar_button("Create Rescue Media", self._on_create_rescue)
        add_sidebar_button("Toggle Danger Mode", self._toggle_danger_mode)

        sidebar_layout.addStretch()
        splitter.addWidget(sidebar)

        # Left panel - disk tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        disk_group = QGroupBox("Disks and Partitions")
        disk_layout = QVBoxLayout(disk_group)

        self._disk_tree = QTreeView()
        self._disk_tree.setModel(self._disk_model)
        self._disk_tree.setSelectionBehavior(QTreeView.SelectRows)
        self._disk_tree.setAlternatingRowColors(True)
        self._disk_tree.selectionModel().selectionChanged.connect(self._on_disk_selection_changed)
        self._disk_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._disk_tree.customContextMenuRequested.connect(self._show_context_menu)

        # Set column widths
        header = self._disk_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        disk_layout.addWidget(self._disk_tree)
        left_layout.addWidget(disk_group)

        splitter.addWidget(left_panel)

        # Right panel - details and progress
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Disk visualization
        viz_group = QGroupBox("Disk Layout")
        viz_layout = QVBoxLayout(viz_group)
        self._disk_view = DiskGraphicsView()
        self._disk_view.partitionSelected.connect(self._on_partition_selected)
        viz_layout.addWidget(self._disk_view)
        right_layout.addWidget(viz_group)

        # Details panel
        details_group = QGroupBox("Details")
        details_layout = QVBoxLayout(details_group)
        self._details_label = QLabel("Select a disk or partition to view details")
        self._details_label.setWordWrap(True)
        details_layout.addWidget(self._details_label)
        right_layout.addWidget(details_group)

        # Progress panel
        progress_group = QGroupBox("Operation Progress")
        progress_layout = QVBoxLayout(progress_group)
        self._progress_widget = ProgressWidget()
        self._progress_widget.cancelRequested.connect(self._on_cancel_job)
        self._progress_widget.pauseRequested.connect(self._on_pause_job)
        self._progress_widget.resumeRequested.connect(self._on_resume_job)
        progress_layout.addWidget(self._progress_widget)
        right_layout.addWidget(progress_group)

        # Job queue
        job_group = QGroupBox("Job Queue")
        job_layout = QVBoxLayout(job_group)
        self._job_table = QTableView()
        self._job_table.setModel(self._job_model)
        self._job_table.setSelectionBehavior(QTableView.SelectRows)
        self._job_table.setAlternatingRowColors(True)
        self._job_table.setMaximumHeight(150)
        job_layout.addWidget(self._job_table)

        clear_btn = QPushButton("Clear Completed")
        clear_btn.clicked.connect(self._job_model.clearCompleted)
        job_layout.addWidget(clear_btn)

        right_layout.addWidget(job_group)

        splitter.addWidget(right_panel)

        # Set splitter sizes
        splitter.setSizes([220, 380, 640])

        main_layout.addWidget(splitter)

    def _apply_aomei_theme(self) -> None:
        """Apply an AOMEI-inspired theme to the main window."""
        self.setStyleSheet(aomei_qss())

    def _setup_statusbar(self) -> None:
        """Set up the status bar."""
        statusbar = self.statusBar()

        self._status_label = QLabel("Ready")
        statusbar.addWidget(self._status_label, 1)

        self._disk_count_label = QLabel("")
        statusbar.addPermanentWidget(self._disk_count_label)

        self._admin_label = QLabel("")
        statusbar.addPermanentWidget(self._admin_label)

        self._update_admin_status()

    def _update_admin_status(self) -> None:
        """Update admin status indicator."""
        is_admin = self._session.platform.is_admin()
        if is_admin:
            self._admin_label.setText("Admin: Yes")
            self._admin_label.setStyleSheet("color: green;")
        else:
            self._admin_label.setText("Admin: No")
            self._admin_label.setStyleSheet("color: red;")

    def _update_danger_mode_indicator(self) -> None:
        """Update danger mode indicator."""
        mode = self._session.danger_mode
        if mode == DangerMode.DISABLED:
            self._danger_label.setText("SAFE MODE")
            self._danger_label.setProperty("danger", False)
        else:
            self._danger_label.setText("⚠️ DANGER MODE")
            self._danger_label.setProperty("danger", True)
        self._danger_label.style().unpolish(self._danger_label)
        self._danger_label.style().polish(self._danger_label)

    @Slot()
    def _refresh_inventory(self) -> None:
        """Refresh disk inventory."""
        self._status_label.setText("Scanning disks...")

        try:
            inventory = self._session.platform.get_disk_inventory()
            self._disk_model.setInventory(inventory)

            # Update status
            self._disk_count_label.setText(
                f"Disks: {inventory.total_disks} | Partitions: {inventory.total_partitions}"
            )
            self._status_label.setText("Ready")

        except Exception as e:
            self._status_label.setText(f"Error: {e}")

    @Slot()
    def _on_disk_selection_changed(self) -> None:
        """Handle disk/partition selection change."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            self._details_label.setText("Select a disk or partition")
            self._disk_view.setDisk(None)
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if item is None:
            return

        if isinstance(item, Disk):
            self._show_disk_details(item)
            self._disk_view.setDisk(item)
        elif isinstance(item, Partition):
            self._show_partition_details(item)

    def _show_disk_details(self, disk: Disk) -> None:
        """Show disk details in the details panel."""
        text = f"""<b>Disk: {disk.device_path}</b><br>
<table>
<tr><td>Model:</td><td>{disk.model}</td></tr>
<tr><td>Serial:</td><td>{disk.serial or "N/A"}</td></tr>
<tr><td>Size:</td><td>{humanize.naturalsize(disk.size_bytes, binary=True)}</td></tr>
<tr><td>Type:</td><td>{disk.disk_type.name}</td></tr>
<tr><td>Style:</td><td>{disk.partition_style.name}</td></tr>
<tr><td>Partitions:</td><td>{len(disk.partitions)}</td></tr>
<tr><td>Unallocated:</td><td>{humanize.naturalsize(disk.unallocated_bytes, binary=True)}</td></tr>
<tr><td>System Disk:</td><td>{"Yes" if disk.is_system_disk else "No"}</td></tr>
</table>"""
        self._details_label.setText(text)

    def _show_partition_details(self, partition: Partition) -> None:
        """Show partition details in the details panel."""
        flags = ", ".join(f.name for f in partition.flags) if partition.flags else "None"
        text = f"""<b>Partition: {partition.device_path}</b><br>
<table>
<tr><td>Number:</td><td>{partition.number}</td></tr>
<tr><td>Size:</td><td>{humanize.naturalsize(partition.size_bytes, binary=True)}</td></tr>
<tr><td>Filesystem:</td><td>{partition.filesystem.value}</td></tr>
<tr><td>Label:</td><td>{partition.label or "N/A"}</td></tr>
<tr><td>UUID:</td><td>{partition.uuid or "N/A"}</td></tr>
<tr><td>Mountpoint:</td><td>{partition.mountpoint or "Not mounted"}</td></tr>
<tr><td>Flags:</td><td>{flags}</td></tr>
</table>"""
        self._details_label.setText(text)

    @Slot(Partition)
    def _on_partition_selected(self, partition: Partition) -> None:
        """Handle partition selection from graphics view."""
        self._show_partition_details(partition)

    def _show_context_menu(self, pos: Any) -> None:
        """Show context menu for disk/partition."""
        index = self._disk_tree.indexAt(pos)
        if not index.isValid():
            return

        item = self._disk_model.getItemAtIndex(index)
        if item is None:
            return

        menu = QMenu(self)

        if isinstance(item, Disk):
            clone_action = menu.addAction("Clone Disk...")
            clone_action.triggered.connect(lambda: self._clone_disk(item))

            backup_action = menu.addAction("Create Backup...")
            backup_action.triggered.connect(lambda: self._backup_device(item.device_path))

            menu.addSeparator()

            create_part_action = menu.addAction("Create Partition...")
            create_part_action.triggered.connect(lambda: self._create_partition(item))

        elif isinstance(item, Partition):
            clone_action = menu.addAction("Clone Partition...")
            clone_action.triggered.connect(lambda: self._clone_partition(item))

            backup_action = menu.addAction("Create Backup...")
            backup_action.triggered.connect(lambda: self._backup_device(item.device_path))

            menu.addSeparator()

            format_action = menu.addAction("Format...")
            format_action.triggered.connect(lambda: self._format_partition(item))

            delete_action = menu.addAction("Delete")
            delete_action.triggered.connect(lambda: self._delete_partition(item))

        menu.exec(self._disk_tree.mapToGlobal(pos))

    def _toggle_danger_mode(self) -> None:
        """Toggle danger mode."""
        if self._session.danger_mode == DangerMode.DISABLED:
            text, ok = QInputDialog.getText(
                self,
                "Enable Danger Mode",
                "Type 'I understand the risks' to enable danger mode:",
            )
            if ok:
                if self._session.enable_danger_mode(text):
                    QMessageBox.warning(
                        self,
                        "Danger Mode Enabled",
                        "Danger mode is now ENABLED. Be careful with destructive operations!",
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Failed",
                        "Incorrect confirmation. Danger mode NOT enabled.",
                    )
        else:
            self._session.disable_danger_mode()
            QMessageBox.information(self, "Danger Mode Disabled", "Danger mode has been disabled.")

        self._update_danger_mode_indicator()

    def _check_danger_mode(self) -> bool:
        """Check if danger mode is enabled, show error if not."""
        if self._session.danger_mode == DangerMode.DISABLED:
            QMessageBox.critical(
                self,
                "Danger Mode Required",
                "This operation requires Danger Mode to be enabled.\n\n"
                "Go to Tools > Toggle Danger Mode to enable it.",
            )
            return False
        return True

    def _on_create_partition(self) -> None:
        """Handle create partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._create_partition(item)
        elif isinstance(item, Partition):
            # Find parent disk
            inventory = self._disk_model.getInventory()
            if inventory:
                for disk in inventory.disks:
                    if item in disk.partitions:
                        self._create_partition(disk)
                        return

    def _create_partition(self, disk: Disk) -> None:
        """Create a new partition on disk."""
        if not self._check_danger_mode():
            return

        if disk.is_system_disk:
            QMessageBox.critical(
                self, "System Disk", "Cannot modify the system disk."
            )
            return

        # Simple dialog for partition creation
        fs_options = ["ext4", "xfs", "btrfs", "ntfs", "fat32"]
        fs, ok = QInputDialog.getItem(
            self,
            "Create Partition",
            "Select filesystem:",
            fs_options,
            0,
            False,
        )
        if not ok:
            return

        fs_map = {
            "ext4": FileSystem.EXT4,
            "xfs": FileSystem.XFS,
            "btrfs": FileSystem.BTRFS,
            "ntfs": FileSystem.NTFS,
            "fat32": FileSystem.FAT32,
        }

        # Confirm
        confirm_str = self._session.safety.generate_confirmation_string(disk.device_path)
        if not ConfirmationDialog.confirm(
            "Create Partition",
            f"This will modify the partition table on {disk.device_path}",
            confirm_str,
            parent=self,
        ):
            return

        from diskforge.core.models import PartitionCreateOptions

        options = PartitionCreateOptions(
            disk_path=disk.device_path,
            filesystem=fs_map[fs],
        )

        success, message = self._session.platform.create_partition(options)
        if success:
            QMessageBox.information(self, "Success", message)
            self._refresh_inventory()
        else:
            QMessageBox.critical(self, "Error", message)

    def _on_format_partition(self) -> None:
        """Handle format partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._format_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _format_partition(self, partition: Partition) -> None:
        """Format a partition."""
        if not self._check_danger_mode():
            return

        if partition.is_mounted:
            QMessageBox.critical(
                self,
                "Partition Mounted",
                f"Partition is mounted at {partition.mountpoint}. Unmount it first.",
            )
            return

        fs_options = ["ext4", "xfs", "btrfs", "ntfs", "fat32", "exfat"]
        fs, ok = QInputDialog.getItem(
            self,
            "Format Partition",
            "Select filesystem:",
            fs_options,
            0,
            False,
        )
        if not ok:
            return

        fs_map = {
            "ext4": FileSystem.EXT4,
            "xfs": FileSystem.XFS,
            "btrfs": FileSystem.BTRFS,
            "ntfs": FileSystem.NTFS,
            "fat32": FileSystem.FAT32,
            "exfat": FileSystem.EXFAT,
        }

        confirm_str = self._session.safety.generate_confirmation_string(partition.device_path)
        if not ConfirmationDialog.confirm(
            "Format Partition",
            f"This will ERASE ALL DATA on {partition.device_path}",
            confirm_str,
            parent=self,
        ):
            return

        from diskforge.core.models import FormatOptions

        options = FormatOptions(
            partition_path=partition.device_path,
            filesystem=fs_map[fs],
        )

        success, message = self._session.platform.format_partition(options)
        if success:
            QMessageBox.information(self, "Success", message)
            self._refresh_inventory()
        else:
            QMessageBox.critical(self, "Error", message)

    def _on_delete_partition(self) -> None:
        """Handle delete partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._delete_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _delete_partition(self, partition: Partition) -> None:
        """Delete a partition."""
        if not self._check_danger_mode():
            return

        if partition.is_mounted:
            QMessageBox.critical(
                self,
                "Partition Mounted",
                f"Partition is mounted at {partition.mountpoint}. Unmount it first.",
            )
            return

        confirm_str = self._session.safety.generate_confirmation_string(partition.device_path)
        if not ConfirmationDialog.confirm(
            "Delete Partition",
            f"This will PERMANENTLY DELETE {partition.device_path}",
            confirm_str,
            parent=self,
        ):
            return

        success, message = self._session.platform.delete_partition(partition.device_path)
        if success:
            QMessageBox.information(self, "Success", message)
            self._refresh_inventory()
        else:
            QMessageBox.critical(self, "Error", message)

    def _on_clone_disk(self) -> None:
        """Handle clone disk action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a source disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._clone_disk(item)

    def _clone_disk(self, source: Disk) -> None:
        """Clone a disk."""
        if not self._check_danger_mode():
            return

        # Get target disk from inventory
        inventory = self._disk_model.getInventory()
        if not inventory:
            return

        target_options = [
            f"{d.device_path} ({d.model})"
            for d in inventory.disks
            if d.device_path != source.device_path and not d.is_system_disk
        ]

        if not target_options:
            QMessageBox.warning(self, "No Target", "No suitable target disks available.")
            return

        target_str, ok = QInputDialog.getItem(
            self,
            "Clone Disk",
            "Select target disk:",
            target_options,
            0,
            False,
        )
        if not ok:
            return

        target_path = target_str.split(" ")[0]

        confirm_str = self._session.safety.generate_confirmation_string(target_path)
        if not ConfirmationDialog.confirm(
            "Clone Disk",
            f"This will DESTROY ALL DATA on {target_path}",
            confirm_str,
            parent=self,
        ):
            return

        self._status_label.setText(f"Cloning {source.device_path} to {target_path}...")
        success, message = self._session.platform.clone_disk(source.device_path, target_path)

        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)

        self._status_label.setText("Ready")
        self._refresh_inventory()

    def _on_clone_partition(self) -> None:
        """Handle clone partition action."""
        QMessageBox.information(
            self,
            "Clone Partition",
            "Select a partition from the tree and use right-click > Clone Partition",
        )

    def _clone_partition(self, source: Partition) -> None:
        """Clone a partition."""
        if not self._check_danger_mode():
            return

        # Get target partition path
        target_path, ok = QInputDialog.getText(
            self,
            "Clone Partition",
            "Enter target partition path:",
        )
        if not ok or not target_path:
            return

        confirm_str = self._session.safety.generate_confirmation_string(target_path)
        if not ConfirmationDialog.confirm(
            "Clone Partition",
            f"This will DESTROY ALL DATA on {target_path}",
            confirm_str,
            parent=self,
        ):
            return

        self._status_label.setText(f"Cloning {source.device_path} to {target_path}...")
        success, message = self._session.platform.clone_partition(
            source.device_path, target_path
        )

        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)

        self._status_label.setText("Ready")
        self._refresh_inventory()

    def _on_create_backup(self) -> None:
        """Handle create backup action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk or partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if item:
            source_path = item.device_path
            self._backup_device(source_path)

    def _backup_device(self, source_path: str) -> None:
        """Create backup of a device."""
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Backup Image",
            "",
            "Disk Images (*.img *.img.zst *.img.gz);;All Files (*)",
        )
        if not output_path:
            return

        compress_options = ["zstd (recommended)", "gzip", "none"]
        compress, ok = QInputDialog.getItem(
            self,
            "Compression",
            "Select compression:",
            compress_options,
            0,
            False,
        )
        if not ok:
            return

        compress_map = {
            "zstd (recommended)": "zstd",
            "gzip": "gzip",
            "none": None,
        }

        self._status_label.setText(f"Creating backup of {source_path}...")
        success, message, info = self._session.platform.create_image(
            source_path,
            Path(output_path),
            compression=compress_map[compress],
        )

        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)

        self._status_label.setText("Ready")

    def _on_restore_backup(self) -> None:
        """Handle restore backup action."""
        if not self._check_danger_mode():
            return

        image_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Backup Image",
            "",
            "Disk Images (*.img *.img.zst *.img.gz);;All Files (*)",
        )
        if not image_path:
            return

        target_path, ok = QInputDialog.getText(
            self,
            "Restore Target",
            "Enter target device path:",
        )
        if not ok or not target_path:
            return

        confirm_str = self._session.safety.generate_confirmation_string(target_path)
        if not ConfirmationDialog.confirm(
            "Restore Backup",
            f"This will DESTROY ALL DATA on {target_path}",
            confirm_str,
            parent=self,
        ):
            return

        self._status_label.setText(f"Restoring to {target_path}...")
        success, message = self._session.platform.restore_image(
            Path(image_path), target_path
        )

        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)

        self._status_label.setText("Ready")
        self._refresh_inventory()

    def _on_create_rescue(self) -> None:
        """Handle create rescue media action."""
        output_path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory for Rescue Media",
        )
        if not output_path:
            return

        self._status_label.setText("Creating rescue media...")
        success, message, artifacts = self._session.platform.create_rescue_media(
            Path(output_path)
        )

        if success:
            QMessageBox.information(self, "Success", f"{message}\n\nCreated files in: {output_path}")
        else:
            QMessageBox.critical(self, "Error", message)

        self._status_label.setText("Ready")

    def _on_cancel_job(self) -> None:
        """Cancel current job."""
        # For now, just log - full implementation would track current job
        self._status_label.setText("Cancellation requested")

    def _on_pause_job(self) -> None:
        """Pause current job."""
        self._status_label.setText("Job paused")

    def _on_resume_job(self) -> None:
        """Resume current job."""
        self._status_label.setText("Job resumed")

    def _show_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About DiskForge",
            f"""<h2>DiskForge v{__version__}</h2>
<p>Cross-platform disk management application.</p>
<p>Features:
<ul>
<li>Disk and partition inventory</li>
<li>Partition management (create, delete, format)</li>
<li>Disk and partition cloning</li>
<li>Image backup and restore</li>
<li>Bootable rescue media creation</li>
</ul>
</p>
<p>Platform: {self._session.platform.name}</p>
<p>&copy; 2024 DiskForge Team</p>""",
        )

    def closeEvent(self, event: Any) -> None:
        """Handle window close."""
        self._refresh_timer.stop()
        self._session.close()
        super().closeEvent(event)
