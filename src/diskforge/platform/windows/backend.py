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
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from diskforge.core.logging import get_logger
from diskforge.core.models import (
    CloneMode,
    CompressionLevel,
    Disk,
    DiskInventory,
    FileSystem,
    ImageInfo,
    Partition,
    PartitionStyle,
)
from diskforge.platform.base import CommandResult, PlatformBackend
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
        FormatOptions,
        MergePartitionsOptions,
        MigrationOptions,
        PartitionCreateOptions,
        PartitionRecoveryOptions,
        ResizeMoveOptions,
        SplitPartitionOptions,
        WipeOptions,
    )

logger = get_logger(__name__)


class WindowsBackend(PlatformBackend):
    """Windows implementation of disk operations."""

    POWERSHELL = "powershell.exe"
    DISKPART = "diskpart.exe"

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

            # Create image info
            image_info = ImageInfo(
                path=str(final_path),
                source_device=source_path,
                source_size_bytes=source_size,
                image_size_bytes=final_path.stat().st_size,
                compression=compression if compress_func else None,
                created_at=start_time,
                checksum=hasher.hexdigest() if hasher else None,
                checksum_algorithm="sha256",
                metadata={
                    "clone_mode": mode.value,
                    "schedule": schedule,
                    "compression_level": compression_level.value if compression_level else None,
                },
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
                return ImageInfo(
                    path=data.get("path", str(image_path)),
                    source_device=data.get("source_device", ""),
                    source_size_bytes=data.get("source_size_bytes", 0),
                    image_size_bytes=data.get("image_size_bytes", image_path.stat().st_size),
                    compression=data.get("compression"),
                    created_at=(
                        datetime.fromisoformat(data["created_at"])
                        if data.get("created_at")
                        else None
                    ),
                    checksum=data.get("checksum"),
                    checksum_algorithm=data.get("checksum_algorithm", "sha256"),
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
