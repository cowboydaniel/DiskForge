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
        BackupType,
        CloneMode,
        CompressionLevel,
        Disk,
        DiskInventory,
        FileSystem,
        FormatOptions,
        ImageInfo,
        Partition,
        PartitionCreateOptions,
        AlignOptions,
        ConvertDiskOptions,
        ConvertDiskLayoutOptions,
        ConvertFilesystemOptions,
        ConvertPartitionRoleOptions,
        ConvertSystemDiskOptions,
        DuplicateRemovalOptions,
        DuplicateScanOptions,
        FileRecoveryOptions,
        MergePartitionsOptions,
        MigrationOptions,
        AllocateFreeSpaceOptions,
        OneClickAdjustOptions,
        QuickPartitionOptions,
        PartitionAttributeOptions,
        InitializeDiskOptions,
        PartitionRecoveryOptions,
        WinREIntegrationOptions,
        BootRepairOptions,
        RebuildMBROptions,
        UEFIBootOptions,
        WindowsToGoOptions,
        WindowsPasswordResetOptions,
        DynamicVolumeResizeMoveOptions,
        FileRemovalOptions,
        FreeSpaceOptions,
        JunkCleanupOptions,
        LargeFileScanOptions,
        MoveApplicationOptions,
        ResizeMoveOptions,
        SplitPartitionOptions,
        ShredOptions,
        WipeOptions,
        SystemDiskWipeOptions,
        SSDSecureEraseOptions,
        DuplicateScanResult,
        FileRemovalResult,
        FreeSpaceReport,
        JunkCleanupResult,
        JunkScanResult,
        LargeFileScanResult,
        MoveApplicationResult,
        BadSectorScanOptions,
        SurfaceTestOptions,
        DiskSpeedTestOptions,
        DiskHealthResult,
        BadSectorScanResult,
        SurfaceTestResult,
        DiskSpeedTestResult,
        BitLockerStatus,
        SystemBackupInfo,
    )
    from diskforge.core.config import SystemBackupConfig
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
    def resize_move_dynamic_volume(
        self,
        options: DynamicVolumeResizeMoveOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Resize or move a dynamic volume.
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
    def extend_dynamic_volume(
        self,
        volume_id: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Extend a dynamic volume.
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
    def shrink_dynamic_volume(
        self,
        volume_id: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Shrink a dynamic volume.
        Returns (success, message/error).
        """

    @abstractmethod
    def allocate_free_space(
        self,
        options: AllocateFreeSpaceOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Allocate free space between partitions.
        Returns (success, message/error).
        """

    @abstractmethod
    def one_click_adjust_space(
        self,
        options: OneClickAdjustOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Auto-adjust space on a disk.
        Returns (success, message/error).
        """

    @abstractmethod
    def quick_partition_disk(
        self,
        options: QuickPartitionOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Quickly partition a disk.
        Returns (success, message/error).
        """

    @abstractmethod
    def change_partition_attributes(
        self,
        options: PartitionAttributeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Change partition attributes (drive letter, label, type ID, serial number).
        Returns (success, message/error).
        """

    @abstractmethod
    def initialize_disk(
        self,
        options: InitializeDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Initialize a disk with a partition style.
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
    def wipe_system_disk(
        self,
        options: SystemDiskWipeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Wipe a system disk with strict safeguards.
        Returns (success, message/error).
        """

    @abstractmethod
    def secure_erase_ssd(
        self,
        options: SSDSecureEraseOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Perform a secure erase workflow on an SSD.
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
    def convert_system_disk_partition_style(
        self,
        options: ConvertSystemDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Convert system disk partition style (MBR/GPT) with safety checks.
        Returns (success, message/error).
        """

    @abstractmethod
    def convert_partition_filesystem(
        self,
        options: ConvertFilesystemOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Convert a partition filesystem (NTFS/FAT32).
        Returns (success, message/error).
        """

    @abstractmethod
    def convert_partition_role(
        self,
        options: ConvertPartitionRoleOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Convert a partition between primary/logical.
        Returns (success, message/error).
        """

    @abstractmethod
    def convert_disk_layout(
        self,
        options: ConvertDiskLayoutOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Convert a disk between basic/dynamic.
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

    # ==================== Maintenance Operations ====================

    @abstractmethod
    def defrag_disk(
        self,
        device_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Defragment a disk's partitions.
        Returns (success, message/error).
        """

    @abstractmethod
    def defrag_partition(
        self,
        partition_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """
        Defragment a partition.
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
        mode: CloneMode = CloneMode.INTELLIGENT,
        schedule: str | None = None,
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
        mode: CloneMode = CloneMode.INTELLIGENT,
        schedule: str | None = None,
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
        compression_level: CompressionLevel | None = None,
        verify: bool = True,
        mode: CloneMode = CloneMode.INTELLIGENT,
        schedule: str | None = None,
        backup_type: BackupType | None = None,
        extra_metadata: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, ImageInfo | None]:
        """
        Create a disk/partition image.
        Returns (success, message/error, image_info).
        """

    @abstractmethod
    def create_system_backup(
        self,
        output_path: Path,
        context: JobContext | None = None,
        profile: SystemBackupConfig | None = None,
        compression: str | None = "zstd",
        compression_level: CompressionLevel | None = None,
        verify: bool = True,
        mode: CloneMode = CloneMode.INTELLIGENT,
        dry_run: bool = False,
    ) -> tuple[bool, str, SystemBackupInfo | None]:
        """
        Create a system backup bundle.
        Returns (success, message/error, system_backup_info).
        """

    @abstractmethod
    def restore_image(
        self,
        image_path: Path,
        target_path: str,
        context: JobContext | None = None,
        verify: bool = True,
        schedule: str | None = None,
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

    # ==================== Boot & Recovery Operations ====================

    @abstractmethod
    def integrate_recovery_environment(
        self,
        options: WinREIntegrationOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Integrate DiskForge into the Windows Recovery Environment."""

    @abstractmethod
    def repair_boot(
        self,
        options: BootRepairOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Repair Windows boot configuration and files."""

    @abstractmethod
    def rebuild_mbr(
        self,
        options: RebuildMBROptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Rebuild the Master Boot Record (MBR)."""

    @abstractmethod
    def manage_uefi_boot_options(
        self,
        options: UEFIBootOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """List or update UEFI boot options."""

    @abstractmethod
    def create_windows_to_go(
        self,
        options: WindowsToGoOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Create a Windows To Go workspace."""

    @abstractmethod
    def reset_windows_password(
        self,
        options: WindowsPasswordResetOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Reset a Windows local account password."""

    # ==================== BitLocker Operations ====================

    @abstractmethod
    def get_bitlocker_status(self, mount_point: str) -> BitLockerStatus:
        """Get BitLocker status for a volume."""

    @abstractmethod
    def enable_bitlocker(self, mount_point: str) -> tuple[bool, str]:
        """Enable BitLocker on a volume."""

    @abstractmethod
    def disable_bitlocker(self, mount_point: str) -> tuple[bool, str]:
        """Disable BitLocker on a volume."""

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

    # ==================== Diagnostics Operations ====================

    @abstractmethod
    def bad_sector_scan(
        self,
        options: BadSectorScanOptions,
        context: JobContext | None = None,
    ) -> BadSectorScanResult:
        """Scan a disk for bad sectors."""

    @abstractmethod
    def disk_health_check(
        self,
        device_path: str,
        context: JobContext | None = None,
    ) -> DiskHealthResult:
        """Check disk health status."""

    @abstractmethod
    def disk_speed_test(
        self,
        options: DiskSpeedTestOptions,
        context: JobContext | None = None,
    ) -> DiskSpeedTestResult:
        """Measure disk read speed."""

    @abstractmethod
    def surface_test(
        self,
        options: SurfaceTestOptions,
        context: JobContext | None = None,
    ) -> SurfaceTestResult:
        """Run a surface test on a disk."""

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

    # ==================== Storage Cleanup Operations ====================

    @abstractmethod
    def scan_free_space(self, options: FreeSpaceOptions) -> FreeSpaceReport:
        """Summarize reclaimable space in the given roots."""

    @abstractmethod
    def scan_junk_files(self, options: JunkCleanupOptions) -> JunkScanResult:
        """Scan for junk files in the given roots."""

    @abstractmethod
    def cleanup_junk_files(self, options: JunkCleanupOptions) -> JunkCleanupResult:
        """Remove junk files from the given roots."""

    @abstractmethod
    def scan_large_files(self, options: LargeFileScanOptions) -> LargeFileScanResult:
        """Scan for large files in the given roots."""

    @abstractmethod
    def remove_large_files(self, options: FileRemovalOptions) -> FileRemovalResult:
        """Remove large files by path."""

    @abstractmethod
    def scan_duplicate_files(self, options: DuplicateScanOptions) -> DuplicateScanResult:
        """Scan for duplicate files in the given roots."""

    @abstractmethod
    def remove_duplicate_files(self, options: DuplicateRemovalOptions) -> FileRemovalResult:
        """Remove duplicate files based on scan groups."""

    @abstractmethod
    def move_application(self, options: MoveApplicationOptions) -> MoveApplicationResult:
        """Move an application directory to another drive."""

    # ==================== Recovery & Shredding Operations ====================

    @abstractmethod
    def recover_files(
        self,
        options: FileRecoveryOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Attempt to recover deleted files."""

    @abstractmethod
    def shred_files(
        self,
        options: ShredOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Securely shred files or folders."""
