"""
DiskForge Platform Backend Base.

Defines the abstract interface for platform-specific implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from diskforge.core.models import (
        Disk,
        DiskInventory,
        FileSystem,
        FormatOptions,
        ImageInfo,
        Partition,
        PartitionCreateOptions,
        AlignOptions,
        ConvertDiskOptions,
        MergePartitionsOptions,
        MigrationOptions,
        PartitionRecoveryOptions,
        ResizeMoveOptions,
        SplitPartitionOptions,
        WipeOptions,
    )
    from diskforge.core.job import JobContext


class CommandResult:
    """Result of a command execution."""

    def __init__(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        command: str | list[str],
        duration_seconds: float = 0.0,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.command = command
        self.duration_seconds = duration_seconds

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:
        cmd = self.command if isinstance(self.command, str) else " ".join(self.command)
        return f"CommandResult(rc={self.returncode}, cmd='{cmd[:50]}...')"


class PlatformBackend(ABC):
    """Abstract base class for platform-specific disk operations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Platform name (e.g., 'linux', 'windows')."""

    @property
    @abstractmethod
    def requires_admin(self) -> bool:
        """Whether admin/root privileges are required for operations."""

    @abstractmethod
    def is_admin(self) -> bool:
        """Check if running with admin privileges."""

    # ==================== Inventory Operations ====================

    @abstractmethod
    def get_disk_inventory(self) -> DiskInventory:
        """Get complete disk inventory."""

    @abstractmethod
    def get_disk_info(self, device_path: str) -> Disk | None:
        """Get information about a specific disk."""

    @abstractmethod
    def get_partition_info(self, device_path: str) -> Partition | None:
        """Get information about a specific partition."""

    @abstractmethod
    def refresh_disk(self, device_path: str) -> Disk | None:
        """Refresh information for a specific disk."""

    # ==================== Partition Operations ====================

    @abstractmethod
    def create_partition(
        self,
        options: PartitionCreateOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Create a new partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def delete_partition(
        self,
        partition_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Delete a partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def format_partition(
        self,
        options: FormatOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Format a partition with specified filesystem.
        Returns (success, message/error).
        """

    @abstractmethod
    def resize_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Resize a partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def resize_move_partition(
        self,
        options: ResizeMoveOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Resize or move a partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def merge_partitions(
        self,
        options: MergePartitionsOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Merge two partitions.
        Returns (success, message/error).
        """

    @abstractmethod
    def split_partition(
        self,
        options: SplitPartitionOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Split a partition into two.
        Returns (success, message/error).
        """

    @abstractmethod
    def extend_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Extend a partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def shrink_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Shrink a partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def wipe_device(
        self,
        options: WipeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Wipe a disk or partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def recover_partitions(
        self,
        options: PartitionRecoveryOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Attempt to recover partitions on a disk.
        Returns (success, message/error, artifacts).
        """

    @abstractmethod
    def align_partition_4k(
        self,
        options: AlignOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Align a partition to 4K boundaries.
        Returns (success, message/error).
        """

    @abstractmethod
    def convert_disk_partition_style(
        self,
        options: ConvertDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Convert disk partition style (MBR/GPT).
        Returns (success, message/error).
        """

    @abstractmethod
    def migrate_system(
        self,
        options: MigrationOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Migrate OS/system to another disk.
        Returns (success, message/error).
        """

    # ==================== Clone Operations ====================

    @abstractmethod
    def clone_disk(
        self,
        source_path: str,
        target_path: str,
        context: JobContext | None = None,
        verify: bool = True,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Clone a disk block-by-block.
        Returns (success, message/error).
        """

    @abstractmethod
    def clone_partition(
        self,
        source_path: str,
        target_path: str,
        context: JobContext | None = None,
        verify: bool = True,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Clone a partition block-by-block.
        Returns (success, message/error).
        """

    # ==================== Image Operations ====================

    @abstractmethod
    def create_image(
        self,
        source_path: str,
        image_path: Path,
        context: JobContext | None = None,
        compression: str | None = "zstd",
        verify: bool = True,
        dry_run: bool = False,
    ) -> tuple[bool, str, ImageInfo | None]:
        """
        Create a disk/partition image.
        Returns (success, message/error, image_info).
        """

    @abstractmethod
    def restore_image(
        self,
        image_path: Path,
        target_path: str,
        context: JobContext | None = None,
        verify: bool = True,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Restore an image to a disk/partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def get_image_info(self, image_path: Path) -> ImageInfo | None:
        """Get information about an image file."""

    # ==================== Rescue Media Operations ====================

    @abstractmethod
    def create_rescue_media(
        self,
        output_path: Path,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Create bootable rescue media.
        Returns (success, message/error, artifacts).
        """

    # ==================== Mount Operations ====================

    @abstractmethod
    def mount_partition(
        self,
        partition_path: str,
        mount_point: str,
        options: list[str] | None = None,
    ) -> tuple[bool, str]:
        """
        Mount a partition.
        Returns (success, message/error).
        """

    @abstractmethod
    def unmount_partition(
        self,
        partition_path: str,
        force: bool = False,
    ) -> tuple[bool, str]:
        """
        Unmount a partition.
        Returns (success, message/error).
        """

    # ==================== SMART Operations ====================

    @abstractmethod
    def get_smart_info(self, device_path: str) -> dict[str, Any] | None:
        """Get SMART information for a disk."""

    # ==================== Utility Methods ====================

    @abstractmethod
    def run_command(
        self,
        command: list[str],
        timeout: int = 300,
        check: bool = True,
        capture_output: bool = True,
    ) -> CommandResult:
        """Run a system command."""

    @abstractmethod
    def validate_device_path(self, path: str) -> tuple[bool, str]:
        """
        Validate a device path.
        Returns (valid, message/error).
        """

    @abstractmethod
    def is_device_mounted(self, device_path: str) -> bool:
        """Check if a device is mounted."""

    @abstractmethod
    def get_mounted_devices(self) -> dict[str, str]:
        """Get mapping of mounted devices to mount points."""

    @abstractmethod
    def is_system_device(self, device_path: str) -> bool:
        """Check if a device is the system disk."""
