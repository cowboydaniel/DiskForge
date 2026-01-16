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
)

from diskforge.core.models import (
    Disk,
    FileSystem,
    FormatOptions,
    Partition,
    PartitionCreateOptions,
)
from diskforge.core.session import Session


@dataclass(frozen=True)
class OperationResult:
    success: bool
    message: str


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
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _clone_disk(self) -> OperationResult:
        target_path = self._target_combo.currentData()
        success, message = self._session.platform.clone_disk(self._source.device_path, target_path)
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
        self.addPage(confirm_page)
        self.addPage(result_page)

    def _clone_partition(self) -> OperationResult:
        target_path = self._target_input.text().strip()
        success, message = self._session.platform.clone_partition(self._source.device_path, target_path)
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
        compress_page.setTitle("Compression")
        compress_layout = QFormLayout(compress_page)
        self._compression_combo = QComboBox()
        self._compression_combo.addItems(["zstd (recommended)", "gzip", "none"])
        compress_layout.addRow("Compression:", self._compression_combo)

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
        success, message, _info = self._session.platform.create_image(
            self._source_path,
            Path(output_path),
            compression=compression,
        )
        return OperationResult(success=success, message=message)


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
