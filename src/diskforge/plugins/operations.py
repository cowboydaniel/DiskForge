"""
DiskForge Operations Plugin.

Provides partition management, cloning, and imaging jobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from diskforge.core.job import Job, JobContext
from diskforge.core.models import (
    FileSystem,
    FormatOptions,
    ImageInfo,
    PartitionCreateOptions,
)
from diskforge.core.safety import (
    ExecutionPlan,
    OperationType,
    PreflightChecker,
    PreflightReport,
    check_not_mounted,
    check_power_status,
    check_target_size,
)
from diskforge.plugins.base import Plugin, PluginMetadata

if TYPE_CHECKING:
    from diskforge.core.session import Session


class CreatePartitionJob(Job[str]):
    """Job to create a new partition."""

    operation_type = OperationType.CREATE

    def __init__(
        self,
        disk_path: str,
        size_bytes: int | None = None,
        filesystem: FileSystem = FileSystem.EXT4,
        label: str | None = None,
    ) -> None:
        super().__init__(
            name="create_partition",
            description=f"Create partition on {disk_path}",
        )
        self.disk_path = disk_path
        self.size_bytes = size_bytes
        self.filesystem = filesystem
        self.label = label
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> str:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        # Create partition
        context.update_progress(stage="create", message="Creating partition...")

        options = PartitionCreateOptions(
            disk_path=self.disk_path,
            size_bytes=self.size_bytes,
            filesystem=self.filesystem,
            label=self.label,
        )

        success, message = platform.create_partition(options, context)
        if not success:
            raise RuntimeError(f"Failed to create partition: {message}")

        return message

    def get_plan(self) -> str:
        size_str = f"{self.size_bytes:,} bytes" if self.size_bytes else "all available space"
        return f"""Create Partition
===============
Disk: {self.disk_path}
Size: {size_str}
Filesystem: {self.filesystem.value}
Label: {self.label or "(none)"}

Steps:
1. Verify disk is accessible
2. Calculate partition boundaries
3. Create partition entry
4. Update partition table

This operation modifies the disk's partition table."""

    def validate(self) -> list[str]:
        errors = []
        if not self.disk_path:
            errors.append("Disk path is required")
        return errors


class DeletePartitionJob(Job[str]):
    """Job to delete a partition."""

    operation_type = OperationType.DELETE

    def __init__(self, partition_path: str) -> None:
        super().__init__(
            name="delete_partition",
            description=f"Delete partition {partition_path}",
        )
        self.partition_path = partition_path
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> str:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        context.update_progress(message=f"Deleting {self.partition_path}...")
        success, message = platform.delete_partition(self.partition_path, context)

        if not success:
            raise RuntimeError(f"Failed to delete partition: {message}")

        return message

    def get_plan(self) -> str:
        return f"""Delete Partition
===============
Target: {self.partition_path}

Steps:
1. Verify partition exists
2. Check partition is not mounted
3. Remove partition from disk
4. Update partition table

⚠️ WARNING: This will permanently delete the partition!
All data on this partition will be LOST."""


class FormatPartitionJob(Job[str]):
    """Job to format a partition."""

    operation_type = OperationType.MODIFY

    def __init__(
        self,
        partition_path: str,
        filesystem: FileSystem,
        label: str | None = None,
        quick: bool = True,
    ) -> None:
        super().__init__(
            name="format_partition",
            description=f"Format {partition_path} as {filesystem.value}",
        )
        self.partition_path = partition_path
        self.filesystem = filesystem
        self.label = label
        self.quick = quick
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> str:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        context.update_progress(
            message=f"Formatting {self.partition_path} as {self.filesystem.value}..."
        )

        options = FormatOptions(
            partition_path=self.partition_path,
            filesystem=self.filesystem,
            label=self.label,
            quick=self.quick,
        )

        success, message = platform.format_partition(options, context)

        if not success:
            raise RuntimeError(f"Failed to format partition: {message}")

        return message

    def get_plan(self) -> str:
        format_type = "Quick format" if self.quick else "Full format"
        return f"""Format Partition
===============
Target: {self.partition_path}
Filesystem: {self.filesystem.value}
Label: {self.label or "(none)"}
Type: {format_type}

Steps:
1. Verify partition is unmounted
2. Create filesystem structures
3. Write filesystem metadata
{"4. Verify filesystem integrity" if not self.quick else ""}

⚠️ WARNING: This will erase all data on the partition!"""


class CloneDiskJob(Job[str]):
    """Job to clone a disk."""

    operation_type = OperationType.CLONE

    def __init__(
        self,
        source_path: str,
        target_path: str,
        verify: bool = True,
    ) -> None:
        super().__init__(
            name="clone_disk",
            description=f"Clone {source_path} to {target_path}",
        )
        self.source_path = source_path
        self.target_path = target_path
        self.verify = verify
        self._session: Session | None = None
        self._preflight_report: PreflightReport | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def run_preflight(self) -> PreflightReport:
        """Run preflight checks."""
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform
        source_info = platform.get_disk_info(self.source_path)
        target_info = platform.get_disk_info(self.target_path)

        context = {
            "source_size": source_info.size_bytes if source_info else 0,
            "target_size": target_info.size_bytes if target_info else 0,
            "target_path": self.target_path,
            "mounted_paths": platform.get_mounted_devices().keys(),
        }

        checker = PreflightChecker()
        checker.add_check("Power Status", check_power_status)
        checker.add_check("Target Size", check_target_size)
        checker.add_check("Mount Status", check_not_mounted)

        self._preflight_report = checker.run_checks(context)
        return self._preflight_report

    def execute(self, context: JobContext) -> str:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        # Run preflight if not already done
        if self._preflight_report is None:
            self.run_preflight()

        if self._preflight_report and self._preflight_report.has_errors:
            raise RuntimeError(
                "Preflight checks failed:\n" + self._preflight_report.get_summary()
            )

        context.update_progress(
            stage="clone",
            message=f"Cloning {self.source_path} to {self.target_path}...",
        )

        success, message = platform.clone_disk(
            self.source_path,
            self.target_path,
            context,
            verify=self.verify,
        )

        if not success:
            raise RuntimeError(f"Clone failed: {message}")

        return message

    def get_plan(self) -> str:
        plan = f"""Clone Disk
=========
Source: {self.source_path}
Target: {self.target_path}
Verify: {"Yes" if self.verify else "No"}

Steps:
1. Verify source disk is accessible
2. Verify target disk is not mounted
3. Copy all data block-by-block
{"4. Verify clone integrity" if self.verify else ""}

⚠️ WARNING: This will DESTROY all data on {self.target_path}!"""

        if self._preflight_report:
            plan += "\n\n" + self._preflight_report.get_summary()

        return plan


class ClonePartitionJob(Job[str]):
    """Job to clone a partition."""

    operation_type = OperationType.CLONE

    def __init__(
        self,
        source_path: str,
        target_path: str,
        verify: bool = True,
    ) -> None:
        super().__init__(
            name="clone_partition",
            description=f"Clone {source_path} to {target_path}",
        )
        self.source_path = source_path
        self.target_path = target_path
        self.verify = verify
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> str:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        context.update_progress(
            stage="clone",
            message=f"Cloning {self.source_path} to {self.target_path}...",
        )

        success, message = platform.clone_partition(
            self.source_path,
            self.target_path,
            context,
            verify=self.verify,
        )

        if not success:
            raise RuntimeError(f"Clone failed: {message}")

        return message

    def get_plan(self) -> str:
        return f"""Clone Partition
==============
Source: {self.source_path}
Target: {self.target_path}
Verify: {"Yes" if self.verify else "No"}

Steps:
1. Verify source partition exists
2. Verify target partition is unmounted
3. Copy partition data block-by-block
{"4. Verify clone integrity" if self.verify else ""}

⚠️ WARNING: This will DESTROY all data on {self.target_path}!"""


class CreateImageJob(Job[ImageInfo]):
    """Job to create a disk/partition image."""

    operation_type = OperationType.CREATE

    def __init__(
        self,
        source_path: str,
        image_path: Path,
        compression: str | None = "zstd",
        verify: bool = True,
    ) -> None:
        super().__init__(
            name="create_image",
            description=f"Create image of {source_path}",
        )
        self.source_path = source_path
        self.image_path = image_path
        self.compression = compression
        self.verify = verify
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> ImageInfo:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        context.update_progress(
            stage="image",
            message=f"Creating image of {self.source_path}...",
        )

        success, message, image_info = platform.create_image(
            self.source_path,
            self.image_path,
            context,
            compression=self.compression,
            verify=self.verify,
        )

        if not success or image_info is None:
            raise RuntimeError(f"Image creation failed: {message}")

        return image_info

    def get_plan(self) -> str:
        return f"""Create Disk Image
================
Source: {self.source_path}
Output: {self.image_path}
Compression: {self.compression or "None"}
Verify: {"Yes" if self.verify else "No"}

Steps:
1. Read source device
2. {"Compress and write" if self.compression else "Write"} to image file
3. Generate checksum
4. Create metadata file

This operation reads the source device."""


class RestoreImageJob(Job[str]):
    """Job to restore a disk/partition image."""

    operation_type = OperationType.RESTORE

    def __init__(
        self,
        image_path: Path,
        target_path: str,
        verify: bool = True,
    ) -> None:
        super().__init__(
            name="restore_image",
            description=f"Restore image to {target_path}",
        )
        self.image_path = image_path
        self.target_path = target_path
        self.verify = verify
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> str:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        context.update_progress(
            stage="restore",
            message=f"Restoring image to {self.target_path}...",
        )

        success, message = platform.restore_image(
            self.image_path,
            self.target_path,
            context,
            verify=self.verify,
        )

        if not success:
            raise RuntimeError(f"Restore failed: {message}")

        return message

    def get_plan(self) -> str:
        return f"""Restore Disk Image
=================
Image: {self.image_path}
Target: {self.target_path}
Verify: {"Yes" if self.verify else "No"}

Steps:
1. Read image metadata
2. Verify target size is sufficient
3. Decompress and write to target
{"4. Verify checksum" if self.verify else ""}

⚠️ WARNING: This will DESTROY all data on {self.target_path}!"""


class CreateRescueMediaJob(Job[dict[str, Any]]):
    """Job to create bootable rescue media."""

    operation_type = OperationType.CREATE

    def __init__(self, output_path: Path) -> None:
        super().__init__(
            name="create_rescue_media",
            description="Create bootable rescue media",
        )
        self.output_path = output_path
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        self._session = session

    def execute(self, context: JobContext) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform

        context.update_progress(message="Creating rescue media...")

        success, message, artifacts = platform.create_rescue_media(
            self.output_path,
            context,
        )

        if not success:
            raise RuntimeError(f"Rescue media creation failed: {message}")

        return {"message": message, "artifacts": artifacts}

    def get_plan(self) -> str:
        return f"""Create Rescue Media
==================
Output: {self.output_path}

Steps:
1. Create directory structure
2. Generate rescue scripts
3. Create bootable image (if supported)

This creates recovery tools for emergency disk operations."""


class OperationsPlugin(Plugin):
    """Plugin providing disk operations."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="operations",
            version="1.0.0",
            description="Disk operations (partition, clone, image)",
            author="DiskForge Team",
            requires_admin=True,
            tags=["core", "operations"],
        )

    def initialize(self, session: Session) -> None:
        """Initialize the operations plugin."""
        if hasattr(session, "plugin_manager"):
            registry = session.plugin_manager.registry

            # Register jobs
            registry.register_job("create_partition", CreatePartitionJob)
            registry.register_job("delete_partition", DeletePartitionJob)
            registry.register_job("format_partition", FormatPartitionJob)
            registry.register_job("clone_disk", CloneDiskJob)
            registry.register_job("clone_partition", ClonePartitionJob)
            registry.register_job("create_image", CreateImageJob)
            registry.register_job("restore_image", RestoreImageJob)
            registry.register_job("create_rescue_media", CreateRescueMediaJob)
