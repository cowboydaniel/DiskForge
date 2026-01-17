"""
Windows Platform Backend Implementation.

Implements disk operations using Windows tools:
- PowerShell with Get-Disk, Get-Partition, Get-Volume
- diskpart for partitioning
- Windows native tools for imaging
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from diskforge.core.config import SystemBackupConfig
from diskforge.core.logging import get_logger
from diskforge.core.models import (
    BackupType,
    CloneMode,
    CompressionLevel,
    Disk,
    DiskInventory,
    DiskLayout,
    FileSystem,
    ImageInfo,
    Partition,
    PartitionFlag,
    PartitionStyle,
    SystemBackupInfo,
    BadSectorScanOptions,
    SurfaceTestOptions,
    DiskSpeedTestOptions,
    DiskHealthResult,
    BadSectorScanResult,
    SurfaceTestResult,
    DiskSpeedTestResult,
    BitLockerStatus,
)
from diskforge.platform.base import CommandResult, PlatformBackend
from diskforge.platform.file_ops import (
    build_free_space_report,
    cleanup_junk_files,
    move_application,
    normalize_roots,
    remove_paths,
    scan_duplicate_files,
    scan_junk_files,
    scan_large_files,
)
from diskforge.platform.windows.parsers import (
    build_disk_from_powershell,
    parse_diskpart_output,
    parse_powershell_json,
)

if TYPE_CHECKING:
    from diskforge.core.job import JobContext
    from diskforge.core.models import (
        AlignOptions,
        ConvertDiskOptions,
        ConvertDiskLayoutOptions,
        ConvertFilesystemOptions,
        ConvertPartitionRoleOptions,
        ConvertSystemDiskOptions,
        FormatOptions,
        MergePartitionsOptions,
        MigrationOptions,
        AllocateFreeSpaceOptions,
        OneClickAdjustOptions,
        QuickPartitionOptions,
        PartitionAttributeOptions,
        InitializeDiskOptions,
        PartitionCreateOptions,
        PartitionRecoveryOptions,
        WinREIntegrationOptions,
        BootRepairOptions,
        RebuildMBROptions,
        UEFIBootOptions,
        WindowsToGoOptions,
        WindowsPasswordResetOptions,
        DynamicVolumeResizeMoveOptions,
        DuplicateRemovalOptions,
        DuplicateScanOptions,
        FileRecoveryOptions,
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
    )

logger = get_logger(__name__)


class WindowsBackend(PlatformBackend):
    """Windows implementation of disk operations."""

    POWERSHELL = "powershell.exe"
    DISKPART = "diskpart.exe"
    DEFRAG = "defrag.exe"

    @property
    def name(self) -> str:
        return "windows"

    @property
    def requires_admin(self) -> bool:
        return True

    def is_admin(self) -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def run_command(
        self,
        command: list[str],
        timeout: int = 300,
        check: bool = True,
        capture_output: bool = True,
    ) -> CommandResult:
        """Run a system command."""
        logger.debug("Running command", command=command)
        start_time = time.time()

        try:
            # Use CREATE_NO_WINDOW flag to hide console
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run(
                command,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                startupinfo=startupinfo,
            )
            duration = time.time() - start_time

            cmd_result = CommandResult(
                returncode=result.returncode,
                stdout=result.stdout if capture_output else "",
                stderr=result.stderr if capture_output else "",
                command=command,
                duration_seconds=duration,
            )

            if check and result.returncode != 0:
                logger.warning(
                    "Command failed",
                    command=command,
                    returncode=result.returncode,
                    stderr=result.stderr[:500] if result.stderr else "",
                )

            return cmd_result
        except subprocess.TimeoutExpired:
            return CommandResult(
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                command=command,
                duration_seconds=timeout,
            )
        except Exception as e:
            return CommandResult(
                returncode=-1,
                stdout="",
                stderr=str(e),
                command=command,
                duration_seconds=time.time() - start_time,
            )

    def _python_shred_file(self, path: Path, passes: int, zero_fill: bool) -> tuple[bool, str]:
        try:
            if path.is_symlink():
                path.unlink()
                return True, f"Removed symlink {path}"

            size = path.stat().st_size
            chunk_size = 1024 * 1024

            with path.open("r+b", buffering=0) as handle:
                for pass_index in range(passes):
                    handle.seek(0)
                    remaining = size
                    while remaining > 0:
                        block = min(chunk_size, remaining)
                        if pass_index == passes - 1 and zero_fill:
                            data = b"\x00" * block
                        else:
                            data = os.urandom(block)
                        handle.write(data)
                        remaining -= block
                    handle.flush()
                    os.fsync(handle.fileno())

            path.unlink()
            return True, f"Shredded {path}"
        except OSError as exc:
            return False, f"Failed to shred {path}: {exc}"

    def _shred_path(
        self,
        path: Path,
        passes: int,
        zero_fill: bool,
        follow_symlinks: bool,
    ) -> tuple[bool, str]:
        if path.is_symlink() and not follow_symlinks:
            try:
                path.unlink()
                return True, f"Removed symlink {path}"
            except OSError as exc:
                return False, f"Failed to remove symlink {path}: {exc}"

        if path.is_dir():
            errors: list[str] = []
            for root, dirs, files in os.walk(path, topdown=False, followlinks=follow_symlinks):
                for filename in files:
                    file_path = Path(root) / filename
                    success, message = self._shred_path(
                        file_path,
                        passes,
                        zero_fill,
                        follow_symlinks,
                    )
                    if not success:
                        errors.append(message)
                for dirname in dirs:
                    dir_path = Path(root) / dirname
                    if dir_path.is_symlink() and not follow_symlinks:
                        try:
                            dir_path.unlink()
                        except OSError as exc:
                            errors.append(f"Failed to remove symlink {dir_path}: {exc}")
                        continue
                    try:
                        dir_path.rmdir()
                    except OSError:
                        pass

            try:
                path.rmdir()
            except OSError:
                pass

            if errors:
                return False, "; ".join(errors)
            return True, f"Shredded directory {path}"

        return self._python_shred_file(path, passes, zero_fill)

    def _run_powershell(
        self,
        script: str,
        timeout: int = 300,
    ) -> CommandResult:
        """Run a PowerShell script."""
        cmd = [
            self.POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ]
        return self.run_command(cmd, timeout=timeout)

    def _run_diskpart(
        self,
        commands: list[str],
        timeout: int = 300,
    ) -> CommandResult:
        """Run diskpart with a script."""
        script_content = "\n".join(commands)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
        ) as f:
            f.write(script_content)
            script_path = f.name

        try:
            cmd = [self.DISKPART, "/s", script_path]
            return self.run_command(cmd, timeout=timeout)
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _get_drive_letter(self, partition: Partition) -> str | None:
        if partition.drive_letter:
            return partition.drive_letter.rstrip(":")
        mountpoint = partition.mountpoint or ""
        if len(mountpoint) >= 2 and mountpoint[1] == ":":
            return mountpoint[0]
        return None

    def get_disk_inventory(self) -> DiskInventory:
        """Get complete disk inventory using PowerShell."""
        inventory = DiskInventory(platform="windows")

        # Get disk information
        disk_script = """
        Get-Disk | Select-Object Number, FriendlyName, SerialNumber, Size,
            LogicalSectorSize, BusType, MediaType, PartitionStyle,
            IsOffline, IsReadOnly, Manufacturer |
        ConvertTo-Json -Compress
        """
        disk_result = self._run_powershell(disk_script)

        if not disk_result.success:
            inventory.errors.append(f"Get-Disk failed: {disk_result.stderr}")
            return inventory

        disks_data = parse_powershell_json(disk_result.stdout)

        # Get partition information
        part_script = """
        Get-Partition | Select-Object DiskNumber, PartitionNumber, Offset, Size,
            Type, IsBoot, IsSystem, IsHidden, IsActive, GptType, Guid, AccessPaths |
        ConvertTo-Json -Compress
        """
        part_result = self._run_powershell(part_script)
        partitions_data = parse_powershell_json(part_result.stdout) if part_result.success else []

        # Get volume information
        vol_script = """
        Get-Volume | Select-Object DriveLetter, FileSystem, FileSystemLabel,
            Size, SizeRemaining |
        ConvertTo-Json -Compress
        """
        vol_result = self._run_powershell(vol_script)
        volumes_data = parse_powershell_json(vol_result.stdout) if vol_result.success else []

        # Get system disk number
        system_disk = self._get_system_disk_number()

        # Build disk objects
        for disk_data in disks_data:
            try:
                disk = build_disk_from_powershell(
                    disk_data,
                    partitions_data,
                    volumes_data,
                    system_disk,
                )
                inventory.disks.append(disk)
            except Exception as e:
                logger.warning(
                    "Failed to parse disk",
                    disk_number=disk_data.get("Number"),
                    error=str(e),
                )
                inventory.errors.append(f"Failed to parse disk {disk_data.get('Number')}: {e}")

        inventory.timestamp = datetime.now()
        return inventory

    def get_disk_info(self, device_path: str) -> Disk | None:
        """Get information about a specific disk."""
        inventory = self.get_disk_inventory()
        return inventory.get_disk_by_path(device_path)

    def get_partition_info(self, device_path: str) -> Partition | None:
        """Get information about a specific partition."""
        inventory = self.get_disk_inventory()
        result = inventory.get_partition_by_path(device_path)
        return result[1] if result else None

    def refresh_disk(self, device_path: str) -> Disk | None:
        """Refresh information for a specific disk."""
        return self.get_disk_info(device_path)

    def _get_system_disk_number(self) -> int | None:
        """Get the disk number containing the system partition."""
        script = """
        $systemDrive = $env:SystemDrive
        $partition = Get-Partition | Where-Object { $_.AccessPaths -contains "$systemDrive\\" }
        if ($partition) { $partition.DiskNumber } else { -1 }
        """
        result = self._run_powershell(script)
        if result.success:
            try:
                return int(result.stdout.strip())
            except ValueError:
                pass
        return None

    def _extract_disk_number(self, device_path: str) -> int | None:
        """Extract disk number from device path."""
        import re

        match = re.search(r"PhysicalDrive(\d+)", device_path)
        if match:
            return int(match.group(1))
        return None

    # ==================== Partition Operations ====================

    def create_partition(
        self,
        options: PartitionCreateOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Create a new partition using PowerShell/diskpart."""
        disk_number = self._extract_disk_number(options.disk_path)
        if disk_number is None:
            return False, f"Cannot parse disk number from: {options.disk_path}"

        disk = self.get_disk_info(options.disk_path)
        if disk and disk.is_system_disk:
            return False, "Cannot modify system disk"

        if context:
            context.update_progress(message=f"Creating partition on disk {disk_number}")

        # Build PowerShell command
        size_param = ""
        if options.size_bytes:
            size_mb = options.size_bytes // (1024 * 1024)
            size_param = f"-Size {size_mb}MB"
        else:
            size_param = "-UseMaximumSize"

        script = f"New-Partition -DiskNumber {disk_number} {size_param} -AssignDriveLetter"

        if dry_run:
            return True, f"Would run: {script}"

        result = self._run_powershell(script)

        if not result.success:
            return False, f"New-Partition failed: {result.stderr}"

        return True, "Partition created successfully"

    def delete_partition(
        self,
        partition_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Delete a partition using PowerShell."""
        # Parse partition info from path
        import re

        match = re.search(r"PhysicalDrive(\d+)Partition(\d+)", partition_path)
        if not match:
            return False, f"Cannot parse partition path: {partition_path}"

        disk_number = int(match.group(1))
        part_number = int(match.group(2))

        # Check if system disk
        disk = self.get_disk_info(f"\\\\.\\PhysicalDrive{disk_number}")
        if disk and disk.is_system_disk:
            return False, "Cannot modify system disk"

        partition = self.get_partition_info(partition_path)
        if partition and partition.is_mounted:
            return False, f"Partition is mounted at {partition.mountpoint}. Remove drive letter first."

        if context:
            context.update_progress(message=f"Deleting partition {part_number} from disk {disk_number}")

        script = f"""
        Remove-Partition -DiskNumber {disk_number} -PartitionNumber {part_number} -Confirm:$false
        """

        if dry_run:
            return True, f"Would delete partition {part_number} from disk {disk_number}"

        result = self._run_powershell(script)

        if not result.success:
            return False, f"Remove-Partition failed: {result.stderr}"

        return True, f"Partition {partition_path} deleted"

    def format_partition(
        self,
        options: FormatOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Format a partition using PowerShell."""
        partition = self.get_partition_info(options.partition_path)
        if not partition:
            return False, f"Partition not found: {options.partition_path}"

        if not partition.mountpoint:
            return False, "Partition must have a drive letter to format"

        drive_letter = partition.mountpoint[0]

        # Map filesystem to Windows format type
        fs_map = {
            FileSystem.NTFS: "NTFS",
            FileSystem.FAT32: "FAT32",
            FileSystem.EXFAT: "exFAT",
            FileSystem.REFS: "ReFS",
        }

        if options.filesystem not in fs_map:
            return False, f"Unsupported filesystem for Windows: {options.filesystem.value}"

        fs_type = fs_map[options.filesystem]

        if context:
            context.update_progress(
                message=f"Formatting {drive_letter}: as {fs_type}"
            )

        label_param = f'-NewFileSystemLabel "{options.label}"' if options.label else ""
        quick_param = "-Full:$false" if options.quick else "-Full:$true"

        script = f"""
        Format-Volume -DriveLetter {drive_letter} -FileSystem {fs_type} {label_param} {quick_param} -Confirm:$false
        """

        if dry_run:
            return True, f"Would format {drive_letter}: as {fs_type}"

        result = self._run_powershell(script, timeout=3600)

        if not result.success:
            return False, f"Format failed: {result.stderr}"

        return True, f"Formatted {drive_letter}: as {fs_type}"

    def resize_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Resize a partition using PowerShell."""
        import re

        match = re.search(r"PhysicalDrive(\d+)Partition(\d+)", partition_path)
        if not match:
            return False, f"Cannot parse partition path: {partition_path}"

        disk_number = int(match.group(1))
        part_number = int(match.group(2))

        partition = self.get_partition_info(partition_path)
        if not partition:
            return False, f"Partition not found: {partition_path}"

        if context:
            context.update_progress(
                message=f"Resizing partition to {new_size_bytes} bytes"
            )

        script = f"""
        Resize-Partition -DiskNumber {disk_number} -PartitionNumber {part_number} -Size {new_size_bytes}
        """

        if dry_run:
            return True, f"Would resize partition to {new_size_bytes} bytes"

        result = self._run_powershell(script, timeout=3600)

        if not result.success:
            return False, f"Resize failed: {result.stderr}"

        return True, f"Resized partition to {new_size_bytes} bytes"

    def resize_move_partition(
        self,
        options: ResizeMoveOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Resize or move a partition."""
        partition = self.get_partition_info(options.partition_path)
        if not partition:
            return False, f"Partition not found: {options.partition_path}"

        if options.new_start_sector is not None and options.new_start_sector != partition.start_sector:
            return False, "Partition move is not supported in the Windows backend yet"

        if options.new_size_bytes is None:
            return False, "New size is required for resize operations"

        return self.resize_partition(
            options.partition_path,
            options.new_size_bytes,
            context=context,
            dry_run=dry_run,
        )

    def resize_move_dynamic_volume(
        self,
        options: DynamicVolumeResizeMoveOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Resize or move a dynamic volume."""
        if options.new_start_sector is not None:
            return False, "Dynamic volume moves are not supported in the Windows backend yet"

        if options.new_size_bytes is None:
            return False, "New size is required for dynamic volume resize operations"

        if context:
            context.update_progress(
                message=f"Resizing dynamic volume {options.volume_id} to {options.new_size_bytes} bytes"
            )

        if dry_run:
            return True, (
                f"Would resize dynamic volume {options.volume_id} to {options.new_size_bytes} bytes"
            )

        return False, "Dynamic volume resize/move is not supported in the Windows backend yet"

    def merge_partitions(
        self,
        options: MergePartitionsOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Merge two partitions."""
        if context:
            context.update_progress(message="Preparing partition merge")

        if dry_run:
            return True, (
                f"Would merge {options.secondary_partition_path} into "
                f"{options.primary_partition_path}"
            )

        return False, "Partition merge is not supported in the Windows backend yet"

    def split_partition(
        self,
        options: SplitPartitionOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Split a partition into two."""
        partition = self.get_partition_info(options.partition_path)
        if not partition:
            return False, f"Partition not found: {options.partition_path}"

        if partition.is_mounted:
            return False, "Partition must be unmounted before splitting"

        if options.split_size_bytes >= partition.size_bytes:
            return False, "Split size must be smaller than the original partition size"

        if context:
            context.update_progress(message="Preparing partition split")

        if dry_run:
            return True, f"Would split {options.partition_path}"

        return False, "Partition split is not supported in the Windows backend yet"

    def extend_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Extend a partition."""
        return self.resize_partition(
            partition_path,
            new_size_bytes,
            context=context,
            dry_run=dry_run,
        )

    def extend_dynamic_volume(
        self,
        volume_id: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Extend a dynamic volume."""
        if context:
            context.update_progress(
                message=f"Extending dynamic volume {volume_id} to {new_size_bytes} bytes"
            )

        if dry_run:
            return True, f"Would extend dynamic volume {volume_id} to {new_size_bytes} bytes"

        return False, "Dynamic volume extension is not supported in the Windows backend yet"

    def shrink_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Shrink a partition."""
        return self.resize_partition(
            partition_path,
            new_size_bytes,
            context=context,
            dry_run=dry_run,
        )

    def shrink_dynamic_volume(
        self,
        volume_id: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Shrink a dynamic volume."""
        if context:
            context.update_progress(
                message=f"Shrinking dynamic volume {volume_id} to {new_size_bytes} bytes"
            )

        if dry_run:
            return True, f"Would shrink dynamic volume {volume_id} to {new_size_bytes} bytes"

        return False, "Dynamic volume shrink is not supported in the Windows backend yet"

    def allocate_free_space(
        self,
        options: AllocateFreeSpaceOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Allocate free space is not supported in the Windows backend yet"

    def one_click_adjust_space(
        self,
        options: OneClickAdjustOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "One-click adjust space is not supported in the Windows backend yet"

    def quick_partition_disk(
        self,
        options: QuickPartitionOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Quick partitioning is not supported in the Windows backend yet"

    def change_partition_attributes(
        self,
        options: PartitionAttributeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Changing partition attributes is not supported in the Windows backend yet"

    def initialize_disk(
        self,
        options: InitializeDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Disk initialization is not supported in the Windows backend yet"

    def wipe_device(
        self,
        options: WipeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Wipe a disk or partition."""
        disk = self.get_disk_info(options.target_path)
        partition = self.get_partition_info(options.target_path)

        if not disk and not partition:
            return False, f"Target not found: {options.target_path}"

        if disk and disk.is_system_disk:
            return False, "Cannot wipe the system disk"

        if context:
            context.update_progress(message=f"Wiping {options.target_path}")

        if dry_run:
            return True, f"Would wipe {options.target_path}"

        if disk:
            disk_number = self._extract_disk_number(options.target_path)
            if disk_number is None:
                return False, f"Cannot parse disk number from: {options.target_path}"

            result = self._run_diskpart(
                [
                    f"select disk {disk_number}",
                    "clean all",
                ],
                timeout=86400,
            )
            if not result.success:
                return False, f"Disk wipe failed: {result.stderr}"
            return True, f"Wiped disk {options.target_path}"

        if not partition or not partition.mountpoint:
            return False, "Partition must have a drive letter to wipe"

        drive_letter = partition.mountpoint[0]
        script = f"""
        Format-Volume -DriveLetter {drive_letter} -FileSystem NTFS -Full -Confirm:$false
        """
        result = self._run_powershell(script, timeout=86400)
        if not result.success:
            return False, f"Partition wipe failed: {result.stderr}"

        return True, f"Wiped partition {options.target_path}"

    def wipe_system_disk(
        self,
        options: SystemDiskWipeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "System disk wipe is not supported in the Windows backend yet"

    def secure_erase_ssd(
        self,
        options: SSDSecureEraseOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "SSD secure erase is not supported in the Windows backend yet"

    def recover_partitions(
        self,
        options: PartitionRecoveryOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Attempt to recover partitions."""
        artifacts: dict[str, Any] = {}

        if context:
            context.update_progress(message="Preparing partition recovery")

        if dry_run:
            return True, f"Would run recovery on {options.disk_path}", artifacts

        return (
            False,
            "Partition recovery requires external recovery tooling on Windows",
            artifacts,
        )

    def recover_files(
        self,
        options: FileRecoveryOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Attempt to recover deleted files."""
        artifacts: dict[str, Any] = {"output": str(options.output_path)}

        if context:
            context.update_progress(message="Preparing file recovery")

        if dry_run:
            return True, f"Would recover files from {options.source_path}", artifacts

        return (
            False,
            "File recovery requires external recovery tooling on Windows",
            artifacts,
        )

    def shred_files(
        self,
        options: ShredOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Securely shred files or folders."""
        targets = [Path(target) for target in options.targets]
        missing = [str(target) for target in targets if not target.exists() and not target.is_symlink()]
        if missing:
            return False, f"Targets not found: {', '.join(missing)}"

        if context:
            context.update_progress(message="Shredding files")

        if dry_run:
            return True, f"Would shred {len(targets)} target(s)"

        errors: list[str] = []
        for target in targets:
            success, message = self._shred_path(
                target,
                max(1, options.passes),
                options.zero_fill,
                options.follow_symlinks,
            )
            if not success:
                errors.append(message)

        if errors:
            return False, "; ".join(errors)
        return True, "Shredding completed"

    def align_partition_4k(
        self,
        options: AlignOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Align a partition to 4K boundaries."""
        inventory = self.get_disk_inventory()
        result = inventory.get_partition_by_path(options.partition_path)
        if not result:
            return False, f"Partition not found: {options.partition_path}"

        disk, partition = result
        sector_size = disk.sector_size or 512
        alignment_sectors = max(1, options.alignment_bytes // sector_size)

        if partition.start_sector % alignment_sectors == 0:
            return True, f"{options.partition_path} is already 4K aligned"

        if context:
            context.update_progress(message="Alignment requires partition move")

        if dry_run:
            return True, f"Would align {options.partition_path} to 4K boundaries"

        return False, "Alignment requires moving the partition, which is not supported yet"

    def convert_disk_partition_style(
        self,
        options: ConvertDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Convert disk partition style (MBR/GPT)."""
        disk = self.get_disk_info(options.disk_path)
        if not disk:
            return False, f"Disk not found: {options.disk_path}"

        if disk.is_system_disk and options.target_style != PartitionStyle.GPT:
            return False, "Cannot convert the system disk to MBR"

        if disk.partition_style == options.target_style:
            return True, f"Disk already uses {options.target_style.name}"

        disk_number = self._extract_disk_number(options.disk_path)
        if disk_number is None:
            return False, f"Cannot parse disk number from: {options.disk_path}"

        if context:
            context.update_progress(
                message=f"Converting disk {disk_number} to {options.target_style.name}"
            )

        if dry_run:
            return True, f"Would convert disk {disk_number} to {options.target_style.name}"

        if options.target_style == PartitionStyle.GPT:
            cmd = ["mbr2gpt", "/convert", f"/disk:{disk_number}", "/allowFullOS"]
            result = self.run_command(cmd, timeout=600, check=False)
            if not result.success:
                return False, f"MBR2GPT failed: {result.stderr}"
            return True, f"Converted disk {disk_number} to GPT"

        return False, "GPT to MBR conversion is not supported in the Windows backend"

    def convert_system_disk_partition_style(
        self,
        options: ConvertSystemDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Convert system disk partition style with safety checks."""
        disk = self.get_disk_info(options.disk_path)
        if not disk:
            return False, f"Disk not found: {options.disk_path}"

        if not disk.is_system_disk:
            return False, "Selected disk is not marked as a system disk"

        if disk.partition_style == options.target_style:
            return True, f"Disk already uses {options.target_style.name}"

        if options.target_style != PartitionStyle.GPT:
            return False, "System disk conversion to MBR is not supported"

        disk_number = self._extract_disk_number(options.disk_path)
        if disk_number is None:
            return False, f"Cannot parse disk number from: {options.disk_path}"

        allow_flag = ["/allowFullOS"] if options.allow_full_os else []

        if context:
            context.update_progress(message=f"Validating system disk {disk_number} for GPT conversion")

        if dry_run:
            return True, f"Would validate and convert system disk {disk_number} to GPT"

        validate_cmd = ["mbr2gpt", "/validate", f"/disk:{disk_number}", *allow_flag]
        validate_result = self.run_command(validate_cmd, timeout=600, check=False)
        if not validate_result.success:
            return False, f"MBR2GPT validation failed: {validate_result.stderr}"

        if context:
            context.update_progress(message=f"Converting system disk {disk_number} to GPT")

        convert_cmd = ["mbr2gpt", "/convert", f"/disk:{disk_number}", *allow_flag]
        result = self.run_command(convert_cmd, timeout=600, check=False)
        if not result.success:
            return False, f"MBR2GPT failed: {result.stderr}"
        return True, f"Converted system disk {disk_number} to GPT"

    def convert_partition_filesystem(
        self,
        options: ConvertFilesystemOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Convert a partition filesystem (NTFS/FAT32)."""
        partition = self.get_partition_info(options.partition_path)
        if not partition:
            return False, f"Partition not found: {options.partition_path}"

        if partition.is_system:
            return False, "Cannot convert the system partition filesystem"

        current_fs = partition.filesystem
        target_fs = options.target_filesystem

        if current_fs == target_fs:
            return True, f"Partition already uses {target_fs.value}"

        drive_letter = self._get_drive_letter(partition)
        if not drive_letter:
            return False, "Partition must have a drive letter to convert the filesystem"

        if target_fs == FileSystem.NTFS:
            if current_fs not in {FileSystem.FAT32, FileSystem.FAT16}:
                return False, "Only FAT32/FAT16 to NTFS conversion is supported"
            cmd = ["cmd", "/c", "convert", f"{drive_letter}:", "/fs:ntfs", "/nosecurity"]
            if context:
                context.update_progress(message=f"Converting {drive_letter}: to NTFS")
            if dry_run:
                return True, f"Would run: {' '.join(cmd)}"
            result = self.run_command(cmd, timeout=3600, check=False)
            if not result.success:
                return False, f"Convert failed: {result.stderr}"
            return True, f"Converted {drive_letter}: to NTFS"

        if target_fs == FileSystem.FAT32:
            if current_fs != FileSystem.NTFS:
                return False, "Only NTFS to FAT32 conversion is supported"
            if not options.allow_format:
                return False, "NTFS to FAT32 requires formatting; re-run with allow_format"
            cmd = ["cmd", "/c", "format", f"{drive_letter}:", "/fs:FAT32", "/q", "/y"]
            if context:
                context.update_progress(message=f"Formatting {drive_letter}: as FAT32")
            if dry_run:
                return True, f"Would run: {' '.join(cmd)}"
            result = self.run_command(cmd, timeout=3600, check=False)
            if not result.success:
                return False, f"Format failed: {result.stderr}"
            return True, f"Formatted {drive_letter}: as FAT32"

        return False, "Unsupported target filesystem"

    def convert_partition_role(
        self,
        options: ConvertPartitionRoleOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Convert a partition between primary/logical."""
        inventory = self.get_disk_inventory()
        result = inventory.get_partition_by_path(options.partition_path)
        if not result:
            return False, f"Partition not found: {options.partition_path}"

        disk, partition = result
        if disk.partition_style != PartitionStyle.MBR:
            return False, "Primary/logical conversion is only supported on MBR disks"

        if disk.is_system_disk:
            return False, "Cannot convert partition role on the system disk"

        return False, "Primary/logical conversion is not supported in the Windows backend"

    def convert_disk_layout(
        self,
        options: ConvertDiskLayoutOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Convert disk layout between basic/dynamic."""
        disk = self.get_disk_info(options.disk_path)
        if not disk:
            return False, f"Disk not found: {options.disk_path}"

        if disk.is_system_disk:
            return False, "Cannot convert the system disk layout"

        disk_number = self._extract_disk_number(options.disk_path)
        if disk_number is None:
            return False, f"Cannot parse disk number from: {options.disk_path}"

        target = "dynamic" if options.target_layout == DiskLayout.DYNAMIC else "basic"

        if context:
            context.update_progress(message=f"Converting disk {disk_number} to {target}")

        if dry_run:
            return True, f"Would convert disk {disk_number} to {target}"

        script = f\"select disk {disk_number}\\nconvert {target}\\n\"
        result = self._run_diskpart(script)
        if not result.success:
            return False, f"Disk layout conversion failed: {result.stderr}"

        return True, f"Converted disk {disk_number} to {target}"

    def migrate_system(
        self,
        options: MigrationOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Migrate OS/system to another disk."""
        source_disk = self.get_disk_info(options.source_disk_path)
        if not source_disk:
            return False, f"Source disk not found: {options.source_disk_path}"

        if not source_disk.is_system_disk:
            return False, "Source disk is not marked as a system disk"

        if context:
            context.update_progress(message="Starting system migration")

        return self.clone_disk(
            options.source_disk_path,
            options.target_disk_path,
            context=context,
            verify=True,
            dry_run=dry_run,
        )

    def defrag_disk(
        self,
        device_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        disk = self.get_disk_info(device_path)
        if not disk:
            return False, f"Disk not found: {device_path}"

        successes: list[str] = []
        skipped: list[str] = []
        failures: list[str] = []

        for partition in disk.partitions:
            drive_letter = self._get_drive_letter(partition)
            if not drive_letter:
                skipped.append(f"{partition.device_path}: no drive letter assigned")
                continue

            command = [self.DEFRAG, f"{drive_letter}:", "/U", "/V"]
            if context:
                context.update_progress(message=f"Defragmenting {drive_letter}:")

            if dry_run:
                successes.append(f"Would run: {' '.join(command)}")
                continue

            result = self.run_command(command, timeout=86400, check=False)
            if result.success:
                successes.append(f"Defragmented {drive_letter}:")
            else:
                failures.append(f"{drive_letter}: {result.stderr or 'defrag failed'}")

        summary_lines = []
        if successes:
            summary_lines.append("Successful:")
            summary_lines.extend(f"  - {line}" for line in successes)
        if skipped:
            summary_lines.append("Skipped:")
            summary_lines.extend(f"  - {line}" for line in skipped)
        if failures:
            summary_lines.append("Failed:")
            summary_lines.extend(f"  - {line}" for line in failures)

        if failures:
            return False, "\n".join(summary_lines)
        if successes:
            return True, "\n".join(summary_lines)
        return False, "\n".join(summary_lines or [f"No defragmentable volumes found on {device_path}"])

    def defrag_partition(
        self,
        partition_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        partition = self.get_partition_info(partition_path)
        if not partition:
            return False, f"Partition not found: {partition_path}"

        drive_letter = self._get_drive_letter(partition)
        if not drive_letter:
            return False, f"No drive letter assigned to {partition_path}"

        command = [self.DEFRAG, f"{drive_letter}:", "/U", "/V"]
        if context:
            context.update_progress(message=f"Defragmenting {drive_letter}:")

        if dry_run:
            return True, f"Would run: {' '.join(command)}"

        result = self.run_command(command, timeout=86400, check=False)
        if not result.success:
            return False, f"Defragmentation failed: {result.stderr}"

        return True, f"Defragmented {drive_letter}:"

    # ==================== Clone Operations ====================

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
        """Clone a disk block-by-block."""
        if mode == CloneMode.INTELLIGENT and context:
            context.add_warning(
                "Intelligent clone is not supported on Windows; using sector-by-sector copy."
            )
        source_disk = self.get_disk_info(source_path)
        target_disk = self.get_disk_info(target_path)

        if not source_disk:
            return False, f"Source disk not found: {source_path}"
        if not target_disk:
            return False, f"Target disk not found: {target_path}"

        if target_disk.is_system_disk:
            return False, "Cannot write to system disk"

        if target_disk.size_bytes < source_disk.size_bytes:
            return False, (
                f"Target ({target_disk.size_bytes} bytes) is smaller than "
                f"source ({source_disk.size_bytes} bytes)"
            )

        # Check target is not mounted
        for partition in target_disk.partitions:
            if partition.is_mounted:
                return False, f"Target partition {partition.mountpoint} is mounted"

        if context:
            context.update_progress(
                message=f"Cloning {source_path} to {target_path}",
                bytes_total=source_disk.size_bytes,
            )

        if dry_run:
            return True, f"Would clone {source_path} to {target_path}"

        return self._run_block_copy(
            source_path,
            target_path,
            source_disk.size_bytes,
            context,
            verify,
        )

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
        """Clone a partition block-by-block."""
        if mode == CloneMode.INTELLIGENT and context:
            context.add_warning(
                "Intelligent clone is not supported on Windows; using sector-by-sector copy."
            )
        source_part = self.get_partition_info(source_path)
        target_part = self.get_partition_info(target_path)

        if not source_part:
            return False, f"Source partition not found: {source_path}"
        if not target_part:
            return False, f"Target partition not found: {target_path}"

        if source_part.is_mounted:
            return False, f"Source partition is mounted at {source_part.mountpoint}"
        if target_part.is_mounted:
            return False, f"Target partition is mounted at {target_part.mountpoint}"

        if target_part.size_bytes < source_part.size_bytes:
            return False, (
                f"Target ({target_part.size_bytes} bytes) is smaller than "
                f"source ({source_part.size_bytes} bytes)"
            )

        if context:
            context.update_progress(
                message=f"Cloning {source_path} to {target_path}",
                bytes_total=source_part.size_bytes,
            )

        if dry_run:
            return True, f"Would clone {source_path} to {target_path}"

        return self._run_block_copy(
            source_path,
            target_path,
            source_part.size_bytes,
            context,
            verify,
        )

    def _run_block_copy(
        self,
        source: str,
        target: str,
        total_bytes: int,
        context: JobContext | None,
        verify: bool,
    ) -> tuple[bool, str]:
        """Run block-level copy using Python file operations."""
        block_size = 64 * 1024 * 1024  # 64 MB

        logger.info("Starting block copy", source=source, target=target, total_bytes=total_bytes)

        try:
            with open(source, "rb") as src, open(target, "r+b") as tgt:
                bytes_copied = 0
                start_time = time.time()

                while bytes_copied < total_bytes:
                    if context:
                        context.check_cancelled()
                        context.wait_if_paused()

                    data = src.read(block_size)
                    if not data:
                        break

                    tgt.write(data)
                    bytes_copied += len(data)

                    if context:
                        elapsed = time.time() - start_time
                        rate = bytes_copied / elapsed if elapsed > 0 else 0
                        context.update_progress(
                            current=int((bytes_copied / total_bytes) * 100),
                            bytes_processed=bytes_copied,
                            rate_bytes_per_sec=rate,
                            message=f"Copied {bytes_copied:,} bytes",
                        )

                tgt.flush()
                os.fsync(tgt.fileno())

            # Verify if requested
            if verify:
                if context:
                    context.update_progress(message="Verifying copy...")

                success, msg = self._verify_copy(source, target, total_bytes, context)
                if not success:
                    return False, f"Verification failed: {msg}"

            return True, "Clone completed successfully"

        except PermissionError:
            return False, "Permission denied. Run as Administrator."
        except Exception as e:
            return False, f"Clone failed: {e}"

    def _verify_copy(
        self,
        source: str,
        target: str,
        size_bytes: int,
        context: JobContext | None,
    ) -> tuple[bool, str]:
        """Verify copy by comparing blocks."""
        block_size = 64 * 1024 * 1024

        try:
            with open(source, "rb") as src, open(target, "rb") as tgt:
                bytes_verified = 0
                block_num = 0

                while bytes_verified < size_bytes:
                    if context:
                        context.check_cancelled()

                    src_data = src.read(block_size)
                    tgt_data = tgt.read(block_size)

                    if src_data != tgt_data:
                        return False, f"Mismatch at block {block_num}"

                    bytes_verified += len(src_data)
                    block_num += 1

                    if context:
                        context.update_progress(
                            message=f"Verified {bytes_verified:,} bytes",
                            bytes_processed=bytes_verified,
                        )

                    if len(src_data) < block_size:
                        break

            return True, "Verification passed"

        except PermissionError:
            return False, "Permission denied during verification"
        except Exception as e:
            return False, str(e)

    # ==================== Image Operations ====================

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
        """Create a disk/partition image."""
        if mode == CloneMode.INTELLIGENT and context:
            context.add_warning(
                "Intelligent backup is not supported on Windows; using sector-by-sector capture."
            )
        source_info = self.get_disk_info(source_path) or self.get_partition_info(source_path)
        if not source_info:
            return False, f"Source not found: {source_path}", None

        source_size = source_info.size_bytes

        # Windows doesn't have native compression tools like Linux
        # We'll use Python's built-in compression
        compress_func = None
        compress_kwargs: dict[str, Any] = {}
        image_suffix = ""
        compression_level_value: int | None = None

        if compression_level:
            compression_level_value = (
                1
                if compression_level == CompressionLevel.FAST
                else 9
                if compression_level == CompressionLevel.MAXIMUM
                else 6
            )

        if compression == "gzip":
            import gzip
            compress_func = gzip.open
            image_suffix = ".gz"
        elif compression in ("zstd", "lz4"):
            # Fall back to gzip if zstd/lz4 not available
            try:
                import gzip
                compress_func = gzip.open
                image_suffix = ".gz"
                if context:
                    context.add_warning(f"{compression} not available, using gzip")
            except ImportError:
                compression = None

        if compress_func and compression_level_value is not None:
            compress_kwargs["compresslevel"] = compression_level_value

        final_path = Path(str(image_path) + image_suffix) if image_suffix else image_path

        if context:
            context.update_progress(
                message=f"Creating image of {source_path}",
                bytes_total=source_size,
            )

        if dry_run:
            return True, f"Would create image at {final_path}", None

        final_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            start_time = datetime.now()
            hasher = hashlib.sha256() if verify else None
            bytes_processed = 0
            block_size = 64 * 1024 * 1024

            with open(source_path, "rb") as src:
                if compress_func:
                    with compress_func(final_path, "wb", **compress_kwargs) as out:
                        while True:
                            if context:
                                context.check_cancelled()

                            data = src.read(block_size)
                            if not data:
                                break

                            if hasher:
                                hasher.update(data)
                            out.write(data)
                            bytes_processed += len(data)

                            if context:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                rate = bytes_processed / elapsed if elapsed > 0 else 0
                                context.update_progress(
                                    current=int((bytes_processed / source_size) * 100),
                                    bytes_processed=bytes_processed,
                                    rate_bytes_per_sec=rate,
                                )
                else:
                    with open(final_path, "wb") as out:
                        while True:
                            if context:
                                context.check_cancelled()

                            data = src.read(block_size)
                            if not data:
                                break

                            if hasher:
                                hasher.update(data)
                            out.write(data)
                            bytes_processed += len(data)

                            if context:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                rate = bytes_processed / elapsed if elapsed > 0 else 0
                                context.update_progress(
                                    current=int((bytes_processed / source_size) * 100),
                                    bytes_processed=bytes_processed,
                                    rate_bytes_per_sec=rate,
                                )

            metadata = {
                "clone_mode": mode.value,
                "schedule": schedule,
                "compression_level": compression_level.value if compression_level else None,
            }
            if extra_metadata:
                metadata.update(extra_metadata)

            backup_type_value = backup_type or BackupType.DISK_IMAGE
            metadata.setdefault("backup_type", backup_type_value.value)

            # Create image info
            image_info = ImageInfo(
                path=str(final_path),
                source_device=source_path,
                source_size_bytes=source_size,
                image_size_bytes=final_path.stat().st_size,
                backup_type=backup_type_value,
                compression=compression if compress_func else None,
                created_at=start_time,
                checksum=hasher.hexdigest() if hasher else None,
                checksum_algorithm="sha256",
                metadata=metadata,
            )

            # Write metadata
            meta_path = Path(str(final_path) + ".meta.json")
            with open(meta_path, "w") as f:
                json.dump(image_info.to_dict(), f, indent=2)

            return True, f"Image created at {final_path}", image_info

        except PermissionError:
            return False, "Permission denied. Run as Administrator.", None
        except Exception as e:
            return False, f"Failed to create image: {e}", None

    def _normalize_mountpoint(self, mountpoint: str | None) -> str | None:
        if not mountpoint:
            return None
        if mountpoint.endswith("\\"):
            return mountpoint.rstrip("\\")
        return mountpoint.rstrip("/")

    def _safe_filename(self, value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
        return sanitized or "partition"

    def _select_system_backup_partitions(
        self,
        disk: Disk,
        profile: SystemBackupConfig,
    ) -> list[Partition]:
        required_mounts = {self._normalize_mountpoint(mp) for mp in profile.required_mountpoints}
        required_mounts.discard(None)
        selected: list[Partition] = []

        for partition in disk.partitions:
            normalized_mount = self._normalize_mountpoint(partition.mountpoint)
            is_required = False

            if normalized_mount and normalized_mount in required_mounts:
                is_required = True
            if partition.is_boot or partition.is_system or PartitionFlag.ESP in partition.flags:
                is_required = True
            if PartitionFlag.MSFTRES in partition.flags and profile.include_reserved_partitions:
                is_required = True

            if partition.filesystem == FileSystem.SWAP and not profile.include_swap_partitions and not is_required:
                continue
            if PartitionFlag.DIAG in partition.flags and not profile.include_recovery_partitions and not is_required:
                continue
            if PartitionFlag.HIDDEN in partition.flags and not profile.include_hidden_partitions and not is_required:
                continue

            if is_required:
                selected.append(partition)

        if not selected:
            selected = disk.partitions.copy()

        return selected

    def _build_system_boot_metadata(
        self,
        disk: Disk,
        selected_partitions: list[Partition],
        profile: SystemBackupConfig,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "disk": {
                "device_path": disk.device_path,
                "model": disk.model,
                "serial": disk.serial,
                "size_bytes": disk.size_bytes,
                "sector_size": disk.sector_size,
                "partition_style": disk.partition_style.name,
            },
            "selected_partitions": [partition.device_path for partition in selected_partitions],
            "boot_partitions": [
                partition.device_path
                for partition in disk.partitions
                if partition.is_boot or partition.is_system or PartitionFlag.ESP in partition.flags
            ],
        }

        if profile.capture_partition_table:
            metadata["partition_table"] = [partition.to_dict() for partition in disk.partitions]

        return metadata

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
        """Create a system backup bundle."""
        profile = profile or SystemBackupConfig()
        inventory = self.get_disk_inventory()
        system_disks = [disk for disk in inventory.disks if disk.is_system_disk]

        if not system_disks:
            return False, "No system disk detected for backup", None

        system_disk = system_disks[0]
        if len(system_disks) > 1 and context:
            context.add_warning(
                f"Multiple system disks detected; using {system_disk.device_path}"
            )

        selected_partitions = self._select_system_backup_partitions(system_disk, profile)
        if not selected_partitions:
            return False, "No system partitions found for backup", None

        if context:
            context.update_progress(message="Preparing system backup", stage="system_backup")

        if dry_run:
            return True, f"Would create system backup at {output_path}", None

        output_path.mkdir(parents=True, exist_ok=True)
        backup_id = str(uuid.uuid4())
        created_at = datetime.now()
        images: list[ImageInfo] = []

        for index, partition in enumerate(selected_partitions, start=1):
            if context:
                context.update_progress(
                    message=f"Backing up {partition.device_path} ({index}/{len(selected_partitions)})",
                    stage="system_backup",
                )

            image_basename = self._safe_filename(partition.device_path)
            image_path = output_path / f"{image_basename}.img"
            success, message, image_info = self.create_image(
                partition.device_path,
                image_path,
                context,
                compression=compression,
                compression_level=compression_level,
                verify=verify,
                mode=mode,
                backup_type=BackupType.SYSTEM_PARTITION,
                extra_metadata={
                    "system_backup_id": backup_id,
                    "system_disk": system_disk.device_path,
                    "partition_flags": [flag.name for flag in partition.flags],
                    "partition_mountpoint": partition.mountpoint,
                    "partition_filesystem": partition.filesystem.value,
                },
            )
            if not success or image_info is None:
                return False, message, None
            images.append(image_info)

        boot_metadata = (
            self._build_system_boot_metadata(system_disk, selected_partitions, profile)
            if profile.capture_boot_metadata
            else {}
        )

        manifest = {
            "backup_type": BackupType.SYSTEM.value,
            "backup_id": backup_id,
            "created_at": created_at.isoformat(),
            "source_disk": system_disk.device_path,
            "source_disk_model": system_disk.model,
            "source_disk_size_bytes": system_disk.size_bytes,
            "partition_style": system_disk.partition_style.name,
            "profile": profile.model_dump(mode="json"),
            "boot_metadata": boot_metadata,
            "partitions": [
                {
                    "device_path": partition.device_path,
                    "mountpoint": partition.mountpoint,
                    "filesystem": partition.filesystem.value,
                    "flags": [flag.name for flag in partition.flags],
                    "image_path": os.path.relpath(image.path, output_path),
                }
                for partition, image in zip(selected_partitions, images)
            ],
        }

        manifest_path = output_path / "system_backup.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        backup_info = SystemBackupInfo(
            path=str(output_path),
            source_disk=system_disk.device_path,
            image_count=len(images),
            images=images,
            created_at=created_at,
            metadata={
                "backup_id": backup_id,
                "manifest_path": str(manifest_path),
                "backup_type": BackupType.SYSTEM.value,
            },
        )

        return True, f"System backup created at {output_path}", backup_info

    def restore_image(
        self,
        image_path: Path,
        target_path: str,
        context: JobContext | None = None,
        verify: bool = True,
        schedule: str | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Restore an image to a disk/partition."""
        if not image_path.exists():
            return False, f"Image not found: {image_path}"

        image_info = self.get_image_info(image_path)
        if not image_info:
            return False, "Could not read image metadata"

        target_info = self.get_disk_info(target_path) or self.get_partition_info(target_path)
        if not target_info:
            return False, f"Target not found: {target_path}"

        if isinstance(target_info, Disk) and target_info.is_system_disk:
            return False, "Cannot write to system disk"

        target_size = target_info.size_bytes
        if target_size < image_info.source_size_bytes:
            return False, (
                f"Target ({target_size} bytes) is smaller than "
                f"source ({image_info.source_size_bytes} bytes)"
            )

        if context:
            context.update_progress(
                message=f"Restoring image to {target_path}",
                bytes_total=image_info.source_size_bytes,
            )

        if dry_run:
            return True, f"Would restore {image_path} to {target_path}"

        # Determine decompression
        decompress_func = None
        if str(image_path).endswith(".gz"):
            import gzip
            decompress_func = gzip.open

        try:
            start_time = datetime.now()
            hasher = hashlib.sha256() if verify else None
            bytes_processed = 0
            block_size = 64 * 1024 * 1024

            with open(target_path, "r+b") as tgt:
                if decompress_func:
                    with decompress_func(image_path, "rb") as src:
                        while True:
                            if context:
                                context.check_cancelled()

                            data = src.read(block_size)
                            if not data:
                                break

                            if hasher:
                                hasher.update(data)
                            tgt.write(data)
                            bytes_processed += len(data)

                            if context:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                rate = bytes_processed / elapsed if elapsed > 0 else 0
                                context.update_progress(
                                    current=int(
                                        (bytes_processed / image_info.source_size_bytes) * 100
                                    ),
                                    bytes_processed=bytes_processed,
                                    rate_bytes_per_sec=rate,
                                )
                else:
                    with open(image_path, "rb") as src:
                        while True:
                            if context:
                                context.check_cancelled()

                            data = src.read(block_size)
                            if not data:
                                break

                            if hasher:
                                hasher.update(data)
                            tgt.write(data)
                            bytes_processed += len(data)

                            if context:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                rate = bytes_processed / elapsed if elapsed > 0 else 0
                                context.update_progress(
                                    current=int(
                                        (bytes_processed / image_info.source_size_bytes) * 100
                                    ),
                                    bytes_processed=bytes_processed,
                                    rate_bytes_per_sec=rate,
                                )

                tgt.flush()
                os.fsync(tgt.fileno())

            # Verify checksum
            if verify and hasher and image_info.checksum:
                if hasher.hexdigest() != image_info.checksum:
                    return False, "Checksum verification failed"

            return True, f"Image restored to {target_path}"

        except PermissionError:
            return False, "Permission denied. Run as Administrator."
        except Exception as e:
            return False, f"Failed to restore image: {e}"

    def get_image_info(self, image_path: Path) -> ImageInfo | None:
        """Get information about an image file."""
        meta_path = Path(str(image_path) + ".meta.json")
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    data = json.load(f)
                metadata = data.get("metadata", {})
                backup_type = BackupType.from_string(
                    data.get("backup_type") or metadata.get("backup_type")
                )
                return ImageInfo(
                    path=data.get("path", str(image_path)),
                    source_device=data.get("source_device", ""),
                    source_size_bytes=data.get("source_size_bytes", 0),
                    image_size_bytes=data.get("image_size_bytes", image_path.stat().st_size),
                    backup_type=backup_type,
                    compression=data.get("compression"),
                    created_at=(
                        datetime.fromisoformat(data["created_at"])
                        if data.get("created_at")
                        else None
                    ),
                    checksum=data.get("checksum"),
                    checksum_algorithm=data.get("checksum_algorithm", "sha256"),
                    metadata=metadata,
                )
            except Exception:
                pass

        if not image_path.exists():
            return None

        compression = None
        if str(image_path).endswith(".gz"):
            compression = "gzip"

        return ImageInfo(
            path=str(image_path),
            source_device="unknown",
            source_size_bytes=0,
            image_size_bytes=image_path.stat().st_size,
            backup_type=BackupType.DISK_IMAGE,
            compression=compression,
        )

    # ==================== Rescue Media Operations ====================

    def create_rescue_media(
        self,
        output_path: Path,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Create bootable rescue media for Windows (WinRE package)."""
        artifacts: dict[str, Any] = {}

        if context:
            context.update_progress(message="Creating Windows rescue package")

        if dry_run:
            return True, f"Would create rescue package at {output_path}", artifacts

        try:
            output_path.mkdir(parents=True, exist_ok=True)

            # Create batch scripts for recovery operations
            scripts_dir = output_path / "scripts"
            scripts_dir.mkdir(exist_ok=True)

            # Main rescue script
            rescue_bat = scripts_dir / "diskforge-rescue.bat"
            rescue_bat.write_text(self._generate_rescue_batch())
            artifacts["rescue_script"] = str(rescue_bat)

            # Disk info script
            diskinfo_bat = scripts_dir / "disk-info.bat"
            diskinfo_bat.write_text(self._generate_diskinfo_batch())
            artifacts["diskinfo_script"] = str(diskinfo_bat)

            # Clone script
            clone_bat = scripts_dir / "clone-disk.bat"
            clone_bat.write_text(self._generate_clone_batch())
            artifacts["clone_script"] = str(clone_bat)

            # PowerShell helper script
            helper_ps1 = scripts_dir / "diskforge-helper.ps1"
            helper_ps1.write_text(self._generate_helper_powershell())
            artifacts["powershell_helper"] = str(helper_ps1)

            # Instructions
            readme = output_path / "README.txt"
            readme.write_text(self._generate_windows_rescue_readme())
            artifacts["readme"] = str(readme)

            # WinRE integration instructions
            winre_txt = output_path / "WINRE_INTEGRATION.txt"
            winre_txt.write_text(self._generate_winre_instructions())
            artifacts["winre_instructions"] = str(winre_txt)

            return True, f"Rescue package created at {output_path}", artifacts

        except Exception as e:
            return False, f"Failed to create rescue package: {e}", artifacts

    # ==================== Boot & Recovery Operations ====================

    def integrate_recovery_environment(
        self,
        options: WinREIntegrationOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Integrate DiskForge into Windows Recovery Environment."""
        artifacts: dict[str, Any] = {}

        source_path = options.source_path
        mount_path = options.mount_path
        target_subdir = options.target_subdir

        if dry_run:
            return (
                True,
                f"Would integrate {source_path} into WinRE at {mount_path} (subdir: {target_subdir})",
                artifacts,
            )

        if not source_path.exists():
            return False, f"Source path not found: {source_path}", artifacts

        if context:
            context.update_progress(message="Mounting WinRE image")

        mount_path.mkdir(parents=True, exist_ok=True)
        disable_result = self.run_command(["reagentc", "/disable"], check=False)
        if not disable_result.success:
            return False, f"reagentc /disable failed: {disable_result.stderr}", artifacts

        mount_result = self.run_command(["reagentc", "/mountre", "/path", str(mount_path)], check=False)
        if not mount_result.success:
            return False, f"reagentc /mountre failed: {mount_result.stderr}", artifacts

        target_root = mount_path / "Windows" / "System32" / target_subdir
        if target_root.exists():
            shutil.rmtree(target_root, ignore_errors=True)

        shutil.copytree(source_path, target_root)
        artifacts["target_path"] = str(target_root)

        if context:
            context.update_progress(message="Committing WinRE changes")

        unmount_result = self.run_command(
            ["reagentc", "/unmountre", "/path", str(mount_path), "/commit"],
            check=False,
        )
        if not unmount_result.success:
            return False, f"reagentc /unmountre failed: {unmount_result.stderr}", artifacts

        enable_result = self.run_command(["reagentc", "/enable"], check=False)
        if not enable_result.success:
            return False, f"reagentc /enable failed: {enable_result.stderr}", artifacts

        return True, f"Integrated DiskForge into WinRE at {target_root}", artifacts

    def repair_boot(
        self,
        options: BootRepairOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Run Windows boot repair commands."""
        artifacts: dict[str, Any] = {}
        commands: list[list[str]] = []
        if options.fix_mbr:
            commands.append(["bootrec.exe", "/fixmbr"])
        if options.fix_boot:
            commands.append(["bootrec.exe", "/fixboot"])
        if options.rebuild_bcd:
            commands.append(["bootrec.exe", "/scanos"])
            commands.append(["bootrec.exe", "/rebuildbcd"])
            commands.append(["bcdboot.exe", str(options.system_root), "/f", "ALL"])

        if dry_run:
            plan = "\n".join(" ".join(cmd) for cmd in commands) or "No commands selected"
            return True, f"Would run:\n{plan}", artifacts

        results = []
        success = True
        for cmd in commands:
            if context:
                context.update_progress(message=f"Running {' '.join(cmd)}")
            result = self.run_command(cmd, check=False)
            artifacts[" ".join(cmd)] = {"stdout": result.stdout, "stderr": result.stderr}
            if not result.success:
                success = False
            results.append(result)

        message = "Boot repair completed" if success else "Boot repair completed with errors"
        return success, message, artifacts

    def rebuild_mbr(
        self,
        options: RebuildMBROptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Rebuild the Master Boot Record (MBR)."""
        commands = [["bootrec.exe", "/fixmbr"]]
        if options.fix_boot:
            commands.append(["bootrec.exe", "/fixboot"])

        if dry_run:
            return True, "Would run: " + " && ".join(" ".join(cmd) for cmd in commands)

        for cmd in commands:
            if context:
                context.update_progress(message=f"Running {' '.join(cmd)}")
            result = self.run_command(cmd, check=False)
            if not result.success:
                return False, f"Command failed: {' '.join(cmd)} - {result.stderr}"

        return True, "MBR rebuilt successfully"

    def manage_uefi_boot_options(
        self,
        options: UEFIBootOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """List or update UEFI boot entries."""
        artifacts: dict[str, Any] = {}

        action = options.action.lower()
        if action == "list":
            if dry_run:
                return True, "Would run: bcdedit /enum firmware", artifacts
            result = self.run_command(["bcdedit", "/enum", "firmware"], check=False)
            artifacts["output"] = result.stdout or result.stderr
            if result.success:
                return True, "UEFI boot entries listed.", artifacts
            return False, f"bcdedit failed: {result.stderr}", artifacts

        if action == "set-default":
            if not options.identifier:
                return False, "Missing identifier for set-default action.", artifacts
            if dry_run:
                return True, f"Would run: bcdedit /default {options.identifier}", artifacts
            result = self.run_command(["bcdedit", "/default", options.identifier], check=False)
            artifacts["output"] = result.stdout or result.stderr
            if result.success:
                return True, f"Set UEFI default to {options.identifier}", artifacts
            return False, f"bcdedit failed: {result.stderr}", artifacts

        return False, f"Unsupported UEFI boot option action: {options.action}", artifacts

    def create_windows_to_go(
        self,
        options: WindowsToGoOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Create a Windows To Go workspace using DISM + BCDBoot."""
        artifacts: dict[str, Any] = {}
        image_path = options.image_path
        target_drive = options.target_drive.rstrip("\\")
        apply_dir = f"{target_drive}\\"

        if dry_run:
            plan = (
                f"dism.exe /Apply-Image /ImageFile:{image_path} /Index:{options.apply_index} /ApplyDir:{apply_dir}\n"
                f"bcdboot.exe {apply_dir}Windows /s {target_drive} /f ALL"
            )
            if options.label:
                plan += f"\nSet-Volume -DriveLetter {target_drive.replace(':', '')} -NewFileSystemLabel '{options.label}'"
            return True, f"Would run:\n{plan}", artifacts

        if not image_path.exists():
            return False, f"Image not found: {image_path}", artifacts

        if context:
            context.update_progress(message="Applying Windows image")

        dism_cmd = [
            "dism.exe",
            "/Apply-Image",
            f"/ImageFile:{image_path}",
            f"/Index:{options.apply_index}",
            f"/ApplyDir:{apply_dir}",
        ]
        dism_result = self.run_command(dism_cmd, timeout=3600, check=False)
        artifacts["dism"] = {"stdout": dism_result.stdout, "stderr": dism_result.stderr}
        if not dism_result.success:
            return False, f"DISM failed: {dism_result.stderr}", artifacts

        if context:
            context.update_progress(message="Configuring boot files")

        bcd_cmd = [
            "bcdboot.exe",
            f"{apply_dir}Windows",
            "/s",
            target_drive,
            "/f",
            "ALL",
        ]
        bcd_result = self.run_command(bcd_cmd, check=False)
        artifacts["bcdboot"] = {"stdout": bcd_result.stdout, "stderr": bcd_result.stderr}
        if not bcd_result.success:
            return False, f"BCDBoot failed: {bcd_result.stderr}", artifacts

        if options.label:
            drive_letter = target_drive.replace(":", "")
            label_script = f"Set-Volume -DriveLetter {drive_letter} -NewFileSystemLabel '{options.label}'"
            label_result = self._run_powershell(label_script)
            artifacts["label"] = {"stdout": label_result.stdout, "stderr": label_result.stderr}
            if not label_result.success:
                return False, f"Failed to set label: {label_result.stderr}", artifacts

        return True, "Windows To Go workspace created.", artifacts

    def reset_windows_password(
        self,
        options: WindowsPasswordResetOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Reset a Windows local account password."""
        if dry_run:
            return True, f"Would reset password for {options.username}"

        if context:
            context.update_progress(message=f"Resetting password for {options.username}")

        result = self.run_command(
            ["net", "user", options.username, options.new_password],
            check=False,
        )
        if result.success:
            return True, f"Password reset for {options.username}"
        return False, f"Password reset failed: {result.stderr}"

    # ==================== BitLocker Operations ====================

    def get_bitlocker_status(self, mount_point: str) -> BitLockerStatus:
        script = (
            "Get-BitLockerVolume -MountPoint "
            f"'{mount_point}' | "
            "Select-Object MountPoint, VolumeStatus, ProtectionStatus, EncryptionPercentage, "
            "LockStatus, AutoUnlockEnabled, "
            "@{Name='KeyProtectorTypes';Expression={$_.KeyProtector | ForEach-Object {$_.KeyProtectorType}}} | "
            "ConvertTo-Json -Depth 3"
        )
        result = self._run_powershell(script)
        if not result.success:
            return BitLockerStatus(
                mount_point=mount_point,
                volume_status="Unknown",
                protection_status="Unknown",
                encryption_percentage=None,
                lock_status=None,
                auto_unlock_enabled=None,
                key_protectors=[],
                success=False,
                message=result.stderr or result.stdout or "Failed to query BitLocker status.",
            )

        records = parse_powershell_json(result.stdout)
        if not records:
            return BitLockerStatus(
                mount_point=mount_point,
                volume_status="Unknown",
                protection_status="Unknown",
                encryption_percentage=None,
                lock_status=None,
                auto_unlock_enabled=None,
                key_protectors=[],
                success=False,
                message="No BitLocker status returned.",
            )

        record = records[0]
        raw_encryption = record.get("EncryptionPercentage")
        try:
            encryption_percentage = float(raw_encryption) if raw_encryption is not None else None
        except (TypeError, ValueError):
            encryption_percentage = None

        key_types = record.get("KeyProtectorTypes") or []
        if isinstance(key_types, str):
            key_types = [key_types]

        return BitLockerStatus(
            mount_point=record.get("MountPoint") or mount_point,
            volume_status=str(record.get("VolumeStatus") or "Unknown"),
            protection_status=str(record.get("ProtectionStatus") or "Unknown"),
            encryption_percentage=encryption_percentage,
            lock_status=record.get("LockStatus"),
            auto_unlock_enabled=record.get("AutoUnlockEnabled"),
            key_protectors=[str(item) for item in key_types],
        )

    def enable_bitlocker(self, mount_point: str) -> tuple[bool, str]:
        script = (
            f"Enable-BitLocker -MountPoint '{mount_point}' "
            "-UsedSpaceOnly -SkipHardwareTest -RecoveryPasswordProtector -ErrorAction Stop"
        )
        result = self._run_powershell(script, timeout=600)
        if result.success:
            return True, f"BitLocker enable initiated for {mount_point}."
        return False, f"BitLocker enable failed: {result.stderr or result.stdout}"

    def disable_bitlocker(self, mount_point: str) -> tuple[bool, str]:
        script = f"Disable-BitLocker -MountPoint '{mount_point}' -ErrorAction Stop"
        result = self._run_powershell(script, timeout=600)
        if result.success:
            return True, f"BitLocker disable initiated for {mount_point}."
        return False, f"BitLocker disable failed: {result.stderr or result.stdout}"

    def _generate_rescue_batch(self) -> str:
        """Generate main rescue batch script."""
        return """@echo off
:: DiskForge Rescue Environment for Windows
:: Run this from Windows Recovery Environment (WinRE) or a Windows PE disk

title DiskForge Rescue Environment

echo ========================================
echo   DiskForge Rescue Environment
echo ========================================
echo.

:MENU
echo.
echo Options:
echo   1. Show disk information
echo   2. Show partition details
echo   3. List volumes
echo   4. Run PowerShell helper
echo   5. Exit
echo.
set /p choice="Select option (1-5): "

if "%choice%"=="1" goto DISKINFO
if "%choice%"=="2" goto PARTINFO
if "%choice%"=="3" goto VOLINFO
if "%choice%"=="4" goto PSHELPER
if "%choice%"=="5" goto END
goto MENU

:DISKINFO
echo.
echo === Disk Information ===
wmic diskdrive get Index,Model,Size,MediaType
echo.
pause
goto MENU

:PARTINFO
echo.
set /p disknum="Enter disk number: "
echo.
echo === Partitions on Disk %disknum% ===
echo list disk > %TEMP%\\dp_part.txt
echo select disk %disknum% >> %TEMP%\\dp_part.txt
echo list partition >> %TEMP%\\dp_part.txt
diskpart /s %TEMP%\\dp_part.txt
del %TEMP%\\dp_part.txt
echo.
pause
goto MENU

:VOLINFO
echo.
echo === Volumes ===
echo list volume > %TEMP%\\dp_vol.txt
diskpart /s %TEMP%\\dp_vol.txt
del %TEMP%\\dp_vol.txt
echo.
pause
goto MENU

:PSHELPER
echo.
echo Starting PowerShell helper...
powershell -ExecutionPolicy Bypass -File "%~dp0diskforge-helper.ps1"
goto MENU

:END
echo.
echo Exiting DiskForge Rescue Environment
exit /b 0
"""

    def _generate_diskinfo_batch(self) -> str:
        """Generate disk info batch script."""
        return """@echo off
:: DiskForge Disk Information Script

echo ========================================
echo   Disk Information Report
echo ========================================
echo.

echo === Physical Disks ===
wmic diskdrive get Index,Model,Size,MediaType,InterfaceType
echo.

echo === Partitions ===
wmic partition get DiskIndex,Index,Size,Type,Bootable
echo.

echo === Logical Disks ===
wmic logicaldisk get DeviceID,FileSystem,Size,FreeSpace,VolumeName
echo.

pause
"""

    def _generate_clone_batch(self) -> str:
        """Generate clone batch script."""
        return """@echo off
:: DiskForge Disk Clone Script
:: WARNING: This script performs destructive operations!

setlocal enabledelayedexpansion

echo ========================================
echo   DiskForge Disk Clone Utility
echo ========================================
echo.
echo WARNING: This operation will DESTROY all data on the target disk!
echo.

set /p source="Enter source disk number: "
set /p target="Enter target disk number: "

echo.
echo You are about to clone:
echo   Source: Disk %source%
echo   Target: Disk %target%
echo.
echo This will ERASE ALL DATA on Disk %target%!
echo.
set /p confirm="Type 'CONFIRM' to proceed: "

if not "%confirm%"=="CONFIRM" (
    echo Operation cancelled.
    pause
    exit /b 1
)

echo.
echo Starting clone operation...
echo This may take a long time depending on disk size.
echo.

:: Use PowerShell for the actual copy
powershell -ExecutionPolicy Bypass -Command ^
    "$source = '\\\\.\\PhysicalDrive%source%'; ^
     $target = '\\\\.\\PhysicalDrive%target%'; ^
     $bufferSize = 64MB; ^
     $sourceStream = [System.IO.File]::OpenRead($source); ^
     $targetStream = [System.IO.File]::OpenWrite($target); ^
     $buffer = New-Object byte[] $bufferSize; ^
     $totalRead = 0; ^
     Write-Host 'Copying...'; ^
     while (($read = $sourceStream.Read($buffer, 0, $bufferSize)) -gt 0) { ^
         $targetStream.Write($buffer, 0, $read); ^
         $totalRead += $read; ^
         Write-Host \"`rCopied: $([math]::Round($totalRead/1GB, 2)) GB\" -NoNewline; ^
     } ^
     $targetStream.Flush(); ^
     $sourceStream.Close(); ^
     $targetStream.Close(); ^
     Write-Host ''; ^
     Write-Host 'Clone complete!'"

echo.
pause
"""

    def _generate_helper_powershell(self) -> str:
        """Generate PowerShell helper script."""
        return """# DiskForge PowerShell Helper
# For use in Windows Recovery Environment

function Show-Menu {
    Clear-Host
    Write-Host "========================================"
    Write-Host "  DiskForge PowerShell Helper"
    Write-Host "========================================"
    Write-Host ""
    Write-Host "1. List all disks"
    Write-Host "2. List all partitions"
    Write-Host "3. List all volumes"
    Write-Host "4. Show disk details"
    Write-Host "5. Export disk report"
    Write-Host "6. Exit"
    Write-Host ""
}

function Get-DiskList {
    Write-Host "`n=== Disks ===" -ForegroundColor Cyan
    Get-WmiObject Win32_DiskDrive | Select-Object Index, Model, @{N='Size(GB)';E={[math]::Round($_.Size/1GB,2)}}, MediaType | Format-Table -AutoSize
}

function Get-PartitionList {
    Write-Host "`n=== Partitions ===" -ForegroundColor Cyan
    Get-WmiObject Win32_DiskPartition | Select-Object DiskIndex, Index, @{N='Size(GB)';E={[math]::Round($_.Size/1GB,2)}}, Type | Format-Table -AutoSize
}

function Get-VolumeList {
    Write-Host "`n=== Volumes ===" -ForegroundColor Cyan
    Get-WmiObject Win32_LogicalDisk | Select-Object DeviceID, FileSystem, @{N='Size(GB)';E={[math]::Round($_.Size/1GB,2)}}, @{N='Free(GB)';E={[math]::Round($_.FreeSpace/1GB,2)}}, VolumeName | Format-Table -AutoSize
}

function Get-DiskDetails {
    $diskNum = Read-Host "Enter disk number"
    Write-Host "`n=== Disk $diskNum Details ===" -ForegroundColor Cyan
    Get-WmiObject Win32_DiskDrive | Where-Object {$_.Index -eq $diskNum} | Format-List *
}

function Export-DiskReport {
    $reportPath = Read-Host "Enter report file path (e.g., C:\\report.txt)"

    $report = @"
DiskForge Disk Report
Generated: $(Get-Date)
========================================

=== Physical Disks ===
$(Get-WmiObject Win32_DiskDrive | Format-List Index, Model, Size, MediaType, InterfaceType | Out-String)

=== Partitions ===
$(Get-WmiObject Win32_DiskPartition | Format-List DiskIndex, Index, Size, Type, Bootable | Out-String)

=== Volumes ===
$(Get-WmiObject Win32_LogicalDisk | Format-List DeviceID, FileSystem, Size, FreeSpace, VolumeName | Out-String)
"@

    $report | Out-File -FilePath $reportPath -Encoding UTF8
    Write-Host "Report saved to: $reportPath" -ForegroundColor Green
}

# Main loop
do {
    Show-Menu
    $choice = Read-Host "Select option (1-6)"

    switch ($choice) {
        "1" { Get-DiskList; Read-Host "Press Enter to continue" }
        "2" { Get-PartitionList; Read-Host "Press Enter to continue" }
        "3" { Get-VolumeList; Read-Host "Press Enter to continue" }
        "4" { Get-DiskDetails; Read-Host "Press Enter to continue" }
        "5" { Export-DiskReport; Read-Host "Press Enter to continue" }
        "6" { break }
        default { Write-Host "Invalid option" -ForegroundColor Red }
    }
} while ($choice -ne "6")

Write-Host "Exiting DiskForge Helper"
"""

    def _generate_windows_rescue_readme(self) -> str:
        """Generate README for Windows rescue package."""
        return """DiskForge Rescue Package for Windows
====================================

This package provides disk management tools for Windows recovery scenarios.

USAGE
-----
1. Boot into Windows Recovery Environment (WinRE) or Windows PE
2. Access the command prompt
3. Navigate to this folder
4. Run: scripts\\diskforge-rescue.bat

INCLUDED SCRIPTS
----------------
- diskforge-rescue.bat   : Main interactive menu
- disk-info.bat          : Display disk information
- clone-disk.bat         : Clone disk utility
- diskforge-helper.ps1   : PowerShell helper with advanced features

REQUIREMENTS
------------
- Windows Recovery Environment (WinRE) or Windows PE
- Administrator privileges
- PowerShell (for advanced features)

COMMON OPERATIONS
-----------------
View disks:
  wmic diskdrive get Index,Model,Size

View partitions:
  wmic partition get DiskIndex,Index,Size,Type

Use diskpart:
  diskpart
  > list disk
  > select disk N
  > list partition

WARNING
-------
Disk operations are DESTRUCTIVE. Always verify source and target
before proceeding. Back up important data first.

For more information, visit: https://diskforge.dev/docs/rescue
"""

    def _generate_winre_instructions(self) -> str:
        """Generate WinRE integration instructions."""
        return """DiskForge WinRE Integration Instructions
========================================

To integrate DiskForge into Windows Recovery Environment:

METHOD 1: USB Drive (Recommended)
---------------------------------
1. Copy this entire folder to a USB drive
2. Boot into WinRE (hold Shift while clicking Restart)
3. Select Troubleshoot > Command Prompt
4. Navigate to your USB drive (usually D: or E:)
5. Run: scripts\\diskforge-rescue.bat

METHOD 2: Add to Recovery Image (Advanced)
------------------------------------------
WARNING: This modifies system recovery files.

1. Mount the recovery image:
   reagentc /disable
   mkdir C:\\WinRE
   reagentc /mountre /path C:\\WinRE

2. Copy DiskForge files:
   copy /Y scripts\\* C:\\WinRE\\Windows\\System32\\

3. Unmount and enable:
   reagentc /unmountre /path C:\\WinRE /commit
   reagentc /enable

4. Test by booting into recovery mode

METHOD 3: Windows PE (IT Professionals)
---------------------------------------
1. Create a Windows PE image using ADK
2. Mount the boot.wim file
3. Copy DiskForge scripts to System32
4. Unmount and create bootable media

ACCESSING WINRE
---------------
- From Windows: Settings > Recovery > Advanced Startup
- During boot: Hold Shift and click Restart
- From boot: Press F8 repeatedly during startup
- Using command: shutdown /r /o /f /t 0

TROUBLESHOOTING
---------------
If scripts don't run:
- Ensure PowerShell execution policy allows scripts
- Run: powershell -ExecutionPolicy Bypass -File script.ps1

If disk operations fail:
- Ensure you have administrator privileges
- Check that target disks are not in use
- Verify disk numbers carefully

For support: https://diskforge.dev/support
"""

    # ==================== Mount Operations ====================

    def mount_partition(
        self,
        partition_path: str,
        mount_point: str,
        options: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Mount a partition (assign drive letter on Windows)."""
        import re

        # Extract disk and partition numbers
        match = re.search(r"PhysicalDrive(\d+)Partition(\d+)", partition_path)
        if not match:
            return False, f"Cannot parse partition path: {partition_path}"

        disk_number = match.group(1)
        part_number = match.group(2)

        # Get drive letter from mount_point
        if len(mount_point) >= 1 and mount_point[0].isalpha():
            drive_letter = mount_point[0].upper()
        else:
            return False, f"Invalid drive letter: {mount_point}"

        script = f"""
        $partition = Get-Partition -DiskNumber {disk_number} -PartitionNumber {part_number}
        $partition | Add-PartitionAccessPath -AccessPath "{drive_letter}:\\"
        """

        result = self._run_powershell(script)
        if result.success:
            return True, f"Assigned {drive_letter}: to partition"
        return False, f"Failed to assign drive letter: {result.stderr}"

    def unmount_partition(
        self,
        partition_path: str,
        force: bool = False,
    ) -> tuple[bool, str]:
        """Unmount a partition (remove drive letter on Windows)."""
        partition = self.get_partition_info(partition_path)
        if not partition:
            return False, f"Partition not found: {partition_path}"

        if not partition.mountpoint:
            return True, "Partition has no drive letter"

        drive_letter = partition.mountpoint[0]

        script = f"""
        $volume = Get-Volume -DriveLetter {drive_letter}
        $partition = $volume | Get-Partition
        $partition | Remove-PartitionAccessPath -AccessPath "{drive_letter}:\\"
        """

        result = self._run_powershell(script)
        if result.success:
            return True, f"Removed drive letter {drive_letter}:"
        return False, f"Failed to remove drive letter: {result.stderr}"

    # ==================== SMART Operations ====================

    def get_smart_info(self, device_path: str) -> dict[str, Any] | None:
        """Get SMART information for a disk using WMI."""
        disk_number = self._extract_disk_number(device_path)
        if disk_number is None:
            return None

        script = f"""
        $disk = Get-WmiObject -Namespace root\\wmi -Class MSStorageDriver_FailurePredictStatus | Where-Object {{ $_.InstanceName -like "*YOURINDEX*" }}
        Get-WmiObject Win32_DiskDrive | Where-Object {{ $_.Index -eq {disk_number} }} | Select-Object Status, MediaType | ConvertTo-Json
        """

        result = self._run_powershell(script)
        if not result.success:
            return None

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    # ==================== Diagnostics Operations ====================

    def bad_sector_scan(
        self,
        options: BadSectorScanOptions,
        context: JobContext | None = None,
    ) -> BadSectorScanResult:
        return BadSectorScanResult(
            device_path=options.device_path,
            success=False,
            message="Bad sector scanning is not supported on Windows yet.",
            bad_sector_count=0,
            bad_sectors=[],
            duration_seconds=0.0,
            block_size=options.block_size,
            passes=options.passes,
            tool="",
        )

    def disk_health_check(
        self,
        device_path: str,
        context: JobContext | None = None,
    ) -> DiskHealthResult:
        smart_info = self.get_smart_info(device_path)
        if smart_info is None:
            return DiskHealthResult(
                device_path=device_path,
                healthy=False,
                status="UNKNOWN",
                smart_available=False,
                temperature_c=None,
                message="SMART data not available",
            )

        status = smart_info.get("Status", "Unknown")
        healthy = status.lower() == "ok"
        return DiskHealthResult(
            device_path=device_path,
            healthy=healthy,
            status=status,
            smart_available=True,
            temperature_c=None,
            message=f"SMART status: {status}",
            details=smart_info,
        )

    def disk_speed_test(
        self,
        options: DiskSpeedTestOptions,
        context: JobContext | None = None,
    ) -> DiskSpeedTestResult:
        return DiskSpeedTestResult(
            device_path=options.device_path,
            success=False,
            message="Disk speed tests are not supported on Windows yet.",
            sample_size_bytes=options.sample_size_bytes,
            block_size_bytes=options.block_size_bytes,
            duration_seconds=0.0,
            read_bytes_per_sec=0.0,
        )

    def surface_test(
        self,
        options: SurfaceTestOptions,
        context: JobContext | None = None,
    ) -> SurfaceTestResult:
        return SurfaceTestResult(
            device_path=options.device_path,
            success=False,
            message="Surface tests are not supported on Windows yet.",
            mode=options.mode,
            bad_sector_count=0,
            bad_sectors=[],
            duration_seconds=0.0,
            block_size=options.block_size,
            passes=options.passes,
            tool="",
        )

    # ==================== Utility Methods ====================

    def validate_device_path(self, path: str) -> tuple[bool, str]:
        """Validate a device path."""
        if not path.startswith("\\\\.\\"):
            return False, r"Device path must start with \\.\\"

        # Check if it's a valid PhysicalDrive path
        import re

        if not re.match(r"\\\\\.\\PhysicalDrive\d+", path):
            if not re.match(r"\\\\\.\\PhysicalDrive\d+Partition\d+", path):
                return False, "Invalid device path format"

        return True, "Valid device path"

    def is_device_mounted(self, device_path: str) -> bool:
        """Check if a device has mounted partitions."""
        if "Partition" in device_path:
            partition = self.get_partition_info(device_path)
            return partition.is_mounted if partition else False
        else:
            disk = self.get_disk_info(device_path)
            if disk:
                return any(p.is_mounted for p in disk.partitions)
        return False

    def get_mounted_devices(self) -> dict[str, str]:
        """Get mapping of mounted devices to mount points."""
        result: dict[str, str] = {}
        inventory = self.get_disk_inventory()

        for disk in inventory.disks:
            for partition in disk.partitions:
                if partition.is_mounted and partition.mountpoint:
                    result[partition.device_path] = partition.mountpoint

        return result

    def is_system_device(self, device_path: str) -> bool:
        """Check if a device is the system disk."""
        disk = self.get_disk_info(device_path)
        return disk.is_system_disk if disk else False

    # ==================== Storage Cleanup Operations ====================

    def _default_cleanup_roots(self) -> list[Path]:
        temp_paths = [Path(os.getenv("TEMP", "")), Path(os.getenv("TMP", ""))]
        user_profile = Path(os.getenv("USERPROFILE", ""))
        recycle = user_profile / "AppData/Local/Temp"
        candidates = temp_paths + [recycle]
        return [path for path in candidates if path and path.exists()]

    def _default_user_roots(self) -> list[Path]:
        user_profile = Path(os.getenv("USERPROFILE", ""))
        roots = [
            user_profile,
            user_profile / "Downloads",
            user_profile / "Desktop",
            user_profile / "Documents",
        ]
        return [root for root in roots if root.exists()]

    def scan_free_space(self, options: FreeSpaceOptions) -> FreeSpaceReport:
        roots = normalize_roots(options.roots, self._default_user_roots())
        return build_free_space_report(
            roots,
            options.exclude_patterns,
            junk_max_files=options.junk_max_files,
            large_min_size_bytes=options.large_min_size_bytes,
            large_max_results=options.large_max_results,
            duplicate_min_size_bytes=options.duplicate_min_size_bytes,
        )

    def scan_junk_files(self, options: JunkCleanupOptions) -> JunkScanResult:
        roots = normalize_roots(options.roots, self._default_cleanup_roots())
        return scan_junk_files(roots, options.exclude_patterns, max_files=options.max_files)

    def cleanup_junk_files(self, options: JunkCleanupOptions) -> JunkCleanupResult:
        roots = normalize_roots(options.roots, self._default_cleanup_roots())
        return cleanup_junk_files(roots, options.exclude_patterns, max_files=options.max_files)

    def scan_large_files(self, options: LargeFileScanOptions) -> LargeFileScanResult:
        roots = normalize_roots(options.roots, self._default_user_roots())
        return scan_large_files(
            roots,
            options.exclude_patterns,
            min_size_bytes=options.min_size_bytes,
            max_results=options.max_results,
        )

    def remove_large_files(self, options: FileRemovalOptions) -> FileRemovalResult:
        return remove_paths([Path(path) for path in options.paths])

    def scan_duplicate_files(self, options: DuplicateScanOptions) -> DuplicateScanResult:
        roots = normalize_roots(options.roots, self._default_user_roots())
        return scan_duplicate_files(
            roots,
            options.exclude_patterns,
            min_size_bytes=options.min_size_bytes,
        )

    def remove_duplicate_files(self, options: DuplicateRemovalOptions) -> FileRemovalResult:
        paths: list[str] = []
        for group in options.duplicate_groups:
            if not group.paths:
                continue
            keep = group.paths[0]
            for path in group.paths:
                if path != keep:
                    paths.append(path)
        return remove_paths([Path(path) for path in paths])

    def move_application(self, options: MoveApplicationOptions) -> MoveApplicationResult:
        return move_application(Path(options.source_path), Path(options.destination_root))
