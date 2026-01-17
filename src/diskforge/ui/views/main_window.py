"""
DiskForge Main Window.

The main application window with disk tree, actions, and job queue.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTreeView,
    QTableView,
    QLabel,
    QMessageBox,
    QMenu,
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
from diskforge.core.models import Disk, DiskType, Partition
from diskforge.core.job import Job, JobStatus
from diskforge.core.safety import DangerMode
from diskforge.core.session import Session
from diskforge.ui.models.disk_model import DiskModel
from diskforge.ui.models.job_model import JobModel, PendingOperationsModel
from diskforge.ui.assets import DiskForgeIcons
from diskforge.ui.theme import aomei_qss
from diskforge.ui.widgets.confirmation_dialog import ConfirmationDialog
from diskforge.ui.widgets.disk_view import DiskMapWidget, MultiDiskMapWidget
from diskforge.ui.widgets.operations_tree import OperationsTreeWidget
from diskforge.ui.widgets.progress_widget import ProgressWidget, PendingOperationsWidget
from diskforge.ui.widgets.selection_actions_panel import SelectionActionsPanel
from diskforge.ui.widgets.ribbon import RibbonWidget, RibbonButton, RibbonGroup
from diskforge.ui.views.wizards import (
    CreatePartitionWizard,
    FormatPartitionWizard,
    DeletePartitionWizard,
    CloneDiskWizard,
    ClonePartitionWizard,
    CreateBackupWizard,
    SystemBackupWizard,
    RestoreBackupWizard,
    RescueMediaWizard,
    ResizeMovePartitionWizard,
    ResizeMoveDynamicVolumeWizard,
    MergePartitionsWizard,
    SplitPartitionWizard,
    ExtendPartitionWizard,
    ShrinkPartitionWizard,
    ExtendDynamicVolumeWizard,
    ShrinkDynamicVolumeWizard,
    AllocateFreeSpaceWizard,
    OneClickAdjustSpaceWizard,
    QuickPartitionWizard,
    PartitionAttributesWizard,
    InitializeDiskWizard,
    WipeWizard,
    SystemDiskWipeWizard,
    SSDSecureEraseWizard,
    PartitionRecoveryWizard,
    FileRecoveryWizard,
    ShredWizard,
    DefragDiskWizard,
    DefragPartitionWizard,
    DiskHealthCheckWizard,
    BadSectorScanWizard,
    DiskSpeedTestWizard,
    SurfaceTestWizard,
    Align4KWizard,
    ConvertPartitionStyleWizard,
    ConvertSystemPartitionStyleWizard,
    ConvertFilesystemWizard,
    ConvertPartitionRoleWizard,
    ConvertDiskLayoutWizard,
    SystemMigrationWizard,
    FreeSpaceWizard,
    JunkCleanupWizard,
    LargeFilesWizard,
    DuplicateFilesWizard,
    MoveApplicationWizard,
    IntegrateRecoveryEnvironmentWizard,
    BootRepairWizard,
    RebuildMBRWizard,
    UEFIBootOptionsWizard,
    WindowsToGoWizard,
    ResetWindowsPasswordWizard,
)
from diskforge.sync import SyncManager


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
        self._pending_model = PendingOperationsModel(self)
        self._active_job_id: str | None = None
        self._selected_disk: Disk | None = None
        self._selected_partition: Partition | None = None

        # Set up UI
        self._apply_aomei_theme()
        self._actions = self._build_actions()
        self._setup_ribbon()
        self._setup_central_widget()
        self._setup_statusbar()
        self._update_danger_mode_indicator()
        self._update_bitlocker_availability()

        self._job_model.jobStatusChanged.connect(self._on_job_status_changed)
        self._job_model.jobProgressChanged.connect(self._on_job_progress_changed)

        # Refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_inventory)
        self._refresh_timer.start(session.config.ui.refresh_interval_ms)

        # Initial load
        self._refresh_inventory()

    def _build_actions(self) -> dict[str, QAction]:
        """Build reusable QAction instances for the ribbon."""
        actions = {
            "apply": QAction("Apply", self),
            "undo": QAction("Undo", self),
            "redo": QAction("Redo", self),
            "refresh": QAction("Refresh", self),
            "exit": QAction("Exit", self),
            "clone": QAction("Clone", self),
            "clone_disk": QAction("Copy Disk Wizard (Advanced)...", self),
            "clone_partition": QAction("Copy Partition Wizard (Advanced)...", self),
            "backup": QAction("Disk Backup (Advanced)", self),
            "create_backup": QAction("Disk Backup (Advanced)...", self),
            "system_backup": QAction("System Backup...", self),
            "restore_backup": QAction("Disk Restore...", self),
            "rescue_media": QAction("Make Bootable Media...", self),
            "integrate_recovery_env": QAction("Integrate to Recovery Environment...", self),
            "boot_repair": QAction("Boot Repair...", self),
            "rebuild_mbr": QAction("Rebuild MBR...", self),
            "uefi_boot_manager": QAction("UEFI BIOS Boot Options...", self),
            "windows_to_go": QAction("Windows To Go Creator...", self),
            "reset_windows_password": QAction("Reset Windows Password...", self),
            "bitlocker_status": QAction("BitLocker Status", self),
            "bitlocker_enable": QAction("Enable BitLocker...", self),
            "bitlocker_disable": QAction("Disable BitLocker...", self),
            "danger_mode": QAction("Toggle Danger Mode", self),
            "about": QAction("About DiskForge", self),
            "create_partition": QAction("Create Partition...", self),
            "format_partition": QAction("Format Partition...", self),
            "delete_partition": QAction("Delete Partition...", self),
            "resize_move_partition": QAction("Resize/Move Partition...", self),
            "resize_move_dynamic_volume": QAction("Resize/Move Dynamic Volume...", self),
            "merge_partitions": QAction("Merge Partitions...", self),
            "split_partition": QAction("Split Partition...", self),
            "extend_partition": QAction("Extend Partition...", self),
            "shrink_partition": QAction("Shrink Partition...", self),
            "extend_dynamic_volume": QAction("Extend Dynamic Volume...", self),
            "shrink_dynamic_volume": QAction("Shrink Dynamic Volume...", self),
            "allocate_free_space": QAction("Allocate Free Space...", self),
            "one_click_adjust_space": QAction("One-Click Adjust Space...", self),
            "quick_partition": QAction("Quick Partition...", self),
            "edit_partition_attributes": QAction("Edit Partition Attributes...", self),
            "initialize_disk": QAction("Initialize Disk...", self),
            "wipe_device": QAction("Wipe/Secure Erase...", self),
            "wipe_system_disk": QAction("System Disk Wipe...", self),
            "secure_erase_ssd": QAction("SSD Secure Erase...", self),
            "partition_recovery": QAction("Partition Recovery...", self),
            "file_recovery": QAction("File Recovery...", self),
            "shred_files": QAction("Shred Files/Folders...", self),
            "defrag_disk": QAction("Defragment Disk...", self),
            "defrag_partition": QAction("Defragment Partition...", self),
            "disk_health_check": QAction("Disk Health Check...", self),
            "disk_speed_test": QAction("Disk Speed Test...", self),
            "bad_sector_scan": QAction("Bad Sector Scan...", self),
            "surface_test": QAction("Surface Test...", self),
            "align_4k": QAction("Align 4K...", self),
            "convert_partition_style": QAction("Convert MBR/GPT...", self),
            "convert_system_partition_style": QAction("Convert System Disk MBR/GPT...", self),
            "convert_filesystem": QAction("Convert Filesystem (NTFS/FAT32)...", self),
            "convert_partition_role": QAction("Convert Primary/Logical...", self),
            "convert_disk_layout": QAction("Convert Dynamic/Basic...", self),
            "migrate_system": QAction("OS/System Migration...", self),
            "free_space": QAction("Free Up Space...", self),
            "junk_cleanup": QAction("Junk File Cleanup...", self),
            "large_files": QAction("Large File Finder...", self),
            "duplicate_files": QAction("Duplicate File Finder...", self),
            "move_applications": QAction("Move Applications...", self),
        }

        icon_map = {
            "apply": DiskForgeIcons.CREATE_BACKUP,
            "undo": DiskForgeIcons.RESTORE_BACKUP,
            "redo": DiskForgeIcons.REFRESH,
            "refresh": DiskForgeIcons.REFRESH,
            "exit": DiskForgeIcons.EXIT,
            "clone": DiskForgeIcons.CLONE_DISK,
            "clone_disk": DiskForgeIcons.CLONE_DISK,
            "clone_partition": DiskForgeIcons.CLONE_PARTITION,
            "backup": DiskForgeIcons.CREATE_BACKUP,
            "create_backup": DiskForgeIcons.CREATE_BACKUP,
            "system_backup": DiskForgeIcons.CREATE_BACKUP,
            "restore_backup": DiskForgeIcons.RESTORE_BACKUP,
            "rescue_media": DiskForgeIcons.RESCUE_MEDIA,
            "integrate_recovery_env": DiskForgeIcons.RESCUE_MEDIA,
            "boot_repair": DiskForgeIcons.REFRESH,
            "rebuild_mbr": DiskForgeIcons.REFRESH,
            "uefi_boot_manager": DiskForgeIcons.ABOUT,
            "windows_to_go": DiskForgeIcons.CLONE_DISK,
            "reset_windows_password": DiskForgeIcons.DANGER_MODE,
            "bitlocker_status": DiskForgeIcons.REFRESH,
            "bitlocker_enable": DiskForgeIcons.DANGER_MODE,
            "bitlocker_disable": DiskForgeIcons.DANGER_MODE,
            "danger_mode": DiskForgeIcons.DANGER_MODE,
            "about": DiskForgeIcons.ABOUT,
            "create_partition": DiskForgeIcons.CREATE_PARTITION,
            "format_partition": DiskForgeIcons.FORMAT_PARTITION,
            "delete_partition": DiskForgeIcons.DELETE_PARTITION,
            "resize_move_partition": DiskForgeIcons.CREATE_PARTITION,
            "resize_move_dynamic_volume": DiskForgeIcons.CREATE_PARTITION,
            "merge_partitions": DiskForgeIcons.CREATE_PARTITION,
            "split_partition": DiskForgeIcons.CREATE_PARTITION,
            "extend_partition": DiskForgeIcons.CREATE_PARTITION,
            "shrink_partition": DiskForgeIcons.FORMAT_PARTITION,
            "extend_dynamic_volume": DiskForgeIcons.CREATE_PARTITION,
            "shrink_dynamic_volume": DiskForgeIcons.FORMAT_PARTITION,
            "allocate_free_space": DiskForgeIcons.CREATE_PARTITION,
            "one_click_adjust_space": DiskForgeIcons.CREATE_PARTITION,
            "quick_partition": DiskForgeIcons.CREATE_PARTITION,
            "edit_partition_attributes": DiskForgeIcons.FORMAT_PARTITION,
            "initialize_disk": DiskForgeIcons.CLONE_DISK,
            "wipe_device": DiskForgeIcons.DELETE_PARTITION,
            "wipe_system_disk": DiskForgeIcons.DELETE_PARTITION,
            "secure_erase_ssd": DiskForgeIcons.DELETE_PARTITION,
            "partition_recovery": DiskForgeIcons.RESTORE_BACKUP,
            "file_recovery": DiskForgeIcons.RESTORE_BACKUP,
            "shred_files": DiskForgeIcons.DELETE_PARTITION,
            "defrag_disk": DiskForgeIcons.REFRESH,
            "defrag_partition": DiskForgeIcons.REFRESH,
            "disk_health_check": DiskForgeIcons.REFRESH,
            "disk_speed_test": DiskForgeIcons.REFRESH,
            "bad_sector_scan": DiskForgeIcons.REFRESH,
            "surface_test": DiskForgeIcons.REFRESH,
            "align_4k": DiskForgeIcons.CREATE_PARTITION,
            "convert_partition_style": DiskForgeIcons.CLONE_DISK,
            "convert_system_partition_style": DiskForgeIcons.CLONE_DISK,
            "convert_filesystem": DiskForgeIcons.FORMAT_PARTITION,
            "convert_partition_role": DiskForgeIcons.CREATE_PARTITION,
            "convert_disk_layout": DiskForgeIcons.CLONE_DISK,
            "migrate_system": DiskForgeIcons.CLONE_DISK,
            "free_space": DiskForgeIcons.REFRESH,
            "junk_cleanup": DiskForgeIcons.DELETE_PARTITION,
            "large_files": DiskForgeIcons.FORMAT_PARTITION,
            "duplicate_files": DiskForgeIcons.CREATE_PARTITION,
            "move_applications": DiskForgeIcons.CLONE_DISK,
        }

        for action_key, icon_name in icon_map.items():
            actions[action_key].setIcon(DiskForgeIcons.icon(icon_name))

        actions["apply"].setEnabled(False)
        actions["undo"].setEnabled(False)
        actions["redo"].setEnabled(False)

        actions["refresh"].setShortcut("F5")
        actions["refresh"].triggered.connect(self._refresh_inventory)

        actions["exit"].setShortcut("Alt+F4")
        actions["exit"].triggered.connect(self.close)

        actions["clone_disk"].triggered.connect(self._on_clone_disk)
        actions["clone_partition"].triggered.connect(self._on_clone_partition)
        actions["create_backup"].triggered.connect(self._on_create_backup)
        actions["system_backup"].triggered.connect(self._on_system_backup)
        actions["restore_backup"].triggered.connect(self._on_restore_backup)
        actions["rescue_media"].triggered.connect(self._on_create_rescue)
        actions["integrate_recovery_env"].triggered.connect(self._on_integrate_recovery_env)
        actions["boot_repair"].triggered.connect(self._on_boot_repair)
        actions["rebuild_mbr"].triggered.connect(self._on_rebuild_mbr)
        actions["uefi_boot_manager"].triggered.connect(self._on_uefi_boot_manager)
        actions["windows_to_go"].triggered.connect(self._on_windows_to_go)
        actions["reset_windows_password"].triggered.connect(self._on_reset_windows_password)
        actions["bitlocker_status"].triggered.connect(self._on_bitlocker_status)
        actions["bitlocker_enable"].triggered.connect(self._on_bitlocker_enable)
        actions["bitlocker_disable"].triggered.connect(self._on_bitlocker_disable)
        actions["danger_mode"].triggered.connect(self._toggle_danger_mode)
        actions["about"].triggered.connect(self._show_about)
        actions["create_partition"].triggered.connect(self._on_create_partition)
        actions["format_partition"].triggered.connect(self._on_format_partition)
        actions["delete_partition"].triggered.connect(self._on_delete_partition)
        actions["resize_move_partition"].triggered.connect(self._on_resize_move_partition)
        actions["resize_move_dynamic_volume"].triggered.connect(self._on_resize_move_dynamic_volume)
        actions["merge_partitions"].triggered.connect(self._on_merge_partitions)
        actions["split_partition"].triggered.connect(self._on_split_partition)
        actions["extend_partition"].triggered.connect(self._on_extend_partition)
        actions["shrink_partition"].triggered.connect(self._on_shrink_partition)
        actions["extend_dynamic_volume"].triggered.connect(self._on_extend_dynamic_volume)
        actions["shrink_dynamic_volume"].triggered.connect(self._on_shrink_dynamic_volume)
        actions["allocate_free_space"].triggered.connect(self._on_allocate_free_space)
        actions["one_click_adjust_space"].triggered.connect(self._on_one_click_adjust_space)
        actions["quick_partition"].triggered.connect(self._on_quick_partition)
        actions["edit_partition_attributes"].triggered.connect(self._on_edit_partition_attributes)
        actions["initialize_disk"].triggered.connect(self._on_initialize_disk)
        actions["wipe_device"].triggered.connect(self._on_wipe_device)
        actions["wipe_system_disk"].triggered.connect(self._on_wipe_system_disk)
        actions["secure_erase_ssd"].triggered.connect(self._on_secure_erase_ssd)
        actions["partition_recovery"].triggered.connect(self._on_partition_recovery)
        actions["file_recovery"].triggered.connect(self._on_file_recovery)
        actions["shred_files"].triggered.connect(self._on_shred_files)
        actions["defrag_disk"].triggered.connect(self._on_defrag_disk)
        actions["defrag_partition"].triggered.connect(self._on_defrag_partition)
        actions["disk_health_check"].triggered.connect(self._on_disk_health_check)
        actions["disk_speed_test"].triggered.connect(self._on_disk_speed_test)
        actions["bad_sector_scan"].triggered.connect(self._on_bad_sector_scan)
        actions["surface_test"].triggered.connect(self._on_surface_test)
        actions["align_4k"].triggered.connect(self._on_align_4k)
        actions["convert_partition_style"].triggered.connect(self._on_convert_partition_style)
        actions["convert_system_partition_style"].triggered.connect(self._on_convert_system_partition_style)
        actions["convert_filesystem"].triggered.connect(self._on_convert_filesystem)
        actions["convert_partition_role"].triggered.connect(self._on_convert_partition_role)
        actions["convert_disk_layout"].triggered.connect(self._on_convert_disk_layout)
        actions["migrate_system"].triggered.connect(self._on_migrate_system)
        actions["free_space"].triggered.connect(self._on_free_space)
        actions["junk_cleanup"].triggered.connect(self._on_junk_cleanup)
        actions["large_files"].triggered.connect(self._on_large_files)
        actions["duplicate_files"].triggered.connect(self._on_duplicate_files)
        actions["move_applications"].triggered.connect(self._on_move_applications)
        actions["clone"].triggered.connect(self._on_clone_disk)
        actions["backup"].triggered.connect(self._on_create_backup)

        actions["clone_disk"].setStatusTip("Clone a disk with intelligent/sector-by-sector options")
        actions["clone_partition"].setStatusTip("Clone a partition with validation and scheduling options")
        actions["create_backup"].setStatusTip("Create a backup with compression levels and validation options")
        actions["system_backup"].setStatusTip("Capture OS partitions and boot metadata in a system backup bundle")
        actions["restore_backup"].setStatusTip("Restore a backup image to a disk or partition")

        return actions

    def _setup_ribbon(self) -> None:
        """Set up the ribbon-style command area."""
        ribbon = RibbonWidget(self)
        ribbon.add_tab(
            "Home",
            [
                RibbonGroup(
                    "Quick Access",
                    columns=[
                        [
                            RibbonButton(self._actions["apply"], size="small"),
                            RibbonButton(self._actions["undo"], size="small"),
                            RibbonButton(self._actions["redo"], size="small"),
                        ]
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Common",
                    columns=[
                        [RibbonButton(self._actions["refresh"])],
                        [
                            RibbonButton(self._actions["about"], size="small"),
                            RibbonButton(self._actions["exit"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Partition Operations",
                    columns=[
                        [RibbonButton(self._actions["create_partition"])],
                        [
                            RibbonButton(self._actions["format_partition"], size="small"),
                            RibbonButton(self._actions["delete_partition"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Safety",
                    columns=[[RibbonButton(self._actions["danger_mode"], size="small")]],
                    separator_after=True,
                ),
                RibbonGroup(
                    "BitLocker",
                    columns=[
                        [RibbonButton(self._actions["bitlocker_status"])],
                        [
                            RibbonButton(self._actions["bitlocker_enable"], size="small"),
                            RibbonButton(self._actions["bitlocker_disable"], size="small"),
                        ],
                    ],
                ),
            ],
        )
        ribbon.add_tab(
            "Advanced",
            [
                RibbonGroup(
                    "Resize",
                    columns=[
                        [RibbonButton(self._actions["resize_move_partition"])],
                        [
                            RibbonButton(self._actions["extend_partition"], size="small"),
                            RibbonButton(self._actions["shrink_partition"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Dynamic Volumes",
                    columns=[
                        [RibbonButton(self._actions["resize_move_dynamic_volume"])],
                        [
                            RibbonButton(self._actions["extend_dynamic_volume"], size="small"),
                            RibbonButton(self._actions["shrink_dynamic_volume"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Space Tools",
                    columns=[
                        [RibbonButton(self._actions["allocate_free_space"])],
                        [RibbonButton(self._actions["one_click_adjust_space"], size="small")],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Partition Tools",
                    columns=[
                        [RibbonButton(self._actions["merge_partitions"])],
                        [
                            RibbonButton(self._actions["split_partition"], size="small"),
                            RibbonButton(self._actions["align_4k"], size="small"),
                            RibbonButton(self._actions["defrag_partition"], size="small"),
                        ],
                        [
                            RibbonButton(self._actions["edit_partition_attributes"], size="small"),
                            RibbonButton(self._actions["convert_filesystem"], size="small"),
                            RibbonButton(self._actions["convert_partition_role"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Disk Tools",
                    columns=[
                        [
                            RibbonButton(self._actions["convert_partition_style"]),
                            RibbonButton(self._actions["convert_system_partition_style"], size="small"),
                        ],
                        [
                            RibbonButton(self._actions["defrag_disk"], size="small"),
                            RibbonButton(self._actions["wipe_device"], size="small"),
                            RibbonButton(self._actions["secure_erase_ssd"], size="small"),
                            RibbonButton(self._actions["partition_recovery"], size="small"),
                        ],
                        [
                            RibbonButton(self._actions["wipe_system_disk"], size="small"),
                        ],
                        [
                            RibbonButton(self._actions["initialize_disk"], size="small"),
                            RibbonButton(self._actions["convert_disk_layout"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Diagnostics",
                    columns=[
                        [RibbonButton(self._actions["disk_health_check"])],
                        [
                            RibbonButton(self._actions["disk_speed_test"], size="small"),
                            RibbonButton(self._actions["bad_sector_scan"], size="small"),
                            RibbonButton(self._actions["surface_test"], size="small"),
                        ],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Setup",
                    columns=[[RibbonButton(self._actions["quick_partition"])]],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Migration",
                    columns=[[RibbonButton(self._actions["migrate_system"])]],
                ),
            ],
        )
        ribbon.add_tab(
            "Cleanup",
            [
                RibbonGroup(
                    "Space Recovery",
                    columns=[
                        [RibbonButton(self._actions["free_space"])],
                        [RibbonButton(self._actions["junk_cleanup"], size="small")],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "File Tools",
                    columns=[
                        [RibbonButton(self._actions["large_files"])],
                        [
                            RibbonButton(self._actions["duplicate_files"], size="small"),
                            RibbonButton(self._actions["file_recovery"], size="small"),
                        ],
                        [RibbonButton(self._actions["shred_files"], size="small")],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Apps",
                    columns=[[RibbonButton(self._actions["move_applications"])]],
                ),
            ],
        )
        ribbon.add_tab(
            "Backup",
            [
                RibbonGroup(
                    "Backup",
                    columns=[
                        [RibbonButton(self._actions["backup"])],
                        [RibbonButton(self._actions["system_backup"], size="small")],
                    ],
                ),
            ],
        )
        ribbon.add_tab(
            "Restore",
            [
                RibbonGroup(
                    "Restore",
                    columns=[[RibbonButton(self._actions["restore_backup"])]],
                ),
            ],
        )
        ribbon.add_tab(
            "Clone",
            [
                RibbonGroup(
                    "Clone",
                    columns=[
                        [
                            RibbonButton(
                                self._actions["clone"],
                                split_actions=[self._actions["clone_disk"], self._actions["clone_partition"]],
                            )
                        ],
                        [RibbonButton(self._actions["clone_partition"], size="small")],
                    ],
                ),
            ],
        )
        ribbon.add_tab(
            "Tools",
            [
                RibbonGroup(
                    "Utilities",
                    columns=[
                        [RibbonButton(self._actions["rescue_media"])],
                        [RibbonButton(self._actions["danger_mode"], size="small")],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Boot & Recovery",
                    columns=[
                        [RibbonButton(self._actions["integrate_recovery_env"])],
                        [
                            RibbonButton(self._actions["boot_repair"], size="small"),
                            RibbonButton(self._actions["rebuild_mbr"], size="small"),
                        ],
                        [
                            RibbonButton(self._actions["uefi_boot_manager"], size="small"),
                            RibbonButton(self._actions["windows_to_go"], size="small"),
                        ],
                        [RibbonButton(self._actions["reset_windows_password"], size="small")],
                    ],
                    separator_after=True,
                ),
                RibbonGroup(
                    "Session",
                    columns=[[RibbonButton(self._actions["exit"], size="small")]],
                ),
            ],
        )

        self._ribbon = ribbon

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
        header_layout.setContentsMargins(20, 12, 20, 12)
        header_layout.setSpacing(16)

        logo_label = QLabel("DF")
        logo_label.setObjectName("appLogo")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setFixedSize(44, 44)

        title_block = QVBoxLayout()
        title_label = QLabel("DiskForge")
        title_label.setObjectName("appTitle")
        subtitle_label = QLabel("Disk management workspace")
        subtitle_label.setObjectName("appSubtitle")
        title_block.addWidget(title_label)
        title_block.addWidget(subtitle_label)
        title_block.setSpacing(0)

        left_header_layout = QHBoxLayout()
        left_header_layout.setSpacing(12)
        left_header_layout.addWidget(logo_label)
        left_header_layout.addLayout(title_block)

        header_layout.addLayout(left_header_layout)
        header_layout.addStretch()

        right_header_layout = QHBoxLayout()
        right_header_layout.setSpacing(8)

        def add_header_action(action: QAction, label: str) -> None:
            button = QPushButton(label)
            button.setObjectName("headerActionButton")
            button.setIcon(action.icon())
            button.setFlat(True)
            button.clicked.connect(action.trigger)
            right_header_layout.addWidget(button)

        add_header_action(self._actions["refresh"], "Refresh")
        add_header_action(self._actions["about"], "About")

        version_badge = QLabel(f"v{__version__}")
        version_badge.setObjectName("versionBadge")
        version_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right_header_layout.addWidget(version_badge)

        self._danger_label = QLabel("SAFE MODE")
        self._danger_label.setObjectName("modeBadge")
        self._danger_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right_header_layout.addWidget(self._danger_label)

        header_layout.addLayout(right_header_layout)

        main_layout.addWidget(header_bar)
        main_layout.addWidget(self._ribbon)

        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")

        # Center area - disk list on top and disk map beneath
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        center_splitter = QSplitter(Qt.Vertical)
        center_splitter.setObjectName("centerSplitter")

        disk_list_panel = QWidget()
        disk_list_layout = QVBoxLayout(disk_list_panel)
        disk_list_layout.setContentsMargins(12, 12, 12, 12)
        disk_list_layout.setSpacing(12)

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
        for column in range(self._disk_model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        disk_layout.addWidget(self._disk_tree)
        disk_list_layout.addWidget(disk_group)

        disk_overview_title = QLabel("Disk Overview")
        disk_overview_title.setObjectName("sectionTitle")
        disk_list_layout.addWidget(disk_overview_title)

        self._multi_disk_map = MultiDiskMapWidget()
        disk_list_layout.addWidget(self._multi_disk_map)

        disk_map_panel = QFrame()
        disk_map_panel.setObjectName("diskMapPanel")
        disk_panel_layout = QVBoxLayout(disk_map_panel)
        disk_panel_layout.setContentsMargins(12, 12, 12, 12)
        disk_panel_layout.setSpacing(6)

        disk_header_layout = QHBoxLayout()
        disk_title = QLabel("Disk Map")
        disk_title.setObjectName("sectionTitle")
        disk_header_layout.addWidget(disk_title)
        disk_header_layout.addStretch()

        def add_map_action(text: str, slot: Any) -> None:
            button = QPushButton(text)
            button.setObjectName("mapActionButton")
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.clicked.connect(slot)
            disk_header_layout.addWidget(button)

        add_map_action("Refresh", self._refresh_inventory)
        add_map_action("Create", self._on_create_partition)
        add_map_action("Format", self._on_format_partition)
        add_map_action("Delete", self._on_delete_partition)

        disk_panel_layout.addLayout(disk_header_layout)

        self._disk_map_subtitle = QLabel("Select a disk to view the map")
        self._disk_map_subtitle.setObjectName("diskMapSubtitle")
        disk_panel_layout.addWidget(self._disk_map_subtitle)

        self._disk_map = DiskMapWidget()
        self._disk_map.partitionSelected.connect(self._on_partition_selected)
        disk_panel_layout.addWidget(self._disk_map)

        center_splitter.addWidget(disk_list_panel)
        center_splitter.addWidget(disk_map_panel)
        center_splitter.setStretchFactor(0, 1)
        center_splitter.setStretchFactor(1, 2)

        center_layout.addWidget(center_splitter)
        splitter.addWidget(center_panel)

        # Right panel - actions and properties
        right_panel = QWidget()
        right_panel.setMinimumWidth(320)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(12)

        selection_actions_group = QGroupBox("Selection Actions")
        selection_actions_layout = QVBoxLayout(selection_actions_group)
        self._selection_actions_panel = SelectionActionsPanel(self._actions, selection_actions_group)
        self._selection_actions_panel.propertiesRequested.connect(self._show_selection_properties)
        selection_actions_layout.addWidget(self._selection_actions_panel)
        right_layout.addWidget(selection_actions_group)

        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)

        operations_tree = OperationsTreeWidget(self._actions, actions_group)
        operations_tree.setObjectName("operationsTree")
        actions_layout.addWidget(operations_tree)
        right_layout.addWidget(actions_group)

        # Details panel
        details_group = QGroupBox("Selection Details")
        details_layout = QVBoxLayout(details_group)
        self._details_label = QLabel("Select a disk or partition to view details")
        self._details_label.setWordWrap(True)
        details_layout.addWidget(self._details_label)
        right_layout.addWidget(details_group)

        # BitLocker panel
        self._bitlocker_group = QGroupBox("BitLocker")
        bitlocker_layout = QVBoxLayout(self._bitlocker_group)

        self._bitlocker_volume_label = QLabel("Volume: (none)")
        self._bitlocker_volume_label.setObjectName("bitlockerVolumeLabel")
        bitlocker_layout.addWidget(self._bitlocker_volume_label)

        self._bitlocker_status_label = QLabel("BitLocker status is unavailable.")
        self._bitlocker_status_label.setWordWrap(True)
        self._bitlocker_status_label.setObjectName("bitlockerStatusLabel")
        bitlocker_layout.addWidget(self._bitlocker_status_label)

        bitlocker_button_row = QHBoxLayout()
        self._bitlocker_refresh_button = QPushButton("Refresh Status")
        self._bitlocker_refresh_button.clicked.connect(self._on_bitlocker_status)
        bitlocker_button_row.addWidget(self._bitlocker_refresh_button)

        self._bitlocker_enable_button = QPushButton("Enable")
        self._bitlocker_enable_button.clicked.connect(self._on_bitlocker_enable)
        bitlocker_button_row.addWidget(self._bitlocker_enable_button)

        self._bitlocker_disable_button = QPushButton("Disable")
        self._bitlocker_disable_button.clicked.connect(self._on_bitlocker_disable)
        bitlocker_button_row.addWidget(self._bitlocker_disable_button)

        bitlocker_button_row.addStretch()
        bitlocker_layout.addLayout(bitlocker_button_row)

        right_layout.addWidget(self._bitlocker_group)

        # Pending operations panel
        pending_group = QGroupBox("Pending Operations")
        pending_layout = QVBoxLayout(pending_group)
        self._pending_widget = PendingOperationsWidget()
        self._pending_widget.setModel(self._pending_model)
        self._pending_widget.applyRequested.connect(self._apply_pending_operations)
        self._pending_widget.undoRequested.connect(self._pending_model.undoLastOperation)
        self._actions["apply"].triggered.connect(self._pending_widget.applyRequested.emit)
        self._actions["undo"].triggered.connect(self._pending_model.undoLastOperation)
        self._pending_model.pendingCountChanged.connect(self._actions["apply"].setEnabled)
        self._pending_model.pendingCountChanged.connect(self._actions["undo"].setEnabled)
        pending_layout.addWidget(self._pending_widget)
        right_layout.addWidget(pending_group)

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
        splitter.setSizes([760, 360])

        main_layout.addWidget(splitter)

    def _apply_pending_operations(self) -> None:
        """Submit pending operations to the job runner."""
        pending_jobs = self._pending_model.takeOperations()
        if not pending_jobs:
            return

        for job in pending_jobs:
            self._session.submit_job(job)
            self._job_model.addJob(job)

        if hasattr(self, "_status_label"):
            count = len(pending_jobs)
            noun = "operation" if count == 1 else "operations"
            self._status_label.setText(f"Applied {count} {noun}.")

    def _submit_job(self, job: Job[Any]) -> None:
        """Submit a job to the runner and track it in the UI."""
        self._session.submit_job(job)
        self._job_model.addJob(job)
        if hasattr(self, "_status_label"):
            self._status_label.setText(f"Queued job: {job.name}")

    def _find_running_job(self) -> Job[Any] | None:
        for row in range(self._job_model.rowCount()):
            job = self._job_model.getJobAtRow(row)
            if job and job.status == JobStatus.RUNNING:
                return job
        return None

    def _on_job_status_changed(self, job_id: str, status: JobStatus) -> None:
        if status == JobStatus.RUNNING:
            self._active_job_id = job_id
            job = self._job_model.getJobById(job_id)
            if job:
                self._progress_widget.setRunning(True)
                self._progress_widget.updateProgress(job.context.get_progress())
            if hasattr(self, "_status_label") and job:
                self._status_label.setText(f"Running: {job.name}")
            return

        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            if job_id == self._active_job_id:
                next_job = self._find_running_job()
                if next_job:
                    self._active_job_id = next_job.id
                    self._progress_widget.setRunning(True)
                    self._progress_widget.updateProgress(next_job.context.get_progress())
                    if hasattr(self, "_status_label"):
                        self._status_label.setText(f"Running: {next_job.name}")
                else:
                    self._active_job_id = None
                    self._progress_widget.reset()
                    if hasattr(self, "_status_label"):
                        self._status_label.setText("Ready")

    def _on_job_progress_changed(self, job_id: str, progress: Any) -> None:
        if job_id == self._active_job_id:
            self._progress_widget.updateProgress(progress)

    def _apply_aomei_theme(self) -> None:
        """Apply an AOMEI-inspired theme to the main window."""
        self.setStyleSheet(aomei_qss())

    def _setup_statusbar(self) -> None:
        """Set up the status bar."""
        statusbar = self.statusBar()

        self._status_label = QLabel("Ready")
        statusbar.addWidget(self._status_label, 1)

        self._sync_mode_combo = QComboBox()
        self._sync_mode_combo.addItems(["one-way", "two-way"])
        self._sync_mode_combo.setCurrentText(self._session.config.sync.direction)
        self._sync_mode_combo.setToolTip("Select sync mode")
        self._sync_mode_combo.currentTextChanged.connect(self._on_sync_mode_changed)
        statusbar.addPermanentWidget(QLabel("Sync:"))
        statusbar.addPermanentWidget(self._sync_mode_combo)

        self._sync_status_button = QPushButton("Sync Status")
        self._sync_status_button.clicked.connect(self._show_sync_status)
        statusbar.addPermanentWidget(self._sync_status_button)

        self._disk_count_label = QLabel("")
        statusbar.addPermanentWidget(self._disk_count_label)

        self._admin_label = QLabel("")
        statusbar.addPermanentWidget(self._admin_label)

        self._update_admin_status()

    def _on_sync_mode_changed(self, mode: str) -> None:
        self._session.config.sync.direction = mode
        if hasattr(self, "_status_label"):
            self._status_label.setText(f"Sync mode: {mode}")

    def _show_sync_status(self) -> None:
        manager = SyncManager(self._session.config.sync)
        status = manager.load_status()
        if not status:
            QMessageBox.information(self, "Sync Status", "No sync status recorded yet.")
            return

        summary = status.get("summary", {})
        details = (
            f"Source: {status.get('source')}\n"
            f"Target: {status.get('target')}\n"
            f"Direction: {status.get('direction')}\n"
            f"Conflict policy: {status.get('conflict_policy')}\n"
            f"Started: {status.get('started_at')}\n"
            f"Ended: {status.get('ended_at')}\n\n"
            f"Copied: {summary.get('copied', 0)}\n"
            f"Skipped: {summary.get('skipped', 0)}\n"
            f"Conflicts: {summary.get('conflicts', 0)}\n"
            f"Errors: {summary.get('errors', 0)}\n"
        )
        QMessageBox.information(self, "Sync Status", details)

    def _update_admin_status(self) -> None:
        """Update admin status indicator."""
        is_admin = self._session.platform.is_admin()
        if is_admin:
            self._admin_label.setText("Admin: Yes")
            self._admin_label.setStyleSheet("color: green;")
        else:
            self._admin_label.setText("Admin: No")
            self._admin_label.setStyleSheet("color: red;")

    def _bitlocker_supported(self) -> bool:
        return self._session.platform.name == "windows"

    def _update_bitlocker_availability(self) -> None:
        supported = self._bitlocker_supported()
        self._bitlocker_group.setVisible(supported)
        for action_key in ("bitlocker_status", "bitlocker_enable", "bitlocker_disable"):
            self._actions[action_key].setEnabled(supported)

        for button in (
            self._bitlocker_refresh_button,
            self._bitlocker_enable_button,
            self._bitlocker_disable_button,
        ):
            button.setEnabled(supported)

        if supported:
            self._bitlocker_volume_label.setText("Volume: (none)")
            self._bitlocker_status_label.setText("Select a mounted volume to view BitLocker status.")

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
            self._multi_disk_map.setDisks(inventory.disks)

            # Update status
            self._disk_count_label.setText(
                f"Disks: {inventory.total_disks} | Partitions: {inventory.total_partitions}"
            )
            self._status_label.setText("Ready")

        except Exception as e:
            self._status_label.setText(f"Error: {e}")
            self._multi_disk_map.setDisks([])

    @Slot()
    def _on_disk_selection_changed(self) -> None:
        """Handle disk/partition selection change."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            self._details_label.setText("Select a disk or partition")
            self._set_disk_map(None)
            self._selected_disk = None
            self._selected_partition = None
            self._selection_actions_panel.set_selection(None)
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if item is None:
            return

        if isinstance(item, Disk):
            self._show_disk_details(item)
            self._set_disk_map(item)
            self._selection_actions_panel.set_selection("disk", item.device_path)
        elif isinstance(item, Partition):
            self._show_partition_details(item)
            self._selection_actions_panel.set_selection("partition", item.device_path)
            parent_index = indexes[0].parent()
            parent_item = self._disk_model.getItemAtIndex(parent_index) if parent_index.isValid() else None
            if isinstance(parent_item, Disk):
                self._set_disk_map(parent_item)

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
        self._selected_disk = disk
        self._selected_partition = None
        self._refresh_bitlocker_panel()

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
        self._selected_disk = None
        self._selected_partition = partition
        self._refresh_bitlocker_panel(partition.mountpoint)

    def _set_disk_map(self, disk: Disk | None) -> None:
        """Update the disk map widget and its header."""
        self._disk_map.setDisk(disk)
        if disk is None:
            self._disk_map_subtitle.setText("Select a disk to view the map")
            return

        size_text = humanize.naturalsize(disk.size_bytes, binary=True)
        model_text = disk.model or "Unknown model"
        self._disk_map_subtitle.setText(
            f"{disk.device_path} • {model_text} • {size_text} • {disk.partition_style.name}"
        )

    @Slot(Partition)
    def _on_partition_selected(self, partition: Partition) -> None:
        """Handle partition selection from graphics view."""
        self._show_partition_details(partition)
        self._selection_actions_panel.set_selection("partition", partition.device_path)

    def _show_selection_properties(self) -> None:
        """Show the properties for the current selection."""
        if not self._details_label.text():
            QMessageBox.information(self, "Properties", "Select a disk or partition to view properties.")
            return
        QMessageBox.information(self, "Properties", self._details_label.text())

    def _current_bitlocker_mount_point(self) -> str | None:
        if self._selected_partition and self._selected_partition.mountpoint:
            return self._selected_partition.mountpoint
        return None

    def _prompt_for_bitlocker_mount_point(self) -> str | None:
        mount_point, ok = QInputDialog.getText(
            self,
            "BitLocker Volume",
            "Enter volume mount point (e.g., C:)",
            text="C:",
        )
        if ok and mount_point.strip():
            return mount_point.strip()
        return None

    def _resolve_bitlocker_mount_point(self, prompt: bool = False) -> str | None:
        mount_point = self._current_bitlocker_mount_point()
        if mount_point:
            return mount_point
        if prompt:
            return self._prompt_for_bitlocker_mount_point()
        return None

    def _refresh_bitlocker_panel(self, mount_point: str | None = None) -> None:
        if not self._bitlocker_supported():
            return

        target_mount = mount_point or self._current_bitlocker_mount_point()
        if not target_mount:
            self._bitlocker_volume_label.setText("Volume: (none)")
            self._bitlocker_status_label.setText("Select a mounted volume to view BitLocker status.")
            return

        try:
            status = self._session.platform.get_bitlocker_status(target_mount)
        except Exception as exc:
            self._bitlocker_volume_label.setText(f"Volume: {target_mount}")
            self._bitlocker_status_label.setText(f"BitLocker status unavailable: {exc}")
            return

        self._bitlocker_volume_label.setText(f"Volume: {status.mount_point}")

        if not status.success:
            self._bitlocker_status_label.setText(f"BitLocker status unavailable: {status.message}")
            return

        encryption = (
            f"{status.encryption_percentage:.0f}%"
            if status.encryption_percentage is not None
            else "Unknown"
        )
        lock_status = status.lock_status or "Unknown"
        auto_unlock = (
            "Enabled"
            if status.auto_unlock_enabled is True
            else "Disabled"
            if status.auto_unlock_enabled is False
            else "Unknown"
        )
        protectors = ", ".join(status.key_protectors) if status.key_protectors else "None"
        self._bitlocker_status_label.setText(
            "Volume Status: "
            f"{status.volume_status}\n"
            "Protection: "
            f"{status.protection_status}\n"
            f"Encryption: {encryption}\n"
            f"Lock: {lock_status}\n"
            f"Auto-unlock: {auto_unlock}\n"
            f"Protectors: {protectors}"
        )

    def _on_bitlocker_status(self) -> None:
        if not self._bitlocker_supported():
            QMessageBox.information(self, "BitLocker", "BitLocker is only available on Windows.")
            return
        mount_point = self._resolve_bitlocker_mount_point(prompt=True)
        if not mount_point:
            return
        self._refresh_bitlocker_panel(mount_point)

    def _on_bitlocker_enable(self) -> None:
        if not self._bitlocker_supported():
            QMessageBox.information(self, "BitLocker", "BitLocker is only available on Windows.")
            return
        mount_point = self._resolve_bitlocker_mount_point(prompt=True)
        if not mount_point:
            return
        confirm = QMessageBox.question(
            self,
            "Enable BitLocker",
            f"Enable BitLocker on {mount_point}?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        success, message = self._session.platform.enable_bitlocker(mount_point)
        if success:
            QMessageBox.information(self, "BitLocker", message)
        else:
            QMessageBox.warning(self, "BitLocker", message)
        self._refresh_bitlocker_panel(mount_point)

    def _on_bitlocker_disable(self) -> None:
        if not self._bitlocker_supported():
            QMessageBox.information(self, "BitLocker", "BitLocker is only available on Windows.")
            return
        mount_point = self._resolve_bitlocker_mount_point(prompt=True)
        if not mount_point:
            return
        confirm = QMessageBox.question(
            self,
            "Disable BitLocker",
            f"Disable BitLocker on {mount_point}?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        success, message = self._session.platform.disable_bitlocker(mount_point)
        if success:
            QMessageBox.information(self, "BitLocker", message)
        else:
            QMessageBox.warning(self, "BitLocker", message)
        self._refresh_bitlocker_panel(mount_point)

    def _show_context_menu(self, pos: Any) -> None:
        """Show context menu for disk/partition."""
        index = self._disk_tree.indexAt(pos)
        if not index.isValid():
            return

        item = self._disk_model.getItemAtIndex(index)
        if item is None:
            return

        menu = QMenu(self)
        menu.setIconSize(DiskForgeIcons.MENU_SIZE)

        if isinstance(item, Disk):
            clone_action = menu.addAction(
                self._actions["clone_disk"].icon(),
                "Copy Disk Wizard...",
            )
            clone_action.triggered.connect(lambda: self._clone_disk(item))

            backup_action = menu.addAction(
                self._actions["create_backup"].icon(),
                "Disk Backup...",
            )
            backup_action.triggered.connect(lambda: self._backup_device(item.device_path))

            defrag_action = menu.addAction(
                self._actions["defrag_disk"].icon(),
                "Defragment Disk...",
            )
            defrag_action.triggered.connect(lambda: self._defrag_disk(item))

            health_action = menu.addAction(
                self._actions["disk_health_check"].icon(),
                "Disk Health Check...",
            )
            health_action.triggered.connect(lambda: self._disk_health_check(item))

            speed_action = menu.addAction(
                self._actions["disk_speed_test"].icon(),
                "Disk Speed Test...",
            )
            speed_action.triggered.connect(lambda: self._disk_speed_test(item))

            bad_sector_action = menu.addAction(
                self._actions["bad_sector_scan"].icon(),
                "Bad Sector Scan...",
            )
            bad_sector_action.triggered.connect(lambda: self._bad_sector_scan(item))

            surface_action = menu.addAction(
                self._actions["surface_test"].icon(),
                "Surface Test...",
            )
            surface_action.triggered.connect(lambda: self._surface_test(item))

            menu.addSeparator()

            create_part_action = menu.addAction(
                self._actions["create_partition"].icon(),
                "Create Partition...",
            )
            create_part_action.triggered.connect(lambda: self._create_partition(item))

            menu.addSeparator()

            convert_action = menu.addAction(
                self._actions["convert_partition_style"].icon(),
                "Convert MBR/GPT...",
            )
            convert_action.triggered.connect(lambda: self._convert_partition_style(item))

            convert_system_action = menu.addAction(
                self._actions["convert_system_partition_style"].icon(),
                "Convert System Disk MBR/GPT...",
            )
            convert_system_action.triggered.connect(lambda: self._convert_system_partition_style(item))

            convert_layout_action = menu.addAction(
                self._actions["convert_disk_layout"].icon(),
                "Convert Dynamic/Basic...",
            )
            convert_layout_action.triggered.connect(lambda: self._convert_disk_layout(item))

            wipe_action = menu.addAction(
                self._actions["wipe_device"].icon(),
                "Wipe/Secure Erase...",
            )
            wipe_action.triggered.connect(self._on_wipe_device)

            secure_erase_action = menu.addAction(
                self._actions["secure_erase_ssd"].icon(),
                "SSD Secure Erase...",
            )
            secure_erase_action.triggered.connect(self._on_secure_erase_ssd)

            system_wipe_action = menu.addAction(
                self._actions["wipe_system_disk"].icon(),
                "System Disk Wipe...",
            )
            system_wipe_action.triggered.connect(self._on_wipe_system_disk)

            migrate_action = menu.addAction(
                self._actions["migrate_system"].icon(),
                "OS/System Migration...",
            )
            migrate_action.triggered.connect(lambda: self._migrate_system(item))

            recovery_action = menu.addAction(
                self._actions["partition_recovery"].icon(),
                "Partition Recovery...",
            )
            recovery_action.triggered.connect(self._on_partition_recovery)

        elif isinstance(item, Partition):
            clone_action = menu.addAction(
                self._actions["clone_partition"].icon(),
                "Copy Partition Wizard...",
            )
            clone_action.triggered.connect(lambda: self._clone_partition(item))

            backup_action = menu.addAction(
                self._actions["create_backup"].icon(),
                "Disk Backup...",
            )
            backup_action.triggered.connect(lambda: self._backup_device(item.device_path))

            menu.addSeparator()

            format_action = menu.addAction(
                self._actions["format_partition"].icon(),
                "Format...",
            )
            format_action.triggered.connect(lambda: self._format_partition(item))

            defrag_action = menu.addAction(
                self._actions["defrag_partition"].icon(),
                "Defragment...",
            )
            defrag_action.triggered.connect(lambda: self._defrag_partition(item))

            if self._bitlocker_supported():
                menu.addSeparator()
                status_action = menu.addAction(
                    self._actions["bitlocker_status"].icon(),
                    "BitLocker Status",
                )
                status_action.triggered.connect(self._on_bitlocker_status)

                enable_action = menu.addAction(
                    self._actions["bitlocker_enable"].icon(),
                    "Enable BitLocker...",
                )
                enable_action.triggered.connect(self._on_bitlocker_enable)

                disable_action = menu.addAction(
                    self._actions["bitlocker_disable"].icon(),
                    "Disable BitLocker...",
                )
                disable_action.triggered.connect(self._on_bitlocker_disable)

            delete_action = menu.addAction(
                self._actions["delete_partition"].icon(),
                "Delete",
            )
            delete_action.triggered.connect(lambda: self._delete_partition(item))

            menu.addSeparator()

            resize_action = menu.addAction(
                self._actions["resize_move_partition"].icon(),
                "Resize/Move...",
            )
            resize_action.triggered.connect(lambda: self._resize_move_partition(item))

            extend_action = menu.addAction(
                self._actions["extend_partition"].icon(),
                "Extend...",
            )
            extend_action.triggered.connect(lambda: self._extend_partition(item))

            shrink_action = menu.addAction(
                self._actions["shrink_partition"].icon(),
                "Shrink...",
            )
            shrink_action.triggered.connect(lambda: self._shrink_partition(item))

            split_action = menu.addAction(
                self._actions["split_partition"].icon(),
                "Split...",
            )
            split_action.triggered.connect(lambda: self._split_partition(item))

            merge_action = menu.addAction(
                self._actions["merge_partitions"].icon(),
                "Merge...",
            )
            merge_action.triggered.connect(self._on_merge_partitions)

            align_action = menu.addAction(
                self._actions["align_4k"].icon(),
                "Align 4K...",
            )
            align_action.triggered.connect(lambda: self._align_partition(item))

            convert_fs_action = menu.addAction(
                self._actions["convert_filesystem"].icon(),
                "Convert Filesystem (NTFS/FAT32)...",
            )
            convert_fs_action.triggered.connect(lambda: self._convert_filesystem(item))

            convert_role_action = menu.addAction(
                self._actions["convert_partition_role"].icon(),
                "Convert Primary/Logical...",
            )
            convert_role_action.triggered.connect(lambda: self._convert_partition_role(item))

            wipe_action = menu.addAction(
                self._actions["wipe_device"].icon(),
                "Wipe/Secure Erase...",
            )
            wipe_action.triggered.connect(self._on_wipe_device)

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
                "Go to the Tools tab and select Toggle Danger Mode to enable it.",
            )
            return False
        return True

    def _require_windows(self, operation: str) -> bool:
        """Ensure the current platform supports Windows-only operations."""
        if self._session.platform.name != "windows":
            QMessageBox.warning(
                self,
                "Unsupported Platform",
                f"{operation} is only available on Windows systems.",
            )
            return False
        return True

    def _find_parent_disk(self, partition: Partition) -> Disk | None:
        """Find the parent disk for a partition."""
        inventory = self._disk_model.getInventory()
        if inventory:
            for disk in inventory.disks:
                if partition in disk.partitions:
                    return disk
        return None

    def _get_selected_volume_id(self) -> str | None:
        """Return a best-effort volume identifier from the current selection."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            return None
        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            return item.mountpoint or item.device_path
        return None

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
        wizard = CreatePartitionWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

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
        wizard = FormatPartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

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
        wizard = DeletePartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_resize_move_partition(self) -> None:
        """Handle resize/move partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._resize_move_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _resize_move_partition(self, partition: Partition) -> None:
        """Resize or move a partition."""
        if not self._check_danger_mode():
            return

        if partition.is_mounted:
            QMessageBox.critical(
                self,
                "Partition Mounted",
                f"Partition is mounted at {partition.mountpoint}. Unmount it first.",
            )
            return

        wizard = ResizeMovePartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_resize_move_dynamic_volume(self) -> None:
        """Handle resize/move dynamic volume action."""
        if not self._check_danger_mode():
            return

        wizard = ResizeMoveDynamicVolumeWizard(
            self._session,
            self._get_selected_volume_id(),
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_merge_partitions(self) -> None:
        """Handle merge partitions action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk or partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if not disk:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk or partition.")
            return

        if len(disk.partitions) < 2:
            QMessageBox.warning(self, "Not Enough Partitions", "Select a disk with at least two partitions.")
            return

        if not self._check_danger_mode():
            return

        wizard = MergePartitionsWizard(
            self._session,
            disk.partitions,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_split_partition(self) -> None:
        """Handle split partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._split_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _split_partition(self, partition: Partition) -> None:
        """Split a partition."""
        if not self._check_danger_mode():
            return

        if partition.is_mounted:
            QMessageBox.critical(
                self,
                "Partition Mounted",
                f"Partition is mounted at {partition.mountpoint}. Unmount it first.",
            )
            return

        wizard = SplitPartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_extend_partition(self) -> None:
        """Handle extend partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._extend_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _extend_partition(self, partition: Partition) -> None:
        """Extend a partition."""
        if not self._check_danger_mode():
            return

        if partition.is_mounted:
            QMessageBox.critical(
                self,
                "Partition Mounted",
                f"Partition is mounted at {partition.mountpoint}. Unmount it first.",
            )
            return

        wizard = ExtendPartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_shrink_partition(self) -> None:
        """Handle shrink partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._shrink_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _shrink_partition(self, partition: Partition) -> None:
        """Shrink a partition."""
        if not self._check_danger_mode():
            return

        if partition.is_mounted:
            QMessageBox.critical(
                self,
                "Partition Mounted",
                f"Partition is mounted at {partition.mountpoint}. Unmount it first.",
            )
            return

        wizard = ShrinkPartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_extend_dynamic_volume(self) -> None:
        """Handle extend dynamic volume action."""
        if not self._check_danger_mode():
            return

        wizard = ExtendDynamicVolumeWizard(
            self._session,
            self._get_selected_volume_id(),
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_shrink_dynamic_volume(self) -> None:
        """Handle shrink dynamic volume action."""
        if not self._check_danger_mode():
            return

        wizard = ShrinkDynamicVolumeWizard(
            self._session,
            self._get_selected_volume_id(),
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_allocate_free_space(self) -> None:
        """Handle allocate free space action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk or partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if not disk:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk or partition.")
            return

        if len(disk.partitions) < 2:
            QMessageBox.warning(self, "Not Enough Partitions", "Select a disk with at least two partitions.")
            return

        if not self._check_danger_mode():
            return

        wizard = AllocateFreeSpaceWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_one_click_adjust_space(self) -> None:
        """Handle one-click adjust space action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk or partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if not disk:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk or partition.")
            return

        if not self._check_danger_mode():
            return

        wizard = OneClickAdjustSpaceWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_quick_partition(self) -> None:
        """Handle quick partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if not isinstance(item, Disk):
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")
            return

        if item.is_system_disk:
            QMessageBox.critical(self, "System Disk", "Cannot partition the system disk.")
            return

        if not self._check_danger_mode():
            return

        wizard = QuickPartitionWizard(
            self._session,
            item,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_edit_partition_attributes(self) -> None:
        """Handle edit partition attributes action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if not isinstance(item, Partition):
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")
            return

        if not self._check_danger_mode():
            return

        wizard = PartitionAttributesWizard(
            self._session,
            item,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_initialize_disk(self) -> None:
        """Handle initialize disk action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if not isinstance(item, Disk):
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")
            return

        if item.is_system_disk:
            QMessageBox.critical(self, "System Disk", "Cannot initialize the system disk.")
            return

        if not self._check_danger_mode():
            return

        wizard = InitializeDiskWizard(
            self._session,
            item,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_wipe_device(self) -> None:
        """Handle wipe/secure erase action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk or partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if not self._check_danger_mode():
            return

        if isinstance(item, Disk):
            if item.is_system_disk:
                QMessageBox.critical(self, "System Disk", "Cannot wipe the system disk.")
                return
            target_path = item.device_path
        elif isinstance(item, Partition):
            if item.is_mounted:
                QMessageBox.critical(
                    self,
                    "Partition Mounted",
                    f"Partition is mounted at {item.mountpoint}. Unmount it first.",
                )
                return
            target_path = item.device_path
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk or partition.")
            return

        wizard = WipeWizard(
            self._session,
            target_path,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_wipe_system_disk(self) -> None:
        """Handle system disk wipe action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if not isinstance(item, Disk):
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")
            return

        if not item.is_system_disk:
            QMessageBox.warning(self, "Not System Disk", "Selected disk is not marked as the system disk.")
            return

        if not self._check_danger_mode():
            return

        wizard = SystemDiskWipeWizard(
            self._session,
            item,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_secure_erase_ssd(self) -> None:
        """Handle SSD secure erase action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if not isinstance(item, Disk):
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")
            return

        if item.disk_type not in {DiskType.SSD, DiskType.NVME}:
            QMessageBox.warning(self, "Unsupported Disk", "Secure erase is only supported for SSD or NVMe disks.")
            return

        if item.is_system_disk:
            QMessageBox.critical(self, "System Disk", "Cannot secure erase the system disk.")
            return

        if not self._check_danger_mode():
            return

        wizard = SSDSecureEraseWizard(
            self._session,
            item,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_partition_recovery(self) -> None:
        """Handle partition recovery action."""
        inventory = self._disk_model.getInventory()
        if not inventory or not inventory.disks:
            QMessageBox.warning(self, "No Disks", "No disks available for recovery.")
            return

        wizard = PartitionRecoveryWizard(
            self._session,
            inventory.disks,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_file_recovery(self) -> None:
        """Handle file recovery action."""
        wizard = FileRecoveryWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_shred_files(self) -> None:
        """Handle shred files action."""
        if not self._check_danger_mode():
            return

        wizard = ShredWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_defrag_disk(self) -> None:
        """Handle defragment disk action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._defrag_disk(item)
            return
        if isinstance(item, Partition):
            disk = self._find_parent_disk(item)
            if disk:
                self._defrag_disk(disk)
                return
        QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _defrag_disk(self, disk: Disk) -> None:
        """Defragment a disk."""
        if not disk.partitions:
            QMessageBox.warning(self, "No Partitions", "No partitions available to defragment.")
            return

        wizard = DefragDiskWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_disk_health_check(self) -> None:
        """Handle disk health check action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if disk:
            self._disk_health_check(disk)
            return
        QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _disk_health_check(self, disk: Disk) -> None:
        wizard = DiskHealthCheckWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_disk_speed_test(self) -> None:
        """Handle disk speed test action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if disk:
            self._disk_speed_test(disk)
            return
        QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _disk_speed_test(self, disk: Disk) -> None:
        wizard = DiskSpeedTestWizard(
            self._session,
            disk,
            self._submit_job,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_bad_sector_scan(self) -> None:
        """Handle bad sector scan action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if disk:
            self._bad_sector_scan(disk)
            return
        QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _bad_sector_scan(self, disk: Disk) -> None:
        wizard = BadSectorScanWizard(
            self._session,
            disk,
            self._submit_job,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_surface_test(self) -> None:
        """Handle surface test action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        disk = item if isinstance(item, Disk) else self._find_parent_disk(item) if isinstance(item, Partition) else None
        if disk:
            self._surface_test(disk)
            return
        QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _surface_test(self, disk: Disk) -> None:
        wizard = SurfaceTestWizard(
            self._session,
            disk,
            self._submit_job,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_defrag_partition(self) -> None:
        """Handle defragment partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._defrag_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _defrag_partition(self, partition: Partition) -> None:
        """Defragment a partition."""
        if not partition.mountpoint and not partition.drive_letter:
            QMessageBox.warning(
                self,
                "Partition Not Mounted",
                "Defragmentation requires a mounted partition or drive letter.",
            )
            return

        wizard = DefragPartitionWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_align_4k(self) -> None:
        """Handle align 4K action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._align_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _align_partition(self, partition: Partition) -> None:
        """Align a partition to 4K boundaries."""
        if not self._check_danger_mode():
            return

        wizard = Align4KWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_convert_partition_style(self) -> None:
        """Handle convert partition style action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._convert_partition_style(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _convert_partition_style(self, disk: Disk) -> None:
        """Convert disk partition style."""
        if not self._check_danger_mode():
            return

        if disk.is_system_disk:
            QMessageBox.critical(self, "System Disk", "Cannot convert the system disk.")
            return

        wizard = ConvertPartitionStyleWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_convert_system_partition_style(self) -> None:
        """Handle system disk partition style conversion."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._convert_system_partition_style(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _convert_system_partition_style(self, disk: Disk) -> None:
        """Convert a system disk between MBR/GPT with safety checks."""
        if not self._check_danger_mode():
            return

        if not disk.is_system_disk:
            QMessageBox.warning(self, "Not System Disk", "Select the system disk for this conversion.")
            return

        wizard = ConvertSystemPartitionStyleWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_convert_disk_layout(self) -> None:
        """Handle disk layout conversion."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._convert_disk_layout(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _convert_disk_layout(self, disk: Disk) -> None:
        """Convert a disk between basic/dynamic."""
        if not self._check_danger_mode():
            return

        if disk.is_system_disk:
            QMessageBox.critical(self, "System Disk", "Cannot convert the system disk layout.")
            return

        wizard = ConvertDiskLayoutWizard(
            self._session,
            disk,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_convert_filesystem(self) -> None:
        """Handle filesystem conversion action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._convert_filesystem(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _convert_filesystem(self, partition: Partition) -> None:
        """Convert a partition filesystem between NTFS/FAT32."""
        if not self._check_danger_mode():
            return

        wizard = ConvertFilesystemWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_convert_partition_role(self) -> None:
        """Handle partition role conversion."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._convert_partition_role(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _convert_partition_role(self, partition: Partition) -> None:
        """Convert a partition between primary/logical."""
        if not self._check_danger_mode():
            return

        wizard = ConvertPartitionRoleWizard(
            self._session,
            partition,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_migrate_system(self) -> None:
        """Handle OS/system migration action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a source disk first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Disk):
            self._migrate_system(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a disk, not a partition.")

    def _migrate_system(self, source: Disk) -> None:
        """Migrate OS/system to another disk."""
        if not self._check_danger_mode():
            return

        if not source.is_system_disk:
            QMessageBox.warning(self, "Not a System Disk", "Select the system disk as the source.")
            return

        inventory = self._disk_model.getInventory()
        if not inventory:
            return

        target_disks = [
            d
            for d in inventory.disks
            if d.device_path != source.device_path and not d.is_system_disk
        ]

        if not target_disks:
            QMessageBox.warning(self, "No Target", "No suitable target disks available.")
            return

        wizard = SystemMigrationWizard(
            self._session,
            source,
            target_disks,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_free_space(self) -> None:
        """Handle free space scan action."""
        wizard = FreeSpaceWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_junk_cleanup(self) -> None:
        """Handle junk cleanup action."""
        if not self._check_danger_mode():
            return
        wizard = JunkCleanupWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_large_files(self) -> None:
        """Handle large file discovery action."""
        wizard = LargeFilesWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_duplicate_files(self) -> None:
        """Handle duplicate file discovery action."""
        wizard = DuplicateFilesWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_move_applications(self) -> None:
        """Handle move applications action."""
        if not self._check_danger_mode():
            return
        wizard = MoveApplicationWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

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

        target_disks = [
            d
            for d in inventory.disks
            if d.device_path != source.device_path and not d.is_system_disk
        ]

        if not target_disks:
            QMessageBox.warning(self, "No Target", "No suitable target disks available.")
            return
        wizard = CloneDiskWizard(
            self._session,
            source,
            target_disks,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_clone_partition(self) -> None:
        """Handle clone partition action."""
        indexes = self._disk_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "No Selection", "Please select a partition first.")
            return

        item = self._disk_model.getItemAtIndex(indexes[0])
        if isinstance(item, Partition):
            self._clone_partition(item)
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a partition, not a disk.")

    def _clone_partition(self, source: Partition) -> None:
        """Clone a partition."""
        if not self._check_danger_mode():
            return
        wizard = ClonePartitionWizard(
            self._session,
            source,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

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
        wizard = CreateBackupWizard(
            self._session,
            source_path,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_system_backup(self) -> None:
        """Handle system backup action."""
        wizard = SystemBackupWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_restore_backup(self) -> None:
        """Handle restore backup action."""
        if not self._check_danger_mode():
            return
        wizard = RestoreBackupWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_create_rescue(self) -> None:
        """Handle create rescue media action."""
        wizard = RescueMediaWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_integrate_recovery_env(self) -> None:
        """Handle WinRE integration action."""
        if not self._require_windows("WinRE integration"):
            return
        wizard = IntegrateRecoveryEnvironmentWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_boot_repair(self) -> None:
        """Handle boot repair action."""
        if not self._require_windows("Boot repair"):
            return
        if not self._check_danger_mode():
            return
        wizard = BootRepairWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_rebuild_mbr(self) -> None:
        """Handle rebuild MBR action."""
        if not self._require_windows("MBR rebuild"):
            return
        if not self._check_danger_mode():
            return
        wizard = RebuildMBRWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_uefi_boot_manager(self) -> None:
        """Handle UEFI boot options manager action."""
        if not self._require_windows("UEFI boot options manager"):
            return
        wizard = UEFIBootOptionsWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_windows_to_go(self) -> None:
        """Handle Windows To Go creator action."""
        if not self._require_windows("Windows To Go"):
            return
        if not self._check_danger_mode():
            return
        wizard = WindowsToGoWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _on_reset_windows_password(self) -> None:
        """Handle Windows password reset action."""
        if not self._require_windows("Windows password reset"):
            return
        if not self._check_danger_mode():
            return
        wizard = ResetWindowsPasswordWizard(
            self._session,
            self._status_label.setText,
            self,
        )
        self._run_wizard(wizard)

    def _run_wizard(self, wizard: Any) -> None:
        wizard.exec()
        if wizard.operation_success and wizard.refresh_on_success:
            self._refresh_inventory()

    def _on_cancel_job(self) -> None:
        """Cancel current job."""
        if not self._active_job_id:
            self._status_label.setText("No running job to cancel")
            return
        if self._session.cancel_job(self._active_job_id):
            self._status_label.setText("Cancellation requested")
        else:
            self._status_label.setText("Unable to cancel job")

    def _on_pause_job(self) -> None:
        """Pause current job."""
        if not self._active_job_id:
            self._status_label.setText("No running job to pause")
            return
        if self._session.job_runner.pause(self._active_job_id):
            self._status_label.setText("Job paused")
        else:
            self._status_label.setText("Unable to pause job")

    def _on_resume_job(self) -> None:
        """Resume current job."""
        if not self._active_job_id:
            self._status_label.setText("No paused job to resume")
            return
        if self._session.job_runner.resume(self._active_job_id):
            self._status_label.setText("Job resumed")
        else:
            self._status_label.setText("Unable to resume job")

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
