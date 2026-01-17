"""
QWizard-based flows for disk operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

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
    Disk,
    FileSystem,
    FormatOptions,
    MergePartitionsOptions,
    MigrationOptions,
    AllocateFreeSpaceOptions,
    OneClickAdjustOptions,
    QuickPartitionOptions,
    PartitionAttributeOptions,
    InitializeDiskOptions,
    Partition,
    PartitionCreateOptions,
    PartitionRecoveryOptions,
    PartitionStyle,
    ResizeMoveOptions,
    SplitPartitionOptions,
    WipeOptions,
)
from diskforge.core.session import Session


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
