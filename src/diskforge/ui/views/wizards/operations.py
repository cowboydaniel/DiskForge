"""
QWizard-based flows for disk operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Any

from PySide6.QtWidgets import (
    QWizard,
    QWizardPage,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QHBoxLayout,
    QFormLayout,
    QTextEdit,
    QCheckBox,
)

from diskforge.core.models import (
    AlignOptions,
    CloneMode,
    CompressionLevel,
    ConvertDiskOptions,
    ConvertDiskLayoutOptions,
    ConvertFilesystemOptions,
    ConvertPartitionRoleOptions,
    ConvertSystemDiskOptions,
    Disk,
    DiskLayout,
    FileSystem,
    FormatOptions,
    MergePartitionsOptions,
    MigrationOptions,
    AllocateFreeSpaceOptions,
    OneClickAdjustOptions,
    QuickPartitionOptions,
    PartitionAttributeOptions,
    InitializeDiskOptions,
    DynamicVolumeResizeMoveOptions,
    DuplicateRemovalOptions,
    DuplicateScanOptions,
    FileRecoveryOptions,
    FileRemovalOptions,
    Partition,
    PartitionRole,
    PartitionCreateOptions,
    PartitionRecoveryOptions,
    WinREIntegrationOptions,
    BootRepairOptions,
    RebuildMBROptions,
    UEFIBootOptions,
    WindowsToGoOptions,
    WindowsPasswordResetOptions,
    PartitionStyle,
    FreeSpaceOptions,
    JunkCleanupOptions,
    LargeFileScanOptions,
    MoveApplicationOptions,
    ResizeMoveOptions,
    SplitPartitionOptions,
    ShredOptions,
    SSDSecureEraseOptions,
    SystemDiskWipeOptions,
    WipeOptions,
)
from diskforge.core.session import Session
from diskforge.core.safety import DangerMode
from diskforge.core.job import Job
from diskforge.plugins.operations import (
    BadSectorScanJob,
    SurfaceTestJob,
    DiskSpeedTestJob,
)


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str


def _parse_size_mib(value: str) -> int | None:
    try:
        size_mib = int(value.strip())
    except ValueError:
        return None
    if size_mib <= 0:
        return None
    return size_mib * 1024 * 1024


def _format_bytes(size_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TiB"


class ConfirmationPage(QWizardPage):
    """Wizard page to confirm destructive operations."""

    def __init__(self, title: str, message: str, confirmation: str, parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self._confirmation = confirmation

        layout = QVBoxLayout(self)
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        self._confirm_label = QLabel()
        self._confirm_label.setWordWrap(True)
        self._confirm_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._confirm_label)
        self.set_confirmation(confirmation)

        self._confirm_input = QLineEdit()
        self._confirm_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._confirm_input)

    def _on_text_changed(self) -> None:
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._confirm_input.text() == self._confirmation

    def set_confirmation(self, confirmation: str) -> None:
        self._confirmation = confirmation
        self._confirm_label.setText(
            f"Type the confirmation phrase to continue:\n\n{confirmation}"
        )
        self._confirm_input.clear()
        self.completeChanged.emit()


class DynamicConfirmationPage(ConfirmationPage):
    """Confirmation page that updates its phrase on entry."""

    def __init__(
        self,
        title: str,
        message: str,
        confirmation_supplier: Callable[[], str],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(title, message, "", parent)
        self._confirmation_supplier = confirmation_supplier

    def initializePage(self) -> None:
        self.set_confirmation(self._confirmation_supplier())


class OutputPathPage(QWizardPage):
    """Wizard page to select a path."""

    def __init__(self, title: str, label: str, dialog_title: str, parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self._dialog_title = dialog_title

        layout = QVBoxLayout(self)
        helper = QLabel(label)
        helper.setWordWrap(True)
        layout.addWidget(helper)

        row = QHBoxLayout()
        self._path_input = QLineEdit()
        self._path_input.textChanged.connect(self._on_text_changed)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self._path_input)
        row.addWidget(browse_btn)
        layout.addLayout(row)

    def _browse(self) -> None:
        raise NotImplementedError

    def _on_text_changed(self) -> None:
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return bool(self._path_input.text().strip())

    def path(self) -> str:
        return self._path_input.text().strip()


class SaveFilePage(OutputPathPage):
    def __init__(self, title: str, label: str, dialog_title: str, filters: str, parent: QWizard | None = None) -> None:
        super().__init__(title, label, dialog_title, parent)
        self._filters = filters

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self._dialog_title, "", self._filters)
        if path:
            self._path_input.setText(path)


class OpenFilePage(OutputPathPage):
    def __init__(self, title: str, label: str, dialog_title: str, filters: str, parent: QWizard | None = None) -> None:
        super().__init__(title, label, dialog_title, parent)
        self._filters = filters

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._dialog_title, "", self._filters)
        if path:
            self._path_input.setText(path)


class DirectoryPage(OutputPathPage):
    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self._dialog_title)
        if path:
            self._path_input.setText(path)


class PathEntryPage(QWizardPage):
    """Wizard page to enter a file or folder path."""

    def __init__(
        self,
        title: str,
        label: str,
        file_dialog_title: str,
        dir_dialog_title: str,
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self._file_dialog_title = file_dialog_title
        self._dir_dialog_title = dir_dialog_title

        layout = QVBoxLayout(self)
        helper = QLabel(label)
        helper.setWordWrap(True)
        layout.addWidget(helper)

        row = QHBoxLayout()
        self._path_input = QLineEdit()
        self._path_input.textChanged.connect(self._on_text_changed)
        browse_file_btn = QPushButton("Browse File...")
        browse_file_btn.clicked.connect(self._browse_file)
        browse_dir_btn = QPushButton("Browse Folder...")
        browse_dir_btn.clicked.connect(self._browse_dir)
        row.addWidget(self._path_input)
        row.addWidget(browse_file_btn)
        row.addWidget(browse_dir_btn)
        layout.addLayout(row)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self._file_dialog_title, "")
        if path:
            self._path_input.setText(path)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self._dir_dialog_title)
        if path:
            self._path_input.setText(path)

    def _on_text_changed(self) -> None:
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return bool(self._path_input.text().strip())

    def path(self) -> str:
        return self._path_input.text().strip()


class OperationResultPage(QWizardPage):
    """Final wizard page to run the operation and show results."""

    def __init__(
        self,
        title: str,
        operation: Callable[[], OperationResult],
        status_callback: Callable[[str], None],
        status_message: str,
        success_follow_up: Callable[[], None] | None = None,
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self._operation = operation
        self._status_callback = status_callback
        self._status_message = status_message
        self._success_follow_up = success_follow_up
        self._ran = False

        layout = QVBoxLayout(self)
        self._status_label = QLabel("Ready to execute.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(140)
        layout.addWidget(self._details)

    def initializePage(self) -> None:
        if self._ran:
            return
        self._ran = True

        self._status_callback(self._status_message)
        result = self._operation()
        self._status_callback("Ready")

        wizard = self.wizard()
        if wizard is not None:
            wizard.operation_success = result.success
            wizard.operation_message = result.message

        outcome = "Success" if result.success else "Error"
        self._status_label.setText(f"{outcome}: {result.message}")
        self._details.setPlainText(result.message)

        if result.success and self._success_follow_up:
            self._success_follow_up()


class JobSubmissionPage(QWizardPage):
    """Final wizard page to submit a background job."""

    def __init__(
        self,
        title: str,
        build_job: Callable[[], Job[Any]],
        submit_job: Callable[[Job[Any]], None],
        status_callback: Callable[[str], None],
        status_message: str,
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle(title)
        self._build_job = build_job
        self._submit_job = submit_job
        self._status_callback = status_callback
        self._status_message = status_message
        self._job: Job[Any] | None = None

        layout = QVBoxLayout(self)
        self._status_label = QLabel("Ready to queue job.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(140)
        layout.addWidget(self._details)

    def initializePage(self) -> None:
        if self._job is not None:
            return

        self._status_callback(self._status_message)
        self._job = self._build_job()
        self._submit_job(self._job)
        self._status_callback("Ready")

        wizard = self.wizard()
        if wizard is not None:
            wizard.operation_success = True
            wizard.operation_message = f"Queued job {self._job.name}"

        self._status_label.setText(
            f"Queued job {self._job.name} (ID: {self._job.id[:8]})"
        )
        self._details.setPlainText(self._job.get_plan())


class DiskForgeWizard(QWizard):
    """Base wizard with status tracking."""

    def __init__(self, parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.operation_success = False
        self.operation_message = ""
        self.refresh_on_success = False


class CreatePartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Partition")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        fs_page = QWizardPage()
        fs_page.setTitle("Select Filesystem")
        fs_layout = QFormLayout(fs_page)
        self._filesystem_combo = QComboBox()
        self._filesystem_combo.addItems(["ext4", "xfs", "btrfs", "ntfs", "fat32"])
        fs_layout.addRow("Filesystem:", self._filesystem_combo)
        fs_layout.addRow(QLabel(f"Target disk: {disk.device_path}"))

        confirm_str = session.safety.generate_confirmation_string(disk.device_path)
        confirm_page = ConfirmationPage(
            "Confirm Partition Creation",
            f"This will modify the partition table on {disk.device_path}.",
            confirm_str,
        )

        result_page = OperationResultPage(
            "Create Partition",
            self._create_partition,
            status_callback,
            f"Creating partition on {disk.device_path}...",
        )

        self.addPage(fs_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _create_partition(self) -> OperationResult:
        fs_map = {
            "ext4": FileSystem.EXT4,
            "xfs": FileSystem.XFS,
            "btrfs": FileSystem.BTRFS,
            "ntfs": FileSystem.NTFS,
            "fat32": FileSystem.FAT32,
        }
        fs_key = self._filesystem_combo.currentText()
        options = PartitionCreateOptions(
            disk_path=self._disk.device_path,
            filesystem=fs_map[fs_key],
        )
        success, message = self._session.platform.create_partition(options)
        return OperationResult(success=success, message=message)


class FormatPartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Format Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        fs_page = QWizardPage()
        fs_page.setTitle("Select Filesystem")
        fs_layout = QFormLayout(fs_page)
        self._filesystem_combo = QComboBox()
        self._filesystem_combo.addItems(["ext4", "xfs", "btrfs", "ntfs", "fat32", "exfat"])
        fs_layout.addRow("Filesystem:", self._filesystem_combo)
        fs_layout.addRow(QLabel(f"Target partition: {partition.device_path}"))

        confirm_str = session.safety.generate_confirmation_string(partition.device_path)
        confirm_page = ConfirmationPage(
            "Confirm Format",
            f"This will ERASE ALL DATA on {partition.device_path}.",
            confirm_str,
        )

        result_page = OperationResultPage(
            "Format Partition",
            self._format_partition,
            status_callback,
            f"Formatting {partition.device_path}...",
        )

        self.addPage(fs_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _format_partition(self) -> OperationResult:
        fs_map = {
            "ext4": FileSystem.EXT4,
            "xfs": FileSystem.XFS,
            "btrfs": FileSystem.BTRFS,
            "ntfs": FileSystem.NTFS,
            "fat32": FileSystem.FAT32,
            "exfat": FileSystem.EXFAT,
        }
        fs_key = self._filesystem_combo.currentText()
        options = FormatOptions(
            partition_path=self._partition.device_path,
            filesystem=fs_map[fs_key],
        )
        success, message = self._session.platform.format_partition(options)
        return OperationResult(success=success, message=message)


class DeletePartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        confirm_str = session.safety.generate_confirmation_string(partition.device_path)
        confirm_page = ConfirmationPage(
            "Confirm Delete",
            f"This will PERMANENTLY DELETE {partition.device_path}.",
            confirm_str,
        )

        result_page = OperationResultPage(
            "Delete Partition",
            self._delete_partition,
            status_callback,
            f"Deleting {partition.device_path}...",
        )

        self.addPage(confirm_page)
        self.addPage(result_page)

    def _delete_partition(self) -> OperationResult:
        success, message = self._session.platform.delete_partition(self._partition.device_path)
        return OperationResult(success=success, message=message)


class CloneDiskWizard(DiskForgeWizard):
    def __init__(
        self,
        session: Session,
        source: Disk,
        targets: Iterable[Disk],
        status_callback: Callable[[str], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clone Disk")
        self._session = session
        self._source = source
        self._targets = list(targets)
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = QWizardPage()
        target_page.setTitle("Select Target Disk")
        target_layout = QFormLayout(target_page)
        self._target_combo = QComboBox()
        for disk in self._targets:
            self._target_combo.addItem(f"{disk.device_path} ({disk.model})", disk.device_path)
        target_layout.addRow("Target disk:", self._target_combo)
        target_layout.addRow(QLabel(f"Source disk: {source.device_path}"))

        options_page = QWizardPage()
        options_page.setTitle("Clone Options")
        options_layout = QFormLayout(options_page)
        self._clone_mode_combo = QComboBox()
        self._clone_mode_combo.addItem("Intelligent clone (recommended)", CloneMode.INTELLIGENT)
        self._clone_mode_combo.addItem("Sector-by-sector clone", CloneMode.SECTOR_BY_SECTOR)
        self._clone_validate_check = QCheckBox("Validate after clone")
        self._clone_validate_check.setChecked(True)
        self._clone_schedule_combo = QComboBox()
        self._clone_schedule_combo.addItem("Run once (no schedule)", None)
        self._clone_schedule_combo.addItem("Daily", "Daily")
        self._clone_schedule_combo.addItem("Weekly", "Weekly")
        self._clone_schedule_combo.addItem("Monthly", "Monthly")
        options_layout.addRow("Clone mode:", self._clone_mode_combo)
        options_layout.addRow("Schedule:", self._clone_schedule_combo)
        options_layout.addRow("", self._clone_validate_check)

        confirm_page = ConfirmationPage(
            "Confirm Clone",
            "This will DESTROY ALL DATA on the target disk.",
            session.safety.generate_confirmation_string(self._target_combo.currentData()),
        )
        self._target_combo.currentIndexChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._target_combo.currentData())
            )
        )

        result_page = OperationResultPage(
            "Clone Disk",
            self._clone_disk,
            status_callback,
            "Cloning disk...",
        )

        self.addPage(target_page)
        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _clone_disk(self) -> OperationResult:
        target_path = self._target_combo.currentData()
        success, message = self._session.platform.clone_disk(
            self._source.device_path,
            target_path,
            verify=self._clone_validate_check.isChecked(),
            mode=self._clone_mode_combo.currentData(),
            schedule=self._clone_schedule_combo.currentData(),
        )
        return OperationResult(success=success, message=message)


class ClonePartitionWizard(DiskForgeWizard):
    def __init__(
        self,
        session: Session,
        source: Partition,
        status_callback: Callable[[str], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clone Partition")
        self._session = session
        self._source = source
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = QWizardPage()
        target_page.setTitle("Target Partition")
        target_layout = QFormLayout(target_page)
        self._target_input = QLineEdit()
        self._target_input.textChanged.connect(target_page.completeChanged)
        target_page.isComplete = lambda: bool(self._target_input.text().strip())
        target_layout.addRow("Target path:", self._target_input)
        target_layout.addRow(QLabel(f"Source partition: {source.device_path}"))

        options_page = QWizardPage()
        options_page.setTitle("Clone Options")
        options_layout = QFormLayout(options_page)
        self._clone_mode_combo = QComboBox()
        self._clone_mode_combo.addItem("Intelligent clone (recommended)", CloneMode.INTELLIGENT)
        self._clone_mode_combo.addItem("Sector-by-sector clone", CloneMode.SECTOR_BY_SECTOR)
        self._clone_validate_check = QCheckBox("Validate after clone")
        self._clone_validate_check.setChecked(True)
        self._clone_schedule_combo = QComboBox()
        self._clone_schedule_combo.addItem("Run once (no schedule)", None)
        self._clone_schedule_combo.addItem("Daily", "Daily")
        self._clone_schedule_combo.addItem("Weekly", "Weekly")
        self._clone_schedule_combo.addItem("Monthly", "Monthly")
        options_layout.addRow("Clone mode:", self._clone_mode_combo)
        options_layout.addRow("Schedule:", self._clone_schedule_combo)
        options_layout.addRow("", self._clone_validate_check)

        confirm_page = ConfirmationPage(
            "Confirm Clone",
            "This will DESTROY ALL DATA on the target partition.",
            session.safety.generate_confirmation_string(self._target_input.text().strip()),
        )
        self._target_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._target_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Clone Partition",
            self._clone_partition,
            status_callback,
            "Cloning partition...",
        )

        self.addPage(target_page)
        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _clone_partition(self) -> OperationResult:
        target_path = self._target_input.text().strip()
        success, message = self._session.platform.clone_partition(
            self._source.device_path,
            target_path,
            verify=self._clone_validate_check.isChecked(),
            mode=self._clone_mode_combo.currentData(),
            schedule=self._clone_schedule_combo.currentData(),
        )
        return OperationResult(success=success, message=message)


class CreateBackupWizard(DiskForgeWizard):
    def __init__(self, session: Session, source_path: str, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Backup")
        self._session = session
        self._source_path = source_path
        self._status_callback = status_callback

        output_page = SaveFilePage(
            "Save Backup",
            f"Select output image for {source_path}.",
            "Save Backup Image",
            "Disk Images (*.img *.img.zst *.img.gz);;All Files (*)",
        )

        compress_page = QWizardPage()
        compress_page.setTitle("Backup Options")
        compress_layout = QFormLayout(compress_page)
        self._compression_combo = QComboBox()
        self._compression_combo.addItems(["zstd (recommended)", "gzip", "none"])
        self._compression_level_combo = QComboBox()
        self._compression_level_combo.addItem("Balanced", CompressionLevel.BALANCED)
        self._compression_level_combo.addItem("Fast", CompressionLevel.FAST)
        self._compression_level_combo.addItem("Maximum", CompressionLevel.MAXIMUM)
        self._backup_mode_combo = QComboBox()
        self._backup_mode_combo.addItem("Intelligent backup (recommended)", CloneMode.INTELLIGENT)
        self._backup_mode_combo.addItem("Sector-by-sector backup", CloneMode.SECTOR_BY_SECTOR)
        self._backup_validate_check = QCheckBox("Validate backup after creation")
        self._backup_validate_check.setChecked(True)
        self._backup_schedule_combo = QComboBox()
        self._backup_schedule_combo.addItem("Run once (no schedule)", None)
        self._backup_schedule_combo.addItem("Daily", "Daily")
        self._backup_schedule_combo.addItem("Weekly", "Weekly")
        self._backup_schedule_combo.addItem("Monthly", "Monthly")
        compress_layout.addRow("Compression:", self._compression_combo)
        compress_layout.addRow("Compression level:", self._compression_level_combo)
        compress_layout.addRow("Backup mode:", self._backup_mode_combo)
        compress_layout.addRow("Schedule:", self._backup_schedule_combo)
        compress_layout.addRow("", self._backup_validate_check)
        self._compression_combo.currentTextChanged.connect(self._on_compression_changed)
        self._on_compression_changed(self._compression_combo.currentText())

        result_page = OperationResultPage(
            "Create Backup",
            lambda: self._create_backup(output_page.path()),
            status_callback,
            f"Creating backup of {source_path}...",
        )

        self.addPage(output_page)
        self.addPage(compress_page)
        self.addPage(result_page)

    def _create_backup(self, output_path: str) -> OperationResult:
        compress_map = {
            "zstd (recommended)": "zstd",
            "gzip": "gzip",
            "none": None,
        }
        compression = compress_map[self._compression_combo.currentText()]
        compression_level = self._compression_level_combo.currentData() if compression else None
        success, message, _info = self._session.platform.create_image(
            self._source_path,
            Path(output_path),
            compression=compression,
            compression_level=compression_level,
            verify=self._backup_validate_check.isChecked(),
            mode=self._backup_mode_combo.currentData(),
            schedule=self._backup_schedule_combo.currentData(),
        )
        return OperationResult(success=success, message=message)

    def _on_compression_changed(self, selection: str) -> None:
        self._compression_level_combo.setEnabled(selection != "none")


class SystemBackupWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("System Backup")
        self._session = session
        self._status_callback = status_callback

        output_page = DirectoryPage(
            "Backup Destination",
            "Select the output folder for the system backup.",
            "Select Backup Folder",
        )

        options_page = QWizardPage()
        options_page.setTitle("System Backup Options")
        options_layout = QFormLayout(options_page)
        self._compression_combo = QComboBox()
        self._compression_combo.addItems(["zstd (recommended)", "gzip", "none"])
        self._compression_level_combo = QComboBox()
        self._compression_level_combo.addItem("Balanced", CompressionLevel.BALANCED)
        self._compression_level_combo.addItem("Fast", CompressionLevel.FAST)
        self._compression_level_combo.addItem("Maximum", CompressionLevel.MAXIMUM)
        self._backup_mode_combo = QComboBox()
        self._backup_mode_combo.addItem("Intelligent backup (recommended)", CloneMode.INTELLIGENT)
        self._backup_mode_combo.addItem("Sector-by-sector backup", CloneMode.SECTOR_BY_SECTOR)
        self._backup_validate_check = QCheckBox("Validate backup after creation")
        self._backup_validate_check.setChecked(True)
        options_layout.addRow("Compression:", self._compression_combo)
        options_layout.addRow("Compression level:", self._compression_level_combo)
        options_layout.addRow("Backup mode:", self._backup_mode_combo)
        options_layout.addRow("", self._backup_validate_check)
        self._compression_combo.currentTextChanged.connect(self._on_compression_changed)
        self._on_compression_changed(self._compression_combo.currentText())

        result_page = OperationResultPage(
            "System Backup",
            lambda: self._create_system_backup(output_page.path()),
            status_callback,
            "Creating system backup...",
        )

        self.addPage(output_page)
        self.addPage(options_page)
        self.addPage(result_page)

    def _create_system_backup(self, output_path: str) -> OperationResult:
        compress_map = {
            "zstd (recommended)": "zstd",
            "gzip": "gzip",
            "none": None,
        }
        compression = compress_map[self._compression_combo.currentText()]
        compression_level = self._compression_level_combo.currentData() if compression else None
        success, message, _info = self._session.platform.create_system_backup(
            Path(output_path),
            compression=compression,
            compression_level=compression_level,
            verify=self._backup_validate_check.isChecked(),
            mode=self._backup_mode_combo.currentData(),
            profile=self._session.config.system_backup,
        )
        return OperationResult(success=success, message=message)

    def _on_compression_changed(self, selection: str) -> None:
        self._compression_level_combo.setEnabled(selection != "none")


class RestoreBackupWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restore Backup")
        self._session = session
        self._status_callback = status_callback
        self.refresh_on_success = True

        image_page = OpenFilePage(
            "Select Backup Image",
            "Choose the backup image to restore.",
            "Select Backup Image",
            "Disk Images (*.img *.img.zst *.img.gz);;All Files (*)",
        )

        target_page = QWizardPage()
        target_page.setTitle("Restore Target")
        target_layout = QFormLayout(target_page)
        self._target_input = QLineEdit()
        self._target_input.textChanged.connect(target_page.completeChanged)
        target_page.isComplete = lambda: bool(self._target_input.text().strip())
        target_layout.addRow("Target device:", self._target_input)

        confirm_page = ConfirmationPage(
            "Confirm Restore",
            "This will DESTROY ALL DATA on the target device.",
            session.safety.generate_confirmation_string(self._target_input.text().strip()),
        )
        self._target_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._target_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Restore Backup",
            lambda: self._restore_backup(image_page.path()),
            status_callback,
            "Restoring backup...",
        )

        self.addPage(image_page)
        self.addPage(target_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _restore_backup(self, image_path: str) -> OperationResult:
        target_path = self._target_input.text().strip()
        success, message = self._session.platform.restore_image(Path(image_path), target_path)
        return OperationResult(success=success, message=message)


class RescueMediaWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Rescue Media")
        self._session = session
        self._status_callback = status_callback

        output_page = DirectoryPage(
            "Output Directory",
            "Select output directory for rescue media.",
            "Select Output Directory for Rescue Media",
        )

        result_page = OperationResultPage(
            "Create Rescue Media",
            lambda: self._create_rescue_media(output_page.path()),
            status_callback,
            "Creating rescue media...",
        )

        self.addPage(output_page)
        self.addPage(result_page)

    def _create_rescue_media(self, output_path: str) -> OperationResult:
        success, message, _artifacts = self._session.platform.create_rescue_media(Path(output_path))
        return OperationResult(success=success, message=message)


class IntegrateRecoveryEnvironmentWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Integrate to Recovery Environment")
        self._session = session
        self._status_callback = status_callback

        source_page = PathEntryPage(
            "Select Rescue Package",
            "Select the DiskForge rescue media folder to integrate into WinRE.",
            "Select Rescue Package",
            "Select Rescue Folder",
        )

        confirm_str = session.safety.generate_confirmation_string("WinRE")
        confirm_page = ConfirmationPage(
            "Confirm WinRE Integration",
            "This will copy DiskForge scripts into the Windows Recovery Environment.",
            confirm_str,
        )

        result_page = OperationResultPage(
            "Integrate WinRE",
            lambda: self._integrate_recovery_env(source_page.path()),
            status_callback,
            "Integrating into WinRE...",
        )

        self.addPage(source_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _integrate_recovery_env(self, source_path: str) -> OperationResult:
        if self._session.platform.name != "windows":
            return OperationResult(False, "WinRE integration is only available on Windows.")

        options = WinREIntegrationOptions(source_path=Path(source_path))
        success, message, artifacts = self._session.platform.integrate_recovery_environment(options)
        if artifacts:
            detail_lines = [f"{key}: {value}" for key, value in artifacts.items()]
            message = f"{message}\n\n" + "\n".join(detail_lines)
        return OperationResult(success=success, message=message)


class BootRepairWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Boot Repair")
        self._session = session
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("Boot Repair Options")
        options_layout = QFormLayout(options_page)
        self._system_root_input = QLineEdit("C:\\Windows")
        self._system_root_input.textChanged.connect(options_page.completeChanged)
        self._fix_mbr_checkbox = QCheckBox("Fix MBR (bootrec /fixmbr)")
        self._fix_mbr_checkbox.setChecked(True)
        self._fix_boot_checkbox = QCheckBox("Fix boot sector (bootrec /fixboot)")
        self._fix_boot_checkbox.setChecked(True)
        self._rebuild_bcd_checkbox = QCheckBox("Rebuild BCD store (bootrec /rebuildbcd + bcdboot)")
        self._rebuild_bcd_checkbox.setChecked(True)
        options_layout.addRow("System root:", self._system_root_input)
        options_layout.addRow(self._fix_mbr_checkbox)
        options_layout.addRow(self._fix_boot_checkbox)
        options_layout.addRow(self._rebuild_bcd_checkbox)
        options_page.isComplete = lambda: bool(self._system_root_input.text().strip())

        confirm_str = session.safety.generate_confirmation_string("boot-repair")
        confirm_page = ConfirmationPage(
            "Confirm Boot Repair",
            "This will modify Windows boot configuration.",
            confirm_str,
        )

        result_page = OperationResultPage(
            "Boot Repair",
            self._repair_boot,
            status_callback,
            "Running boot repair...",
        )

        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _repair_boot(self) -> OperationResult:
        if self._session.platform.name != "windows":
            return OperationResult(False, "Boot repair is only available on Windows.")

        options = BootRepairOptions(
            system_root=Path(self._system_root_input.text().strip()),
            fix_mbr=self._fix_mbr_checkbox.isChecked(),
            fix_boot=self._fix_boot_checkbox.isChecked(),
            rebuild_bcd=self._rebuild_bcd_checkbox.isChecked(),
        )
        success, message, artifacts = self._session.platform.repair_boot(options)
        if artifacts:
            details = "\n".join(f"{cmd}: {info.get('stderr') or info.get('stdout')}" for cmd, info in artifacts.items())
            message = f"{message}\n\n{details}"
        return OperationResult(success=success, message=message)


class RebuildMBRWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rebuild MBR")
        self._session = session
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("MBR Options")
        options_layout = QFormLayout(options_page)
        self._fix_boot_checkbox = QCheckBox("Fix boot sector (bootrec /fixboot)")
        self._fix_boot_checkbox.setChecked(True)
        options_layout.addRow(self._fix_boot_checkbox)

        confirm_str = session.safety.generate_confirmation_string("mbr")
        confirm_page = ConfirmationPage(
            "Confirm MBR Rebuild",
            "This will rewrite the MBR boot code.",
            confirm_str,
        )

        result_page = OperationResultPage(
            "Rebuild MBR",
            self._rebuild_mbr,
            status_callback,
            "Rebuilding MBR...",
        )

        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _rebuild_mbr(self) -> OperationResult:
        if self._session.platform.name != "windows":
            return OperationResult(False, "MBR rebuild is only available on Windows.")

        options = RebuildMBROptions(fix_boot=self._fix_boot_checkbox.isChecked())
        success, message = self._session.platform.rebuild_mbr(options)
        return OperationResult(success=success, message=message)


class UEFIBootOptionsWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("UEFI Boot Options Manager")
        self._session = session
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("UEFI Options")
        options_layout = QFormLayout(options_page)
        self._action_combo = QComboBox()
        self._action_combo.addItem("List UEFI entries", "list")
        self._action_combo.addItem("Set default entry", "set-default")
        self._identifier_input = QLineEdit()
        self._identifier_input.setPlaceholderText("{bootmgr} or GUID")
        self._action_combo.currentIndexChanged.connect(options_page.completeChanged)
        self._identifier_input.textChanged.connect(options_page.completeChanged)
        options_layout.addRow("Action:", self._action_combo)
        options_layout.addRow("Identifier:", self._identifier_input)

        def is_complete() -> bool:
            action = self._action_combo.currentData()
            if action == "set-default":
                return bool(self._identifier_input.text().strip())
            return True

        options_page.isComplete = is_complete  # type: ignore[assignment]

        result_page = OperationResultPage(
            "UEFI Boot Options",
            self._manage_uefi_options,
            status_callback,
            "Managing UEFI boot options...",
        )

        self.addPage(options_page)
        self.addPage(result_page)

    def _manage_uefi_options(self) -> OperationResult:
        if self._session.platform.name != "windows":
            return OperationResult(False, "UEFI boot option management is only available on Windows.")

        options = UEFIBootOptions(
            action=self._action_combo.currentData(),
            identifier=self._identifier_input.text().strip() or None,
        )
        success, message, artifacts = self._session.platform.manage_uefi_boot_options(options)
        output = artifacts.get("output")
        if output:
            message = f"{message}\n\n{output}"
        return OperationResult(success=success, message=message)


class WindowsToGoWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Windows To Go Creator")
        self._session = session
        self._status_callback = status_callback

        image_page = OpenFilePage(
            "Select Windows Image",
            "Select the Windows image (WIM/ESD) to deploy.",
            "Select Windows Image",
            "Image Files (*.wim *.esd);;All Files (*)",
        )

        options_page = QWizardPage()
        options_page.setTitle("Target Settings")
        options_layout = QFormLayout(options_page)
        self._target_drive_input = QLineEdit()
        self._target_drive_input.setPlaceholderText("E:")
        self._target_drive_input.textChanged.connect(options_page.completeChanged)
        self._index_input = QLineEdit("1")
        self._index_input.textChanged.connect(options_page.completeChanged)
        self._label_input = QLineEdit()
        options_layout.addRow("Target drive:", self._target_drive_input)
        options_layout.addRow("Image index:", self._index_input)
        options_layout.addRow("Drive label (optional):", self._label_input)

        def is_complete() -> bool:
            return bool(self._target_drive_input.text().strip()) and self._index_input.text().strip().isdigit()

        options_page.isComplete = is_complete  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Windows To Go",
            "This will deploy Windows to the target drive.",
            session.safety.generate_confirmation_string(self._target_drive_input.text().strip()),
        )
        self._target_drive_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._target_drive_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Windows To Go",
            lambda: self._create_windows_to_go(image_page.path()),
            status_callback,
            "Creating Windows To Go workspace...",
        )

        self.addPage(image_page)
        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _create_windows_to_go(self, image_path: str) -> OperationResult:
        if self._session.platform.name != "windows":
            return OperationResult(False, "Windows To Go creation is only available on Windows.")

        try:
            index = int(self._index_input.text().strip())
        except ValueError:
            return OperationResult(False, "Image index must be a number.")

        options = WindowsToGoOptions(
            image_path=Path(image_path),
            target_drive=self._target_drive_input.text().strip(),
            apply_index=index,
            label=self._label_input.text().strip() or None,
        )
        success, message, artifacts = self._session.platform.create_windows_to_go(options)
        if artifacts:
            details = "\n".join(f"{key}: {value.get('stderr') or value.get('stdout')}" for key, value in artifacts.items())
            message = f"{message}\n\n{details}"
        return OperationResult(success=success, message=message)


class ResetWindowsPasswordWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reset Windows Password")
        self._session = session
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("Account Information")
        options_layout = QFormLayout(options_page)
        self._username_input = QLineEdit()
        self._username_input.textChanged.connect(options_page.completeChanged)
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.Password)
        self._password_input.textChanged.connect(options_page.completeChanged)
        options_layout.addRow("Username:", self._username_input)
        options_layout.addRow("New password:", self._password_input)
        options_page.isComplete = lambda: bool(self._username_input.text().strip() and self._password_input.text().strip())

        confirm_page = ConfirmationPage(
            "Confirm Password Reset",
            "This will reset the password for the selected account.",
            session.safety.generate_confirmation_string(self._username_input.text().strip()),
        )
        self._username_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._username_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Reset Windows Password",
            self._reset_password,
            status_callback,
            "Resetting password...",
        )

        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _reset_password(self) -> OperationResult:
        if self._session.platform.name != "windows":
            return OperationResult(False, "Windows password reset is only available on Windows.")

        options = WindowsPasswordResetOptions(
            username=self._username_input.text().strip(),
            new_password=self._password_input.text().strip(),
        )
        success, message = self._session.platform.reset_windows_password(options)
        return OperationResult(success=success, message=message)


class ResizeMovePartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize/Move Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        size_page = QWizardPage()
        size_page.setTitle("Resize/Move Settings")
        size_layout = QFormLayout(size_page)
        self._size_input = QLineEdit(str(partition.size_bytes // (1024 * 1024)))
        self._size_input.textChanged.connect(size_page.completeChanged)
        self._start_input = QLineEdit()
        self._start_input.setPlaceholderText("Leave blank to keep current")
        size_layout.addRow("New size (MiB):", self._size_input)
        size_layout.addRow("New start sector:", self._start_input)
        size_layout.addRow(QLabel(f"Target partition: {partition.device_path}"))

        def is_complete() -> bool:
            return _parse_size_mib(self._size_input.text()) is not None

        size_page.isComplete = is_complete  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Resize/Move",
            f"This will modify {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Resize/Move Partition",
            self._resize_move_partition,
            status_callback,
            f"Resizing {partition.device_path}...",
        )

        self.addPage(size_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _resize_move_partition(self) -> OperationResult:
        size_bytes = _parse_size_mib(self._size_input.text()) or 0
        start_text = self._start_input.text().strip()
        start_sector = int(start_text) if start_text else None
        options = ResizeMoveOptions(
            partition_path=self._partition.device_path,
            new_size_bytes=size_bytes,
            new_start_sector=start_sector,
        )
        success, message = self._session.platform.resize_move_partition(options)
        return OperationResult(success=success, message=message)


class ResizeMoveDynamicVolumeWizard(DiskForgeWizard):
    def __init__(self, session: Session, volume_id: str | None, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize/Move Dynamic Volume")
        self._session = session
        self._status_callback = status_callback
        self.refresh_on_success = True

        size_page = QWizardPage()
        size_page.setTitle("Resize/Move Settings")
        size_layout = QFormLayout(size_page)
        self._volume_input = QLineEdit(volume_id or "")
        self._volume_input.setPlaceholderText("e.g., F: or \\\\?\\Volume{GUID}")
        self._size_input = QLineEdit("1024")
        self._size_input.textChanged.connect(size_page.completeChanged)
        self._start_input = QLineEdit()
        self._start_input.setPlaceholderText("Leave blank to keep current")
        size_layout.addRow("Dynamic volume identifier:", self._volume_input)
        size_layout.addRow("New size (MiB):", self._size_input)
        size_layout.addRow("New start sector:", self._start_input)

        def is_complete() -> bool:
            return bool(self._volume_input.text().strip()) and _parse_size_mib(self._size_input.text()) is not None

        size_page.isComplete = is_complete  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Resize/Move",
            "This will modify the selected dynamic volume.",
            session.safety.generate_confirmation_string(self._volume_input.text().strip()),
        )
        self._volume_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._volume_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Resize/Move Dynamic Volume",
            self._resize_move_volume,
            status_callback,
            "Resizing dynamic volume...",
        )

        self.addPage(size_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _resize_move_volume(self) -> OperationResult:
        volume_id = self._volume_input.text().strip()
        size_bytes = _parse_size_mib(self._size_input.text()) or 0
        start_text = self._start_input.text().strip()
        start_sector = int(start_text) if start_text else None
        options = DynamicVolumeResizeMoveOptions(
            volume_id=volume_id,
            new_size_bytes=size_bytes,
            new_start_sector=start_sector,
        )
        success, message = self._session.platform.resize_move_dynamic_volume(options)
        return OperationResult(success=success, message=message)


class MergePartitionsWizard(DiskForgeWizard):
    def __init__(self, session: Session, partitions: Iterable[Partition], status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge Partitions")
        self._session = session
        self._partitions = list(partitions)
        self._status_callback = status_callback
        self.refresh_on_success = True

        select_page = QWizardPage()
        select_page.setTitle("Select Partitions")
        select_layout = QFormLayout(select_page)
        self._primary_combo = QComboBox()
        self._secondary_combo = QComboBox()
        for partition in self._partitions:
            self._primary_combo.addItem(partition.device_path, partition.device_path)
            self._secondary_combo.addItem(partition.device_path, partition.device_path)
        select_layout.addRow("Primary partition:", self._primary_combo)
        select_layout.addRow("Secondary partition:", self._secondary_combo)

        confirm_page = ConfirmationPage(
            "Confirm Merge",
            "This will merge the secondary partition into the primary partition.",
            session.safety.generate_confirmation_string(self._primary_combo.currentData()),
        )
        self._primary_combo.currentIndexChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._primary_combo.currentData())
            )
        )

        result_page = OperationResultPage(
            "Merge Partitions",
            self._merge_partitions,
            status_callback,
            "Merging partitions...",
        )

        self.addPage(select_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _merge_partitions(self) -> OperationResult:
        options = MergePartitionsOptions(
            primary_partition_path=self._primary_combo.currentData(),
            secondary_partition_path=self._secondary_combo.currentData(),
        )
        success, message = self._session.platform.merge_partitions(options)
        return OperationResult(success=success, message=message)


class SplitPartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Split Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        split_page = QWizardPage()
        split_page.setTitle("Split Settings")
        split_layout = QFormLayout(split_page)
        self._split_size_input = QLineEdit(str(partition.size_bytes // (1024 * 1024) // 2))
        self._split_size_input.textChanged.connect(split_page.completeChanged)
        self._filesystem_combo = QComboBox()
        self._filesystem_combo.addItems(["ext4", "xfs", "btrfs", "ntfs", "fat32"])
        self._label_input = QLineEdit()
        split_layout.addRow("New partition size (MiB):", self._split_size_input)
        split_layout.addRow("Filesystem:", self._filesystem_combo)
        split_layout.addRow("Label:", self._label_input)

        split_page.isComplete = lambda: _parse_size_mib(self._split_size_input.text()) is not None  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Split",
            f"This will split {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Split Partition",
            self._split_partition,
            status_callback,
            f"Splitting {partition.device_path}...",
        )

        self.addPage(split_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _split_partition(self) -> OperationResult:
        size_bytes = _parse_size_mib(self._split_size_input.text()) or 0
        fs_map = {
            "ext4": FileSystem.EXT4,
            "xfs": FileSystem.XFS,
            "btrfs": FileSystem.BTRFS,
            "ntfs": FileSystem.NTFS,
            "fat32": FileSystem.FAT32,
        }
        filesystem = fs_map.get(self._filesystem_combo.currentText())
        options = SplitPartitionOptions(
            partition_path=self._partition.device_path,
            split_size_bytes=size_bytes,
            filesystem=filesystem,
            label=self._label_input.text().strip() or None,
        )
        success, message = self._session.platform.split_partition(options)
        return OperationResult(success=success, message=message)


class ExtendPartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extend Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        extend_page = QWizardPage()
        extend_page.setTitle("Extend Settings")
        extend_layout = QFormLayout(extend_page)
        self._size_input = QLineEdit(str(partition.size_bytes // (1024 * 1024)))
        self._size_input.textChanged.connect(extend_page.completeChanged)
        extend_layout.addRow("New size (MiB):", self._size_input)
        extend_layout.addRow(QLabel(f"Target partition: {partition.device_path}"))
        extend_page.isComplete = lambda: _parse_size_mib(self._size_input.text()) is not None  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Extend",
            f"This will extend {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Extend Partition",
            self._extend_partition,
            status_callback,
            f"Extending {partition.device_path}...",
        )

        self.addPage(extend_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _extend_partition(self) -> OperationResult:
        size_bytes = _parse_size_mib(self._size_input.text()) or 0
        success, message = self._session.platform.extend_partition(
            self._partition.device_path,
            size_bytes,
        )
        return OperationResult(success=success, message=message)


class ShrinkPartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Shrink Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        shrink_page = QWizardPage()
        shrink_page.setTitle("Shrink Settings")
        shrink_layout = QFormLayout(shrink_page)
        self._size_input = QLineEdit(str(partition.size_bytes // (1024 * 1024)))
        self._size_input.textChanged.connect(shrink_page.completeChanged)
        shrink_layout.addRow("New size (MiB):", self._size_input)
        shrink_layout.addRow(QLabel(f"Target partition: {partition.device_path}"))
        shrink_page.isComplete = lambda: _parse_size_mib(self._size_input.text()) is not None  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Shrink",
            f"This will shrink {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Shrink Partition",
            self._shrink_partition,
            status_callback,
            f"Shrinking {partition.device_path}...",
        )

        self.addPage(shrink_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _shrink_partition(self) -> OperationResult:
        size_bytes = _parse_size_mib(self._size_input.text()) or 0
        success, message = self._session.platform.shrink_partition(
            self._partition.device_path,
            size_bytes,
        )
        return OperationResult(success=success, message=message)


class ExtendDynamicVolumeWizard(DiskForgeWizard):
    def __init__(self, session: Session, volume_id: str | None, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extend Dynamic Volume")
        self._session = session
        self._status_callback = status_callback
        self.refresh_on_success = True

        extend_page = QWizardPage()
        extend_page.setTitle("Extend Settings")
        extend_layout = QFormLayout(extend_page)
        self._volume_input = QLineEdit(volume_id or "")
        self._volume_input.setPlaceholderText("e.g., F: or \\\\?\\Volume{GUID}")
        self._size_input = QLineEdit("1024")
        self._size_input.textChanged.connect(extend_page.completeChanged)
        extend_layout.addRow("Dynamic volume identifier:", self._volume_input)
        extend_layout.addRow("New size (MiB):", self._size_input)

        extend_page.isComplete = lambda: bool(self._volume_input.text().strip()) and _parse_size_mib(self._size_input.text()) is not None  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Extend",
            "This will extend the selected dynamic volume.",
            session.safety.generate_confirmation_string(self._volume_input.text().strip()),
        )
        self._volume_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._volume_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Extend Dynamic Volume",
            self._extend_volume,
            status_callback,
            "Extending dynamic volume...",
        )

        self.addPage(extend_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _extend_volume(self) -> OperationResult:
        volume_id = self._volume_input.text().strip()
        size_bytes = _parse_size_mib(self._size_input.text()) or 0
        success, message = self._session.platform.extend_dynamic_volume(volume_id, size_bytes)
        return OperationResult(success=success, message=message)


class ShrinkDynamicVolumeWizard(DiskForgeWizard):
    def __init__(self, session: Session, volume_id: str | None, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Shrink Dynamic Volume")
        self._session = session
        self._status_callback = status_callback
        self.refresh_on_success = True

        shrink_page = QWizardPage()
        shrink_page.setTitle("Shrink Settings")
        shrink_layout = QFormLayout(shrink_page)
        self._volume_input = QLineEdit(volume_id or "")
        self._volume_input.setPlaceholderText("e.g., F: or \\\\?\\Volume{GUID}")
        self._size_input = QLineEdit("1024")
        self._size_input.textChanged.connect(shrink_page.completeChanged)
        shrink_layout.addRow("Dynamic volume identifier:", self._volume_input)
        shrink_layout.addRow("New size (MiB):", self._size_input)

        shrink_page.isComplete = lambda: bool(self._volume_input.text().strip()) and _parse_size_mib(self._size_input.text()) is not None  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Shrink",
            "This will shrink the selected dynamic volume.",
            session.safety.generate_confirmation_string(self._volume_input.text().strip()),
        )
        self._volume_input.textChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._volume_input.text().strip())
            )
        )

        result_page = OperationResultPage(
            "Shrink Dynamic Volume",
            self._shrink_volume,
            status_callback,
            "Shrinking dynamic volume...",
        )

        self.addPage(shrink_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _shrink_volume(self) -> OperationResult:
        volume_id = self._volume_input.text().strip()
        size_bytes = _parse_size_mib(self._size_input.text()) or 0
        success, message = self._session.platform.shrink_dynamic_volume(volume_id, size_bytes)
        return OperationResult(success=success, message=message)


class AllocateFreeSpaceWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Allocate Free Space")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        select_page = QWizardPage()
        select_page.setTitle("Select Partitions")
        select_layout = QFormLayout(select_page)
        self._source_combo = QComboBox()
        self._target_combo = QComboBox()
        for partition in disk.partitions:
            label = partition.label or partition.device_path
            display = f"{partition.device_path} ({label})"
            self._source_combo.addItem(display, partition.device_path)
            self._target_combo.addItem(display, partition.device_path)
        self._size_input = QLineEdit()
        self._size_input.setPlaceholderText("Leave blank to allocate all free space")
        self._source_combo.currentIndexChanged.connect(select_page.completeChanged)
        self._target_combo.currentIndexChanged.connect(select_page.completeChanged)
        self._size_input.textChanged.connect(select_page.completeChanged)
        select_layout.addRow("From partition:", self._source_combo)
        select_layout.addRow("To partition:", self._target_combo)
        select_layout.addRow("Size (MiB):", self._size_input)

        def _is_complete() -> bool:
            if self._source_combo.currentData() == self._target_combo.currentData():
                return False
            if self._size_input.text().strip():
                return _parse_size_mib(self._size_input.text()) is not None
            return True

        select_page.isComplete = _is_complete  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Allocation",
            f"This will allocate free space on {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "Allocate Free Space",
            self._allocate_free_space,
            status_callback,
            f"Allocating free space on {disk.device_path}...",
        )

        self.addPage(select_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _allocate_free_space(self) -> OperationResult:
        size_bytes = _parse_size_mib(self._size_input.text()) if self._size_input.text().strip() else None
        options = AllocateFreeSpaceOptions(
            disk_path=self._disk.device_path,
            source_partition_path=self._source_combo.currentData(),
            target_partition_path=self._target_combo.currentData(),
            size_bytes=size_bytes,
        )
        success, message = self._session.platform.allocate_free_space(options)
        return OperationResult(success=success, message=message)


class OneClickAdjustSpaceWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("One-Click Adjust Space")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        config_page = QWizardPage()
        config_page.setTitle("Adjustment Preferences")
        config_layout = QFormLayout(config_page)
        self._target_combo = QComboBox()
        self._target_combo.addItem("Auto-select", None)
        for partition in disk.partitions:
            label = partition.label or partition.device_path
            self._target_combo.addItem(f"{partition.device_path} ({label})", partition.device_path)
        self._prioritize_system = QCheckBox("Prioritize system partition")
        self._prioritize_system.setChecked(True)
        config_layout.addRow("Target partition:", self._target_combo)
        config_layout.addRow("", self._prioritize_system)

        confirm_page = ConfirmationPage(
            "Confirm Adjustment",
            f"This will auto-adjust space on {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "One-Click Adjust",
            self._adjust_space,
            status_callback,
            f"Adjusting space on {disk.device_path}...",
        )

        self.addPage(config_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _adjust_space(self) -> OperationResult:
        options = OneClickAdjustOptions(
            disk_path=self._disk.device_path,
            target_partition_path=self._target_combo.currentData(),
            prioritize_system=self._prioritize_system.isChecked(),
        )
        success, message = self._session.platform.one_click_adjust_space(options)
        return OperationResult(success=success, message=message)


class QuickPartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Partition")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        setup_page = QWizardPage()
        setup_page.setTitle("Partition Layout")
        setup_layout = QFormLayout(setup_page)
        self._count_input = QLineEdit("2")
        self._filesystem_combo = QComboBox()
        self._filesystem_combo.addItems(["ext4", "xfs", "btrfs", "ntfs", "fat32"])
        self._label_prefix_input = QLineEdit()
        self._size_input = QLineEdit()
        self._size_input.setPlaceholderText("Leave blank to auto-size")
        self._use_entire_disk = QCheckBox("Use entire disk")
        self._use_entire_disk.setChecked(True)
        self._count_input.textChanged.connect(setup_page.completeChanged)
        self._size_input.textChanged.connect(setup_page.completeChanged)
        self._use_entire_disk.stateChanged.connect(setup_page.completeChanged)
        setup_layout.addRow("Partition count:", self._count_input)
        setup_layout.addRow("Filesystem:", self._filesystem_combo)
        setup_layout.addRow("Label prefix:", self._label_prefix_input)
        setup_layout.addRow("Size per partition (MiB):", self._size_input)
        setup_layout.addRow("", self._use_entire_disk)

        def _is_complete() -> bool:
            if not self._count_input.text().strip().isdigit():
                return False
            if not self._use_entire_disk.isChecked():
                return _parse_size_mib(self._size_input.text()) is not None
            if self._size_input.text().strip():
                return _parse_size_mib(self._size_input.text()) is not None
            return True

        setup_page.isComplete = _is_complete  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Quick Partition",
            f"This will partition {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "Quick Partition",
            self._quick_partition,
            status_callback,
            f"Partitioning {disk.device_path}...",
        )

        self.addPage(setup_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _quick_partition(self) -> OperationResult:
        size_bytes = _parse_size_mib(self._size_input.text()) if self._size_input.text().strip() else None
        options = QuickPartitionOptions(
            disk_path=self._disk.device_path,
            partition_count=int(self._count_input.text().strip()),
            filesystem=FileSystem(self._filesystem_combo.currentText()),
            label_prefix=self._label_prefix_input.text().strip() or None,
            partition_size_bytes=size_bytes,
            use_entire_disk=self._use_entire_disk.isChecked(),
        )
        success, message = self._session.platform.quick_partition_disk(options)
        return OperationResult(success=success, message=message)


class PartitionAttributesWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Partition Attributes")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        edit_page = QWizardPage()
        edit_page.setTitle("Attributes")
        edit_layout = QFormLayout(edit_page)
        self._drive_letter_input = QLineEdit()
        self._label_input = QLineEdit()
        self._type_id_input = QLineEdit()
        self._serial_input = QLineEdit()
        self._drive_letter_input.setPlaceholderText("Windows only, e.g. D")
        self._type_id_input.setPlaceholderText("GPT type GUID")
        self._serial_input.setPlaceholderText("Volume serial number")
        for input_field in (
            self._drive_letter_input,
            self._label_input,
            self._type_id_input,
            self._serial_input,
        ):
            input_field.textChanged.connect(edit_page.completeChanged)
        edit_layout.addRow("Drive letter:", self._drive_letter_input)
        edit_layout.addRow("Label:", self._label_input)
        edit_layout.addRow("Partition type ID:", self._type_id_input)
        edit_layout.addRow("Serial number:", self._serial_input)

        def _is_complete() -> bool:
            drive_letter = self._drive_letter_input.text().strip().upper()
            if drive_letter and (len(drive_letter) != 1 or not drive_letter.isalpha()):
                return False
            return any(
                field.text().strip()
                for field in (
                    self._drive_letter_input,
                    self._label_input,
                    self._type_id_input,
                    self._serial_input,
                )
            )

        edit_page.isComplete = _is_complete  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Update",
            f"This will update attributes for {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Update Attributes",
            self._update_attributes,
            status_callback,
            f"Updating attributes for {partition.device_path}...",
        )

        self.addPage(edit_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _update_attributes(self) -> OperationResult:
        drive_letter = self._drive_letter_input.text().strip().upper() or None
        options = PartitionAttributeOptions(
            partition_path=self._partition.device_path,
            drive_letter=drive_letter,
            label=self._label_input.text().strip() or None,
            partition_type_id=self._type_id_input.text().strip() or None,
            serial_number=self._serial_input.text().strip() or None,
        )
        success, message = self._session.platform.change_partition_attributes(options)
        return OperationResult(success=success, message=message)


class InitializeDiskWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Initialize Disk")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        style_page = QWizardPage()
        style_page.setTitle("Partition Style")
        style_layout = QFormLayout(style_page)
        self._style_combo = QComboBox()
        self._style_combo.addItem("GPT", PartitionStyle.GPT)
        self._style_combo.addItem("MBR", PartitionStyle.MBR)
        style_layout.addRow("Initialize as:", self._style_combo)
        style_layout.addRow(QLabel(f"Target disk: {disk.device_path}"))

        confirm_page = ConfirmationPage(
            "Confirm Initialization",
            f"This will initialize {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "Initialize Disk",
            self._initialize_disk,
            status_callback,
            f"Initializing {disk.device_path}...",
        )

        self.addPage(style_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _initialize_disk(self) -> OperationResult:
        options = InitializeDiskOptions(
            disk_path=self._disk.device_path,
            partition_style=self._style_combo.currentData(),
        )
        success, message = self._session.platform.initialize_disk(options)
        return OperationResult(success=success, message=message)


class WipeWizard(DiskForgeWizard):
    def __init__(self, session: Session, target_path: str, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Wipe/Secure Erase")
        self._session = session
        self._target_path = target_path
        self._status_callback = status_callback
        self.refresh_on_success = True

        wipe_page = QWizardPage()
        wipe_page.setTitle("Wipe Method")
        wipe_layout = QFormLayout(wipe_page)
        self._method_combo = QComboBox()
        self._method_combo.addItems(["zero", "random", "dod"])
        self._passes_input = QLineEdit("1")
        self._passes_input.textChanged.connect(wipe_page.completeChanged)
        wipe_layout.addRow("Method:", self._method_combo)
        wipe_layout.addRow("Passes:", self._passes_input)
        wipe_layout.addRow(QLabel(f"Target: {target_path}"))
        wipe_page.isComplete = lambda: self._passes_input.text().strip().isdigit()  # type: ignore[assignment]

        confirm_page = ConfirmationPage(
            "Confirm Wipe",
            f"This will ERASE ALL DATA on {target_path}.",
            session.safety.generate_confirmation_string(target_path),
        )

        result_page = OperationResultPage(
            "Wipe Device",
            self._wipe_device,
            status_callback,
            f"Wiping {target_path}...",
        )

        self.addPage(wipe_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _wipe_device(self) -> OperationResult:
        passes = int(self._passes_input.text().strip() or "1")
        options = WipeOptions(
            target_path=self._target_path,
            method=self._method_combo.currentText(),
            passes=passes,
        )
        success, message = self._session.platform.wipe_device(options)
        return OperationResult(success=success, message=message)


class SystemDiskWipeWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("System Disk Wipe")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True
        self._compatibility_ok = False

        warning_page = QWizardPage()
        warning_page.setTitle("Critical Warning")
        warning_layout = QVBoxLayout(warning_page)
        warning_text = QLabel(
            "You are about to wipe the system disk. This will erase the operating system, "
            "all applications, and all data on the disk. This operation should only be run "
            "from external boot media or a recovery environment."
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        self._backup_checkbox = QCheckBox("I have a verified backup of all important data.")
        self._offline_checkbox = QCheckBox("I am running from external boot media or recovery environment.")
        self._irreversible_checkbox = QCheckBox("I understand this action is irreversible.")
        for checkbox in (self._backup_checkbox, self._offline_checkbox, self._irreversible_checkbox):
            checkbox.stateChanged.connect(warning_page.completeChanged)
            warning_layout.addWidget(checkbox)

        warning_page.isComplete = lambda: all(  # type: ignore[assignment]
            checkbox.isChecked()
            for checkbox in (self._backup_checkbox, self._offline_checkbox, self._irreversible_checkbox)
        )

        method_page = QWizardPage()
        method_page.setTitle("Wipe Method")
        method_layout = QFormLayout(method_page)
        self._method_combo = QComboBox()
        self._method_combo.addItems(["zero", "random", "dod"])
        self._passes_input = QLineEdit("1")
        self._passes_input.textChanged.connect(method_page.completeChanged)
        method_layout.addRow("Method:", self._method_combo)
        method_layout.addRow("Passes:", self._passes_input)
        method_layout.addRow(QLabel(f"Target system disk: {disk.device_path}"))
        method_page.isComplete = lambda: self._passes_input.text().strip().isdigit()  # type: ignore[assignment]

        compatibility_page = QWizardPage()
        compatibility_page.setTitle("Compatibility Check")
        compat_layout = QVBoxLayout(compatibility_page)
        compat_intro = QLabel("Compatibility checks must pass before wiping the system disk.")
        compat_intro.setWordWrap(True)
        compat_layout.addWidget(compat_intro)
        self._compatibility_output = QTextEdit()
        self._compatibility_output.setReadOnly(True)
        compat_layout.addWidget(self._compatibility_output)
        compatibility_page.isComplete = lambda: self._compatibility_ok  # type: ignore[assignment]

        def _run_compat_checks() -> None:
            refreshed = self._session.platform.refresh_disk(self._disk.device_path)
            disk_info = refreshed or self._disk
            checks = []
            ok = True

            if not disk_info.is_system_disk:
                ok = False
                checks.append("✗ Target is not marked as the system disk.")
            else:
                checks.append("✓ Disk is marked as the system disk.")

            mounted_parts = [part.device_path for part in disk_info.partitions if part.is_mounted]
            if mounted_parts:
                ok = False
                checks.append(f"✗ Mounted partitions detected: {', '.join(mounted_parts)}")
            else:
                checks.append("✓ No mounted partitions detected.")

            if self._session.platform.requires_admin and not self._session.platform.is_admin():
                ok = False
                checks.append("✗ Administrator/root privileges are required.")
            else:
                checks.append("✓ Required privileges detected.")

            checks.append(f"Target: {disk_info.device_path}")
            self._compatibility_output.setText("\n".join(checks))
            self._compatibility_ok = ok
            compatibility_page.completeChanged.emit()

        compatibility_page.initializePage = _run_compat_checks  # type: ignore[assignment]

        confirm_phrase = f"WIPE SYSTEM DISK {disk.device_path}"
        confirm_page = ConfirmationPage(
            "Confirm System Disk Wipe",
            "This will ERASE THE SYSTEM DISK and remove the operating system.",
            confirm_phrase,
        )

        result_page = OperationResultPage(
            "System Disk Wipe",
            self._wipe_system_disk,
            status_callback,
            f"Wiping system disk {disk.device_path}...",
        )

        self.addPage(warning_page)
        self.addPage(method_page)
        self.addPage(compatibility_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _wipe_system_disk(self) -> OperationResult:
        passes = int(self._passes_input.text().strip() or "1")
        options = SystemDiskWipeOptions(
            disk_path=self._disk.device_path,
            method=self._method_combo.currentText(),
            passes=passes,
            allow_system_disk=True,
            require_offline=True,
        )
        success, message = self._session.platform.wipe_system_disk(options)
        return OperationResult(success=success, message=message)


class SSDSecureEraseWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SSD Secure Erase")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True
        self._compatibility_ok = False

        warning_page = QWizardPage()
        warning_page.setTitle("Secure Erase Warning")
        warning_layout = QVBoxLayout(warning_page)
        warning_text = QLabel(
            "SSD secure erase issues a hardware-level erase command. This permanently removes "
            "data on the SSD and may not be recoverable. Ensure the disk is not mounted and "
            "you have selected the correct device."
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        self._ssd_backup_checkbox = QCheckBox("I have verified the correct SSD is selected.")
        self._ssd_unmounted_checkbox = QCheckBox("The disk is unmounted and safe to erase.")
        self._ssd_irreversible_checkbox = QCheckBox("I understand the erase is irreversible.")
        for checkbox in (self._ssd_backup_checkbox, self._ssd_unmounted_checkbox, self._ssd_irreversible_checkbox):
            checkbox.stateChanged.connect(warning_page.completeChanged)
            warning_layout.addWidget(checkbox)

        warning_page.isComplete = lambda: all(  # type: ignore[assignment]
            checkbox.isChecked()
            for checkbox in (self._ssd_backup_checkbox, self._ssd_unmounted_checkbox, self._ssd_irreversible_checkbox)
        )

        compatibility_page = QWizardPage()
        compatibility_page.setTitle("Compatibility Check")
        compat_layout = QVBoxLayout(compatibility_page)
        compat_intro = QLabel("Secure erase is only available for SSD or NVMe devices with supported tooling.")
        compat_intro.setWordWrap(True)
        compat_layout.addWidget(compat_intro)
        self._compatibility_output = QTextEdit()
        self._compatibility_output.setReadOnly(True)
        compat_layout.addWidget(self._compatibility_output)
        compatibility_page.isComplete = lambda: self._compatibility_ok  # type: ignore[assignment]

        def _run_compat_checks() -> None:
            options = SSDSecureEraseOptions(
                disk_path=self._disk.device_path,
                allow_system_disk=False,
                require_unmounted=True,
            )
            success, message = self._session.platform.secure_erase_ssd(options, dry_run=True)
            checks = [
                f"Target: {self._disk.device_path}",
                message,
            ]
            if self._session.platform.requires_admin and not self._session.platform.is_admin():
                checks.append("Administrator/root privileges are required.")
                success = False
            self._compatibility_output.setText("\n".join(checks))
            self._compatibility_ok = success
            compatibility_page.completeChanged.emit()

        compatibility_page.initializePage = _run_compat_checks  # type: ignore[assignment]

        confirm_phrase = f"SECURE ERASE {disk.device_path}"
        confirm_page = ConfirmationPage(
            "Confirm Secure Erase",
            "This will issue a hardware secure erase command for the selected SSD.",
            confirm_phrase,
        )

        result_page = OperationResultPage(
            "SSD Secure Erase",
            self._secure_erase,
            status_callback,
            f"Secure erasing {disk.device_path}...",
        )

        self.addPage(warning_page)
        self.addPage(compatibility_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _secure_erase(self) -> OperationResult:
        options = SSDSecureEraseOptions(
            disk_path=self._disk.device_path,
            allow_system_disk=False,
            require_unmounted=True,
        )
        success, message = self._session.platform.secure_erase_ssd(options)
        return OperationResult(success=success, message=message)


class PartitionRecoveryWizard(DiskForgeWizard):
    def __init__(self, session: Session, disks: Iterable[Disk], status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Partition Recovery")
        self._session = session
        self._disks = list(disks)
        self._status_callback = status_callback

        select_page = QWizardPage()
        select_page.setTitle("Select Disk")
        select_layout = QFormLayout(select_page)
        self._disk_combo = QComboBox()
        for disk in self._disks:
            self._disk_combo.addItem(f"{disk.device_path} ({disk.model})", disk.device_path)
        select_layout.addRow("Disk:", self._disk_combo)

        output_page = DirectoryPage(
            "Output Directory",
            "Select directory to store recovery logs.",
            "Select Recovery Output Directory",
        )

        result_page = OperationResultPage(
            "Partition Recovery",
            lambda: self._recover_partitions(output_page.path()),
            status_callback,
            "Running partition recovery...",
        )

        self.addPage(select_page)
        self.addPage(output_page)
        self.addPage(result_page)

    def _recover_partitions(self, output_path: str) -> OperationResult:
        options = PartitionRecoveryOptions(
            disk_path=self._disk_combo.currentData(),
            output_path=Path(output_path),
        )
        success, message, _artifacts = self._session.platform.recover_partitions(options)
        return OperationResult(success=success, message=message)


class FileRecoveryWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("File Recovery")
        self._session = session
        self._status_callback = status_callback

        source_page = PathEntryPage(
            "Source Path",
            "Select the device, folder, or file system path to scan.",
            "Select Source File",
            "Select Source Folder",
        )

        options_page = QWizardPage()
        options_page.setTitle("Recovery Options")
        options_layout = QVBoxLayout(options_page)
        self._deep_scan_checkbox = QCheckBox("Use deep scan (slower, more thorough)")
        self._deep_scan_checkbox.setChecked(True)
        options_layout.addWidget(self._deep_scan_checkbox)

        output_page = DirectoryPage(
            "Output Directory",
            "Select directory to store recovered files.",
            "Select Recovery Output Directory",
        )

        result_page = OperationResultPage(
            "File Recovery",
            lambda: self._recover_files(source_page.path(), output_page.path()),
            status_callback,
            "Running file recovery...",
        )

        self.addPage(source_page)
        self.addPage(options_page)
        self.addPage(output_page)
        self.addPage(result_page)

    def _recover_files(self, source_path: str, output_path: str) -> OperationResult:
        options = FileRecoveryOptions(
            source_path=source_path,
            output_path=Path(output_path),
            deep_scan=self._deep_scan_checkbox.isChecked(),
        )
        success, message, _artifacts = self._session.platform.recover_files(options)
        return OperationResult(success=success, message=message)


class ShredWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Shred Files/Folders")
        self._session = session
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = PathEntryPage(
            "Target Path",
            "Select a file or folder to shred.",
            "Select File to Shred",
            "Select Folder to Shred",
        )

        options_page = QWizardPage()
        options_page.setTitle("Shred Options")
        options_layout = QFormLayout(options_page)
        self._passes_input = QLineEdit("3")
        self._passes_input.textChanged.connect(options_page.completeChanged)
        self._zero_fill_checkbox = QCheckBox("Zero-fill final pass")
        self._zero_fill_checkbox.setChecked(True)
        self._follow_symlinks_checkbox = QCheckBox("Follow symlinks")
        options_layout.addRow("Passes:", self._passes_input)
        options_layout.addRow(self._zero_fill_checkbox)
        options_layout.addRow(self._follow_symlinks_checkbox)
        options_page.isComplete = lambda: self._passes_input.text().strip().isdigit()  # type: ignore[assignment]

        confirm_page = DynamicConfirmationPage(
            "Confirm Shred",
            "This will permanently delete the selected data.",
            lambda: session.safety.generate_confirmation_string(target_page.path()),
        )

        result_page = OperationResultPage(
            "Shred Files/Folders",
            lambda: self._shred_files(target_page.path()),
            status_callback,
            "Shredding files...",
        )

        self.addPage(target_page)
        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _shred_files(self, target_path: str) -> OperationResult:
        passes = int(self._passes_input.text().strip() or "1")
        options = ShredOptions(
            targets=[target_path],
            passes=max(1, passes),
            zero_fill=self._zero_fill_checkbox.isChecked(),
            follow_symlinks=self._follow_symlinks_checkbox.isChecked(),
        )
        success, message = self._session.platform.shred_files(options)
        return OperationResult(success=success, message=message)


class DefragDiskWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Defragment Disk")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        info_page = QWizardPage()
        info_page.setTitle("Disk Defragmentation")
        info_layout = QVBoxLayout(info_page)
        info_layout.addWidget(QLabel(f"Defragment all supported partitions on {disk.device_path}."))
        info_layout.addWidget(QLabel(f"Partitions detected: {len(disk.partitions)}"))

        result_page = OperationResultPage(
            "Defragment Disk",
            self._defrag_disk,
            status_callback,
            f"Defragmenting {disk.device_path}...",
        )

        self.addPage(info_page)
        self.addPage(result_page)

    def _defrag_disk(self) -> OperationResult:
        success, message = self._session.platform.defrag_disk(self._disk.device_path)
        return OperationResult(success=success, message=message)


class DefragPartitionWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Defragment Partition")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        info_page = QWizardPage()
        info_page.setTitle("Partition Defragmentation")
        info_layout = QVBoxLayout(info_page)
        mountpoint = partition.mountpoint or "(not mounted)"
        info_layout.addWidget(QLabel(f"Defragment {partition.device_path}."))
        info_layout.addWidget(QLabel(f"Filesystem: {partition.filesystem.value}"))
        info_layout.addWidget(QLabel(f"Mount point: {mountpoint}"))

        result_page = OperationResultPage(
            "Defragment Partition",
            self._defrag_partition,
            status_callback,
            f"Defragmenting {partition.device_path}...",
        )

        self.addPage(info_page)
        self.addPage(result_page)

    def _defrag_partition(self) -> OperationResult:
        success, message = self._session.platform.defrag_partition(self._partition.device_path)
        return OperationResult(success=success, message=message)


class DiskHealthCheckWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Disk Health Check")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback

        info_page = QWizardPage()
        info_page.setTitle("Health Check")
        info_layout = QVBoxLayout(info_page)
        info_layout.addWidget(QLabel(f"Check SMART health for {disk.device_path}."))

        result_page = OperationResultPage(
            "Disk Health Check",
            self._check_health,
            status_callback,
            f"Checking health for {disk.device_path}...",
        )

        self.addPage(info_page)
        self.addPage(result_page)

    def _check_health(self) -> OperationResult:
        result = self._session.platform.disk_health_check(self._disk.device_path)
        status = result.status
        message = f"SMART status: {status} ({result.message})"
        return OperationResult(success=result.smart_available, message=message)


class BadSectorScanWizard(DiskForgeWizard):
    def __init__(
        self,
        session: Session,
        disk: Disk,
        submit_job: Callable[[Job[Any]], None],
        status_callback: Callable[[str], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bad Sector Scan")
        self._session = session
        self._disk = disk
        self._submit_job = submit_job
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("Scan Options")
        options_layout = QFormLayout(options_page)
        self._block_size_input = QLineEdit("4096")
        self._passes_input = QLineEdit("1")
        self._block_size_input.textChanged.connect(options_page.completeChanged)
        self._passes_input.textChanged.connect(options_page.completeChanged)
        options_layout.addRow("Block size (bytes):", self._block_size_input)
        options_layout.addRow("Passes:", self._passes_input)
        options_page.isComplete = lambda: self._block_size_input.text().isdigit() and self._passes_input.text().isdigit()  # type: ignore[assignment]

        submit_page = JobSubmissionPage(
            "Queue Bad Sector Scan",
            self._build_job,
            submit_job,
            status_callback,
            f"Queueing scan for {disk.device_path}...",
        )

        self.addPage(options_page)
        self.addPage(submit_page)

    def _build_job(self) -> Job[Any]:
        block_size = max(int(self._block_size_input.text() or "4096"), 512)
        passes = max(int(self._passes_input.text() or "1"), 1)
        job = BadSectorScanJob(
            device_path=self._disk.device_path,
            block_size=block_size,
            passes=passes,
        )
        job.set_session(self._session)
        return job


class DiskSpeedTestWizard(DiskForgeWizard):
    def __init__(
        self,
        session: Session,
        disk: Disk,
        submit_job: Callable[[Job[Any]], None],
        status_callback: Callable[[str], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Disk Speed Test")
        self._session = session
        self._disk = disk
        self._submit_job = submit_job
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("Speed Test Options")
        options_layout = QFormLayout(options_page)
        self._sample_size_input = QLineEdit("256")
        self._block_size_input = QLineEdit("4")
        self._sample_size_input.textChanged.connect(options_page.completeChanged)
        self._block_size_input.textChanged.connect(options_page.completeChanged)
        options_layout.addRow("Sample size (MiB):", self._sample_size_input)
        options_layout.addRow("Block size (MiB):", self._block_size_input)
        options_page.isComplete = lambda: self._sample_size_input.text().isdigit() and self._block_size_input.text().isdigit()  # type: ignore[assignment]

        submit_page = JobSubmissionPage(
            "Queue Speed Test",
            self._build_job,
            submit_job,
            status_callback,
            f"Queueing speed test for {disk.device_path}...",
        )

        self.addPage(options_page)
        self.addPage(submit_page)

    def _build_job(self) -> Job[Any]:
        sample_mib = max(int(self._sample_size_input.text() or "256"), 1)
        block_mib = max(int(self._block_size_input.text() or "4"), 1)
        job = DiskSpeedTestJob(
            device_path=self._disk.device_path,
            sample_size_bytes=sample_mib * 1024 * 1024,
            block_size_bytes=block_mib * 1024 * 1024,
        )
        job.set_session(self._session)
        return job


class SurfaceTestWizard(DiskForgeWizard):
    def __init__(
        self,
        session: Session,
        disk: Disk,
        submit_job: Callable[[Job[Any]], None],
        status_callback: Callable[[str], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Surface Test")
        self._session = session
        self._disk = disk
        self._submit_job = submit_job
        self._status_callback = status_callback

        options_page = QWizardPage()
        options_page.setTitle("Surface Test Options")
        options_layout = QFormLayout(options_page)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Read-only", "read")
        self._mode_combo.addItem("Non-destructive", "non-destructive")
        self._mode_combo.addItem("Destructive", "destructive")
        self._block_size_input = QLineEdit("4096")
        self._passes_input = QLineEdit("1")
        self._block_size_input.textChanged.connect(options_page.completeChanged)
        self._passes_input.textChanged.connect(options_page.completeChanged)
        options_layout.addRow("Mode:", self._mode_combo)
        options_layout.addRow("Block size (bytes):", self._block_size_input)
        options_layout.addRow("Passes:", self._passes_input)
        options_page.isComplete = lambda: self._block_size_input.text().isdigit() and self._passes_input.text().isdigit()  # type: ignore[assignment]

        confirm_page = DynamicConfirmationPage(
            "Confirm Surface Test",
            "Surface tests can stress disks. Destructive mode will overwrite data.",
            lambda: session.safety.generate_confirmation_string(disk.device_path),
        )

        submit_page = JobSubmissionPage(
            "Queue Surface Test",
            self._build_job,
            submit_job,
            status_callback,
            f"Queueing surface test for {disk.device_path}...",
        )

        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(submit_page)

    def _build_job(self) -> Job[Any]:
        block_size = max(int(self._block_size_input.text() or "4096"), 512)
        passes = max(int(self._passes_input.text() or "1"), 1)
        mode = self._mode_combo.currentData()
        job = SurfaceTestJob(
            device_path=self._disk.device_path,
            mode=mode,
            block_size=block_size,
            passes=passes,
        )
        job.set_session(self._session)
        return job


class Align4KWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Align 4K")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        info_page = QWizardPage()
        info_page.setTitle("Alignment")
        info_layout = QVBoxLayout(info_page)
        info_layout.addWidget(QLabel(f"Align {partition.device_path} to 4K boundaries."))

        confirm_page = ConfirmationPage(
            "Confirm Alignment",
            f"This will realign {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Align 4K",
            self._align_partition,
            status_callback,
            f"Aligning {partition.device_path}...",
        )

        self.addPage(info_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _align_partition(self) -> OperationResult:
        options = AlignOptions(partition_path=self._partition.device_path)
        success, message = self._session.platform.align_partition_4k(options)
        return OperationResult(success=success, message=message)


class ConvertPartitionStyleWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert MBR/GPT")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        style_page = QWizardPage()
        style_page.setTitle("Target Style")
        style_layout = QFormLayout(style_page)
        self._style_combo = QComboBox()
        self._style_combo.addItem("GPT", PartitionStyle.GPT)
        self._style_combo.addItem("MBR", PartitionStyle.MBR)
        style_layout.addRow("Convert to:", self._style_combo)
        style_layout.addRow(QLabel(f"Target disk: {disk.device_path}"))

        confirm_page = ConfirmationPage(
            "Confirm Conversion",
            f"This will convert {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "Convert Partition Style",
            self._convert_style,
            status_callback,
            f"Converting {disk.device_path}...",
        )

        self.addPage(style_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _convert_style(self) -> OperationResult:
        options = ConvertDiskOptions(
            disk_path=self._disk.device_path,
            target_style=self._style_combo.currentData(),
        )
        success, message = self._session.platform.convert_disk_partition_style(options)
        return OperationResult(success=success, message=message)


class ConvertSystemPartitionStyleWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert System Disk MBR/GPT")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        style_page = QWizardPage()
        style_page.setTitle("Target Style")
        style_layout = QFormLayout(style_page)
        self._style_combo = QComboBox()
        self._style_combo.addItem("GPT", PartitionStyle.GPT)
        self._style_combo.addItem("MBR", PartitionStyle.MBR)
        style_layout.addRow("Convert to:", self._style_combo)
        style_layout.addRow(QLabel(f"System disk: {disk.device_path}"))

        self._allow_full_os = QCheckBox("Allow conversion while the OS is running")
        self._allow_full_os.setChecked(True)
        style_layout.addRow(self._allow_full_os)

        confirm_page = ConfirmationPage(
            "Confirm Conversion",
            f"This will attempt a system disk conversion on {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "Convert System Disk",
            self._convert_style,
            status_callback,
            f"Converting system disk {disk.device_path}...",
        )

        self.addPage(style_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _convert_style(self) -> OperationResult:
        options = ConvertSystemDiskOptions(
            disk_path=self._disk.device_path,
            target_style=self._style_combo.currentData(),
            allow_full_os=self._allow_full_os.isChecked(),
        )
        success, message = self._session.platform.convert_system_disk_partition_style(options)
        return OperationResult(success=success, message=message)


class ConvertFilesystemWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert Filesystem")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = QWizardPage()
        target_page.setTitle("Target Filesystem")
        target_layout = QFormLayout(target_page)
        self._fs_combo = QComboBox()
        self._fs_combo.addItem("NTFS", FileSystem.NTFS)
        self._fs_combo.addItem("FAT32", FileSystem.FAT32)
        target_layout.addRow("Convert to:", self._fs_combo)
        target_layout.addRow(QLabel(f"Partition: {partition.device_path}"))
        target_layout.addRow(QLabel(f"Current filesystem: {partition.filesystem.value}"))

        self._allow_format = QCheckBox("Allow formatting if conversion requires it (data loss)")
        self._allow_format.setChecked(False)
        target_layout.addRow(self._allow_format)

        confirm_page = ConfirmationPage(
            "Confirm Conversion",
            f"This will convert the filesystem on {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Convert Filesystem",
            self._convert_filesystem,
            status_callback,
            f"Converting filesystem on {partition.device_path}...",
        )

        self.addPage(target_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _convert_filesystem(self) -> OperationResult:
        options = ConvertFilesystemOptions(
            partition_path=self._partition.device_path,
            target_filesystem=self._fs_combo.currentData(),
            allow_format=self._allow_format.isChecked(),
        )
        success, message = self._session.platform.convert_partition_filesystem(options)
        return OperationResult(success=success, message=message)


class ConvertPartitionRoleWizard(DiskForgeWizard):
    def __init__(self, session: Session, partition: Partition, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert Primary/Logical")
        self._session = session
        self._partition = partition
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = QWizardPage()
        target_page.setTitle("Target Role")
        target_layout = QFormLayout(target_page)
        self._role_combo = QComboBox()
        self._role_combo.addItem("Primary", PartitionRole.PRIMARY)
        self._role_combo.addItem("Logical", PartitionRole.LOGICAL)
        target_layout.addRow("Convert to:", self._role_combo)
        target_layout.addRow(QLabel(f"Partition: {partition.device_path}"))

        confirm_page = ConfirmationPage(
            "Confirm Conversion",
            f"This will convert the role of {partition.device_path}.",
            session.safety.generate_confirmation_string(partition.device_path),
        )

        result_page = OperationResultPage(
            "Convert Partition Role",
            self._convert_role,
            status_callback,
            f"Converting {partition.device_path} role...",
        )

        self.addPage(target_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _convert_role(self) -> OperationResult:
        options = ConvertPartitionRoleOptions(
            partition_path=self._partition.device_path,
            target_role=self._role_combo.currentData(),
        )
        success, message = self._session.platform.convert_partition_role(options)
        return OperationResult(success=success, message=message)


class ConvertDiskLayoutWizard(DiskForgeWizard):
    def __init__(self, session: Session, disk: Disk, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert Disk Layout")
        self._session = session
        self._disk = disk
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = QWizardPage()
        target_page.setTitle("Target Layout")
        target_layout = QFormLayout(target_page)
        self._layout_combo = QComboBox()
        self._layout_combo.addItem("Basic", DiskLayout.BASIC)
        self._layout_combo.addItem("Dynamic", DiskLayout.DYNAMIC)
        target_layout.addRow("Convert to:", self._layout_combo)
        target_layout.addRow(QLabel(f"Disk: {disk.device_path}"))

        confirm_page = ConfirmationPage(
            "Confirm Conversion",
            f"This will convert the disk layout of {disk.device_path}.",
            session.safety.generate_confirmation_string(disk.device_path),
        )

        result_page = OperationResultPage(
            "Convert Disk Layout",
            self._convert_layout,
            status_callback,
            f"Converting disk layout on {disk.device_path}...",
        )

        self.addPage(target_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _convert_layout(self) -> OperationResult:
        options = ConvertDiskLayoutOptions(
            disk_path=self._disk.device_path,
            target_layout=self._layout_combo.currentData(),
        )
        success, message = self._session.platform.convert_disk_layout(options)
        return OperationResult(success=success, message=message)


class SystemMigrationWizard(DiskForgeWizard):
    def __init__(
        self,
        session: Session,
        source: Disk,
        targets: Iterable[Disk],
        status_callback: Callable[[str], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("OS/System Migration")
        self._session = session
        self._source = source
        self._targets = list(targets)
        self._status_callback = status_callback
        self.refresh_on_success = True

        target_page = QWizardPage()
        target_page.setTitle("Select Target Disk")
        target_layout = QFormLayout(target_page)
        self._target_combo = QComboBox()
        for disk in self._targets:
            self._target_combo.addItem(f"{disk.device_path} ({disk.model})", disk.device_path)
        target_layout.addRow("Target disk:", self._target_combo)
        target_layout.addRow(QLabel(f"Source disk: {source.device_path}"))

        confirm_page = ConfirmationPage(
            "Confirm Migration",
            "This will migrate the system disk to the target disk.",
            session.safety.generate_confirmation_string(self._target_combo.currentData()),
        )
        self._target_combo.currentIndexChanged.connect(
            lambda: confirm_page.set_confirmation(
                session.safety.generate_confirmation_string(self._target_combo.currentData())
            )
        )

        result_page = OperationResultPage(
            "OS/System Migration",
            self._migrate_system,
            status_callback,
            "Migrating system disk...",
        )

        self.addPage(target_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _migrate_system(self) -> OperationResult:
        options = MigrationOptions(
            source_disk_path=self._source.device_path,
            target_disk_path=self._target_combo.currentData(),
        )
        success, message = self._session.platform.migrate_system(options)
        return OperationResult(success=success, message=message)


class FreeSpaceWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Free Up Space")
        self._session = session
        self._status_callback = status_callback

        self._root_page = DirectoryPage(
            "Select Scan Root",
            "Choose a folder to scan for reclaimable space.",
            "Select Folder",
        )

        options_page = QWizardPage()
        options_page.setTitle("Scan Options")
        options_layout = QFormLayout(options_page)
        self._large_min_input = QLineEdit("512")
        self._duplicate_min_input = QLineEdit("32")
        self._junk_max_input = QLineEdit("500")
        options_layout.addRow("Large file threshold (MiB):", self._large_min_input)
        options_layout.addRow("Duplicate scan min size (MiB):", self._duplicate_min_input)
        options_layout.addRow("Max junk files:", self._junk_max_input)

        result_page = OperationResultPage(
            "Free Space Report",
            self._scan_free_space,
            status_callback,
            "Scanning for reclaimable space...",
        )

        self.addPage(self._root_page)
        self.addPage(options_page)
        self.addPage(result_page)

    def _scan_free_space(self) -> OperationResult:
        large_min = _parse_size_mib(self._large_min_input.text()) or 512 * 1024 * 1024
        duplicate_min = _parse_size_mib(self._duplicate_min_input.text()) or 32 * 1024 * 1024
        try:
            junk_max = int(self._junk_max_input.text().strip())
        except ValueError:
            junk_max = 500
        options = FreeSpaceOptions(
            roots=[self._root_page.path()],
            large_min_size_bytes=large_min,
            duplicate_min_size_bytes=duplicate_min,
            junk_max_files=junk_max,
        )
        report = self._session.platform.scan_free_space(options)
        message = (
            "Reclaimable space summary:\n"
            f"Total: {_format_bytes(report.total_reclaimable_bytes)}\n"
            f"Junk: {_format_bytes(report.junk_bytes)}\n"
            f"Large files: {_format_bytes(report.large_files_bytes)}\n"
            f"Duplicates: {_format_bytes(report.duplicate_bytes)}"
        )
        return OperationResult(success=True, message=message)


class JunkCleanupWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Junk File Cleanup")
        self._session = session
        self._status_callback = status_callback

        self._root_page = DirectoryPage(
            "Select Cleanup Root",
            "Choose a folder to clean junk files from.",
            "Select Folder",
        )

        options_page = QWizardPage()
        options_page.setTitle("Cleanup Options")
        options_layout = QFormLayout(options_page)
        self._junk_max_input = QLineEdit("500")
        options_layout.addRow("Max junk files:", self._junk_max_input)

        confirm_page = DynamicConfirmationPage(
            "Confirm Junk Cleanup",
            "This will permanently delete junk files in the selected folder.",
            lambda: session.safety.generate_confirmation_string(self._root_page.path()),
        )

        result_page = OperationResultPage(
            "Cleanup Results",
            self._cleanup_junk,
            status_callback,
            "Cleaning junk files...",
        )

        self.addPage(self._root_page)
        self.addPage(options_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _cleanup_junk(self) -> OperationResult:
        if self._session.danger_mode == DangerMode.DISABLED:
            return OperationResult(
                success=False,
                message="Danger Mode is required to remove junk files.",
            )
        try:
            junk_max = int(self._junk_max_input.text().strip())
        except ValueError:
            junk_max = 500
        options = JunkCleanupOptions(
            roots=[self._root_page.path()],
            max_files=junk_max,
        )
        result = self._session.platform.cleanup_junk_files(options)
        message = (
            f"Removed {result.total_files_removed} files.\n"
            f"Failed: {result.total_files_failed} files.\n"
            f"Freed: {_format_bytes(result.freed_bytes)}"
        )
        return OperationResult(success=True, message=message)


class LargeFilesWizard(DiskForgeWizard):
    OPTIONS_PAGE = 0
    CONFIG_PAGE = 1
    CONFIRM_PAGE = 2
    RESULT_PAGE = 3

    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Large File Discovery")
        self._session = session
        self._status_callback = status_callback

        self._root_page = DirectoryPage(
            "Select Scan Root",
            "Choose a folder to scan for large files.",
            "Select Folder",
        )

        class _ConfigPage(QWizardPage):
            def __init__(self, wizard: LargeFilesWizard) -> None:
                super().__init__()
                self._wizard = wizard
                self.setTitle("Scan Options")
                layout = QFormLayout(self)
                wizard._large_min_input = QLineEdit("1024")
                wizard._large_max_input = QLineEdit("50")
                wizard._remove_checkbox = QCheckBox("Remove discovered files after scan")
                layout.addRow("Minimum size (MiB):", wizard._large_min_input)
                layout.addRow("Max results:", wizard._large_max_input)
                layout.addRow("", wizard._remove_checkbox)

            def nextId(self) -> int:
                if self._wizard._remove_checkbox.isChecked():
                    return LargeFilesWizard.CONFIRM_PAGE
                return LargeFilesWizard.RESULT_PAGE

        self._config_page = _ConfigPage(self)

        confirm_page = DynamicConfirmationPage(
            "Confirm Removal",
            "This will permanently delete all discovered large files.",
            lambda: session.safety.generate_confirmation_string(self._root_page.path()),
        )

        result_page = OperationResultPage(
            "Large File Results",
            self._scan_large_files,
            status_callback,
            "Scanning for large files...",
        )

        self.setPage(self.OPTIONS_PAGE, self._root_page)
        self.setPage(self.CONFIG_PAGE, self._config_page)
        self.setPage(self.CONFIRM_PAGE, confirm_page)
        self.setPage(self.RESULT_PAGE, result_page)
        self.setStartId(self.OPTIONS_PAGE)

    def _scan_large_files(self) -> OperationResult:
        min_size = _parse_size_mib(self._large_min_input.text()) or 1024 * 1024 * 1024
        try:
            max_results = int(self._large_max_input.text().strip())
        except ValueError:
            max_results = 50
        scan = self._session.platform.scan_large_files(
            LargeFileScanOptions(
                roots=[self._root_page.path()],
                min_size_bytes=min_size,
                max_results=max_results,
            )
        )
        message_lines = [
            f"Found {scan.file_count} large files totaling {_format_bytes(scan.total_size_bytes)}."
        ]
        if self._remove_checkbox.isChecked():
            if self._session.danger_mode == DangerMode.DISABLED:
                return OperationResult(
                    success=False,
                    message="Danger Mode is required to remove large files.",
                )
            removal = self._session.platform.remove_large_files(
                FileRemovalOptions(paths=[entry.path for entry in scan.files])
            )
            message_lines.append(removal.message)
        return OperationResult(success=True, message="\n".join(message_lines))


class DuplicateFilesWizard(DiskForgeWizard):
    OPTIONS_PAGE = 0
    CONFIG_PAGE = 1
    CONFIRM_PAGE = 2
    RESULT_PAGE = 3

    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Duplicate File Detection")
        self._session = session
        self._status_callback = status_callback

        self._root_page = DirectoryPage(
            "Select Scan Root",
            "Choose a folder to scan for duplicate files.",
            "Select Folder",
        )

        class _ConfigPage(QWizardPage):
            def __init__(self, wizard: DuplicateFilesWizard) -> None:
                super().__init__()
                self._wizard = wizard
                self.setTitle("Scan Options")
                layout = QFormLayout(self)
                wizard._duplicate_min_input = QLineEdit("32")
                wizard._remove_checkbox = QCheckBox("Remove duplicates after scan (keep one copy)")
                layout.addRow("Minimum size (MiB):", wizard._duplicate_min_input)
                layout.addRow("", wizard._remove_checkbox)

            def nextId(self) -> int:
                if self._wizard._remove_checkbox.isChecked():
                    return DuplicateFilesWizard.CONFIRM_PAGE
                return DuplicateFilesWizard.RESULT_PAGE

        self._config_page = _ConfigPage(self)

        confirm_page = DynamicConfirmationPage(
            "Confirm Removal",
            "This will permanently delete duplicate files, keeping one copy.",
            lambda: session.safety.generate_confirmation_string(self._root_page.path()),
        )

        result_page = OperationResultPage(
            "Duplicate Scan Results",
            self._scan_duplicates,
            status_callback,
            "Scanning for duplicate files...",
        )

        self.setPage(self.OPTIONS_PAGE, self._root_page)
        self.setPage(self.CONFIG_PAGE, self._config_page)
        self.setPage(self.CONFIRM_PAGE, confirm_page)
        self.setPage(self.RESULT_PAGE, result_page)
        self.setStartId(self.OPTIONS_PAGE)

    def _scan_duplicates(self) -> OperationResult:
        min_size = _parse_size_mib(self._duplicate_min_input.text()) or 32 * 1024 * 1024
        scan = self._session.platform.scan_duplicate_files(
            DuplicateScanOptions(
                roots=[self._root_page.path()],
                min_size_bytes=min_size,
            )
        )
        message_lines = [
            f"Found {len(scan.duplicate_groups)} duplicate groups totaling "
            f"{_format_bytes(scan.total_wasted_bytes)} of potential savings."
        ]
        if self._remove_checkbox.isChecked():
            if self._session.danger_mode == DangerMode.DISABLED:
                return OperationResult(
                    success=False,
                    message="Danger Mode is required to remove duplicate files.",
                )
            removal = self._session.platform.remove_duplicate_files(
                DuplicateRemovalOptions(duplicate_groups=scan.duplicate_groups)
            )
            message_lines.append(removal.message)
        return OperationResult(success=True, message="\n".join(message_lines))


class MoveApplicationWizard(DiskForgeWizard):
    def __init__(self, session: Session, status_callback: Callable[[str], None], parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move Applications")
        self._session = session
        self._status_callback = status_callback

        self._source_page = DirectoryPage(
            "Select Application Folder",
            "Choose the application folder you want to move.",
            "Select Folder",
        )
        self._destination_page = DirectoryPage(
            "Select Destination Drive",
            "Choose the destination drive or folder.",
            "Select Folder",
        )

        confirm_page = DynamicConfirmationPage(
            "Confirm Move",
            "This will move the selected application folder to the destination.",
            lambda: session.safety.generate_confirmation_string(self._source_page.path()),
        )

        result_page = OperationResultPage(
            "Move Results",
            self._move_application,
            status_callback,
            "Moving application...",
        )

        self.addPage(self._source_page)
        self.addPage(self._destination_page)
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _move_application(self) -> OperationResult:
        if self._session.danger_mode == DangerMode.DISABLED:
            return OperationResult(
                success=False,
                message="Danger Mode is required to move applications.",
            )
        options = MoveApplicationOptions(
            source_path=self._source_page.path(),
            destination_root=self._destination_page.path(),
        )
        result = self._session.platform.move_application(options)
        return OperationResult(success=result.success, message=result.message)
