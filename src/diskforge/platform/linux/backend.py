"""
Linux Platform Backend Implementation.

Implements disk operations using standard Linux tools.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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
    DiskType,
    FileSystem,
    ImageInfo,
    Partition,
    PartitionStyle,
)
from diskforge.platform.base import CommandResult, PlatformBackend
from diskforge.platform.linux.parsers import (
    build_disk_from_lsblk,
    parse_blkid_output,
    parse_findmnt_json,
    parse_lsblk_json,
    parse_proc_mounts,
)

if TYPE_CHECKING:
    from diskforge.core.job import JobContext
    from diskforge.core.models import (
        AlignOptions,
        ConvertDiskOptions,
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
        ResizeMoveOptions,
        SplitPartitionOptions,
        WipeOptions,
    )

logger = get_logger(__name__)


class LinuxBackend(PlatformBackend):
    """Linux implementation of disk operations."""

    # Tool paths (can be overridden for testing)
    LSBLK = "lsblk"
    BLKID = "blkid"
    SFDISK = "sfdisk"
    PARTED = "parted"
    DD = "dd"
    FINDMNT = "findmnt"
    MOUNT = "mount"
    UMOUNT = "umount"
    SMARTCTL = "smartctl"

    # Filesystem tools
    MKFS_EXT4 = "mkfs.ext4"
    MKFS_EXT3 = "mkfs.ext3"
    MKFS_EXT2 = "mkfs.ext2"
    MKFS_XFS = "mkfs.xfs"
    MKFS_BTRFS = "mkfs.btrfs"
    MKFS_VFAT = "mkfs.vfat"
    MKFS_NTFS = "mkfs.ntfs"
    MKFS_EXFAT = "mkfs.exfat"
    MKSWAP = "mkswap"

    # Resize tools
    RESIZE2FS = "resize2fs"
    XFS_GROWFS = "xfs_growfs"
    BTRFS = "btrfs"

    # Compression tools
    GZIP = "gzip"
    LZ4 = "lz4"
    ZSTD = "zstd"

    # Conversion tools
    SGDISK = "sgdisk"

    # ISO creation
    XORRISO = "xorriso"
    MKSQUASHFS = "mksquashfs"

    # Wipe tools
    SHRED = "shred"

    @property
    def name(self) -> str:
        return "linux"

    @property
    def requires_admin(self) -> bool:
        return True

    def is_admin(self) -> bool:
        return os.geteuid() == 0

    def _check_tool(self, tool: str) -> bool:
        """Check if a tool is available."""
        return shutil.which(tool) is not None

    def _get_required_tools(self) -> list[str]:
        """Get list of required tools."""
        return [self.LSBLK, self.BLKID, self.DD]

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
            result = subprocess.run(
                command,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
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

    def get_disk_inventory(self) -> DiskInventory:
        """Get complete disk inventory using lsblk and blkid."""
        inventory = DiskInventory(platform="linux")

        # Get lsblk data
        lsblk_result = self.run_command(
            [
                self.LSBLK,
                "-J",  # JSON output
                "-b",  # Size in bytes
                "-o",
                "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINT,MODEL,SERIAL,VENDOR,"
                "TRAN,ROTA,RM,RO,PTTYPE,PARTTYPE,PHY-SEC,LOG-SEC,FSUSED,FSSIZE,WWN",
            ],
            check=False,
        )

        if not lsblk_result.success:
            inventory.errors.append(f"lsblk failed: {lsblk_result.stderr}")
            return inventory

        # Get blkid data for additional info
        blkid_result = self.run_command([self.BLKID], check=False)
        blkid_info = parse_blkid_output(blkid_result.stdout) if blkid_result.success else {}

        # Get mount info
        mounts = self._get_mounts()

        # Get system device
        system_devices = self._get_system_devices()

        # Parse lsblk output
        block_devices = parse_lsblk_json(lsblk_result.stdout)

        for block in block_devices:
            block_type = block.get("type", "")
            # Only process whole disks
            if block_type not in ("disk",):
                continue

            try:
                disk = build_disk_from_lsblk(block, blkid_info, mounts, system_devices)
                inventory.disks.append(disk)
            except Exception as e:
                logger.warning(
                    "Failed to parse disk",
                    device=block.get("name"),
                    error=str(e),
                )
                inventory.errors.append(f"Failed to parse {block.get('name')}: {e}")

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

    def _get_mounts(self) -> dict[str, str]:
        """Get current mounts."""
        result = self.run_command([self.FINDMNT, "-J"], check=False)
        if result.success:
            return parse_findmnt_json(result.stdout)
        return parse_proc_mounts()

    def _get_system_devices(self) -> set[str]:
        """Get devices that are part of the system (root filesystem)."""
        system_devices: set[str] = set()

        # Find device for root filesystem
        result = self.run_command(
            [self.FINDMNT, "-n", "-o", "SOURCE", "/"],
            check=False,
        )

        if result.success:
            source = result.stdout.strip()
            # Handle device mapper and LVM
            if source.startswith("/dev/mapper/"):
                system_devices.add(source)
            # Get parent device
            parent_match = re.match(r"(/dev/[a-z]+)", source)
            if parent_match:
                system_devices.add(parent_match.group(1))
            system_devices.add(source)

        return system_devices

    # ==================== Partition Operations ====================

    def create_partition(
        self,
        options: PartitionCreateOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Create a new partition using sfdisk."""
        if not self._check_tool(self.SFDISK):
            return False, "sfdisk not found"

        # Validate disk
        disk = self.get_disk_info(options.disk_path)
        if not disk:
            return False, f"Disk not found: {options.disk_path}"

        if disk.is_system_disk:
            return False, "Cannot modify system disk"

        # Build sfdisk input
        size_spec = ""
        if options.size_bytes:
            size_sectors = options.size_bytes // disk.sector_size
            size_spec = f"size={size_sectors}"

        start_spec = ""
        if options.start_sector:
            start_spec = f"start={options.start_sector}"

        type_spec = ""
        if options.partition_type:
            type_spec = f"type={options.partition_type}"
        elif options.filesystem == FileSystem.SWAP:
            type_spec = "type=0657fd6d-a4ab-43c4-84e5-0933c84b4f4f"

        parts = [p for p in [start_spec, size_spec, type_spec] if p]
        sfdisk_input = ", ".join(parts) + "\n"

        if context:
            context.update_progress(message=f"Creating partition on {options.disk_path}")

        if dry_run:
            return True, f"Would create partition with: {sfdisk_input}"

        # Run sfdisk to add partition
        result = self.run_command(
            [self.SFDISK, "--append", options.disk_path],
            timeout=60,
        )

        # Feed input via stdin
        try:
            proc = subprocess.run(
                [self.SFDISK, "--append", options.disk_path],
                input=sfdisk_input,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if proc.returncode != 0:
                return False, f"sfdisk failed: {proc.stderr}"

            # Re-read partition table
            self.run_command(["partprobe", options.disk_path], check=False)

            return True, "Partition created successfully"

        except Exception as e:
            return False, f"Failed to create partition: {e}"

    def delete_partition(
        self,
        partition_path: str,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Delete a partition using sfdisk."""
        if not self._check_tool(self.SFDISK):
            return False, "sfdisk not found"

        # Get partition info
        partition = self.get_partition_info(partition_path)
        if not partition:
            return False, f"Partition not found: {partition_path}"

        if partition.is_mounted:
            return False, f"Partition is mounted at {partition.mountpoint}. Unmount first."

        # Extract disk path and partition number
        match = re.match(r"(/dev/[a-z]+)(\d+)$", partition_path)
        if not match:
            # Try nvme pattern
            match = re.match(r"(/dev/nvme\d+n\d+)p(\d+)$", partition_path)

        if not match:
            return False, f"Cannot parse partition path: {partition_path}"

        disk_path = match.group(1)
        part_num = match.group(2)

        disk = self.get_disk_info(disk_path)
        if disk and disk.is_system_disk:
            return False, "Cannot modify system disk"

        if context:
            context.update_progress(message=f"Deleting partition {partition_path}")

        if dry_run:
            return True, f"Would delete partition {part_num} from {disk_path}"

        # Delete using sfdisk
        result = self.run_command(
            [self.SFDISK, "--delete", disk_path, part_num],
            timeout=60,
        )

        if not result.success:
            return False, f"sfdisk failed: {result.stderr}"

        # Re-read partition table
        self.run_command(["partprobe", disk_path], check=False)

        return True, f"Partition {partition_path} deleted"

    def format_partition(
        self,
        options: FormatOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Format a partition with specified filesystem."""
        # Get the right mkfs tool
        mkfs_map = {
            FileSystem.EXT4: (self.MKFS_EXT4, ["-F"]),
            FileSystem.EXT3: (self.MKFS_EXT3, ["-F"]),
            FileSystem.EXT2: (self.MKFS_EXT2, ["-F"]),
            FileSystem.XFS: (self.MKFS_XFS, ["-f"]),
            FileSystem.BTRFS: (self.MKFS_BTRFS, ["-f"]),
            FileSystem.FAT32: (self.MKFS_VFAT, ["-F", "32"]),
            FileSystem.NTFS: (self.MKFS_NTFS, ["-f", "-F"]),
            FileSystem.EXFAT: (self.MKFS_EXFAT, []),
            FileSystem.SWAP: (self.MKSWAP, ["-f"]),
        }

        if options.filesystem not in mkfs_map:
            return False, f"Unsupported filesystem: {options.filesystem.value}"

        mkfs_tool, default_args = mkfs_map[options.filesystem]

        if not self._check_tool(mkfs_tool):
            return False, f"{mkfs_tool} not found"

        # Validate partition
        partition = self.get_partition_info(options.partition_path)
        if not partition:
            return False, f"Partition not found: {options.partition_path}"

        if partition.is_mounted:
            return False, f"Partition is mounted at {partition.mountpoint}. Unmount first."

        # Build command
        cmd = [mkfs_tool]
        cmd.extend(default_args)

        if options.label:
            if options.filesystem in (FileSystem.EXT4, FileSystem.EXT3, FileSystem.EXT2):
                cmd.extend(["-L", options.label])
            elif options.filesystem == FileSystem.XFS:
                cmd.extend(["-L", options.label])
            elif options.filesystem == FileSystem.BTRFS:
                cmd.extend(["-L", options.label])
            elif options.filesystem in (FileSystem.FAT32, FileSystem.EXFAT):
                cmd.extend(["-n", options.label])
            elif options.filesystem == FileSystem.NTFS:
                cmd.extend(["-L", options.label])

        cmd.append(options.partition_path)

        if context:
            context.update_progress(
                message=f"Formatting {options.partition_path} as {options.filesystem.value}"
            )

        if dry_run:
            return True, f"Would run: {' '.join(cmd)}"

        result = self.run_command(cmd, timeout=600)

        if not result.success:
            return False, f"Format failed: {result.stderr}"

        return True, f"Formatted {options.partition_path} as {options.filesystem.value}"

    def resize_partition(
        self,
        partition_path: str,
        new_size_bytes: int,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Resize a partition and its filesystem."""
        partition = self.get_partition_info(partition_path)
        if not partition:
            return False, f"Partition not found: {partition_path}"

        if partition.is_mounted:
            # Some filesystems support online resize
            if partition.filesystem not in (FileSystem.EXT4, FileSystem.XFS, FileSystem.BTRFS):
                return False, "Partition must be unmounted for resize"

        # Resize filesystem first (shrink) or after (grow)
        growing = new_size_bytes > partition.size_bytes

        if context:
            context.update_progress(
                message=f"{'Growing' if growing else 'Shrinking'} {partition_path}"
            )

        if dry_run:
            return True, f"Would resize {partition_path} to {new_size_bytes} bytes"

        # Handle different filesystems
        if partition.filesystem in (FileSystem.EXT4, FileSystem.EXT3, FileSystem.EXT2):
            if not growing and partition.is_mounted:
                return False, "Must unmount to shrink ext filesystem"

            size_arg = f"{new_size_bytes // 1024}K"
            if growing:
                # Resize partition first, then filesystem
                # (Simplified - full implementation would use parted/sfdisk)
                result = self.run_command(
                    [self.RESIZE2FS, partition_path, size_arg],
                    timeout=3600,
                )
            else:
                # Filesystem first, then partition
                result = self.run_command(
                    [self.RESIZE2FS, partition_path, size_arg],
                    timeout=3600,
                )

            if not result.success:
                return False, f"resize2fs failed: {result.stderr}"

        elif partition.filesystem == FileSystem.XFS:
            if not partition.is_mounted:
                return False, "XFS must be mounted to resize"
            if not growing:
                return False, "XFS cannot be shrunk"

            result = self.run_command(
                [self.XFS_GROWFS, partition.mountpoint],
                timeout=3600,
            )
            if not result.success:
                return False, f"xfs_growfs failed: {result.stderr}"

        elif partition.filesystem == FileSystem.BTRFS:
            if not partition.is_mounted:
                return False, "BTRFS must be mounted to resize"

            size_arg = str(new_size_bytes)
            result = self.run_command(
                [self.BTRFS, "filesystem", "resize", size_arg, partition.mountpoint],
                timeout=3600,
            )
            if not result.success:
                return False, f"btrfs resize failed: {result.stderr}"

        else:
            return False, f"Resize not supported for {partition.filesystem.value}"

        return True, f"Resized {partition_path}"

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
            return False, "Partition move is not supported in the Linux backend yet"

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

        return False, "Partition merge is not supported in the Linux backend yet"

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

        return False, "Partition split is not supported in the Linux backend yet"

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

    def allocate_free_space(
        self,
        options: AllocateFreeSpaceOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Allocate free space is not supported in the Linux backend yet"

    def one_click_adjust_space(
        self,
        options: OneClickAdjustOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "One-click adjust space is not supported in the Linux backend yet"

    def quick_partition_disk(
        self,
        options: QuickPartitionOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Quick partitioning is not supported in the Linux backend yet"

    def change_partition_attributes(
        self,
        options: PartitionAttributeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Changing partition attributes is not supported in the Linux backend yet"

    def initialize_disk(
        self,
        options: InitializeDiskOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        return False, "Disk initialization is not supported in the Linux backend yet"

    def wipe_device(
        self,
        options: WipeOptions,
        context: JobContext | None = None,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Wipe a disk or partition."""
        target_disk = self.get_disk_info(options.target_path)
        target_partition = self.get_partition_info(options.target_path)

        if not target_disk and not target_partition:
            return False, f"Target not found: {options.target_path}"

        if target_disk and target_disk.is_system_disk:
            return False, "Cannot wipe the system disk"

        if target_disk:
            for part in target_disk.partitions:
                if part.is_mounted:
                    return False, f"Partition {part.device_path} is mounted"

        if target_partition and target_partition.is_mounted:
            return False, f"Partition is mounted at {target_partition.mountpoint}"

        method = options.method.lower()
        passes = max(1, options.passes)

        if method == "dod":
            pass_sources = ["/dev/zero", "/dev/urandom", "/dev/zero"]
        elif method == "random":
            pass_sources = ["/dev/urandom"] * passes
        else:
            pass_sources = ["/dev/zero"] * passes

        if context:
            context.update_progress(message=f"Wiping {options.target_path}")

        if dry_run:
            return True, f"Would wipe {options.target_path} with method {method}"

        for idx, source in enumerate(pass_sources, start=1):
            if context:
                context.update_progress(message=f"Wipe pass {idx}/{len(pass_sources)}")

            cmd = [
                self.DD,
                f"if={source}",
                f"of={options.target_path}",
                "bs=64M",
                "status=progress",
                "conv=fdatasync",
            ]
            result = self.run_command(cmd, timeout=86400, check=False)
            if not result.success:
                return False, f"Wipe failed: {result.stderr}"

        os.sync()
        return True, f"Wipe completed for {options.target_path}"

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
            "Partition recovery requires external tooling (e.g., testdisk)",
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
        if not self._check_tool(self.SGDISK):
            return False, "sgdisk not found (required for conversion)"

        disk = self.get_disk_info(options.disk_path)
        if not disk:
            return False, f"Disk not found: {options.disk_path}"

        if disk.is_system_disk:
            return False, "Cannot convert the system disk"

        if disk.partition_style == options.target_style:
            return True, f"Disk already uses {options.target_style.name}"

        if options.target_style == PartitionStyle.GPT:
            cmd = [self.SGDISK, "--mbrtogpt", options.disk_path]
        elif options.target_style == PartitionStyle.MBR:
            cmd = [self.SGDISK, "--gpttombr", options.disk_path]
        else:
            return False, "Unsupported target partition style"

        if context:
            context.update_progress(message=f"Converting {options.disk_path} to {options.target_style.name}")

        if dry_run:
            return True, f"Would run: {' '.join(cmd)}"

        result = self.run_command(cmd, timeout=300, check=False)
        if not result.success:
            return False, f"Conversion failed: {result.stderr}"

        self.run_command(["partprobe", options.disk_path], check=False)
        return True, f"Converted {options.disk_path} to {options.target_style.name}"

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
        """Clone a disk block-by-block using dd."""
        if mode == CloneMode.INTELLIGENT and context:
            context.add_warning(
                "Intelligent clone is not supported on Linux; using sector-by-sector copy."
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
                return False, f"Target partition {partition.device_path} is mounted"

        if context:
            context.update_progress(
                message=f"Cloning {source_path} to {target_path}",
                bytes_total=source_disk.size_bytes,
            )

        if dry_run:
            return True, f"Would clone {source_path} to {target_path}"

        return self._run_dd_clone(
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
                "Intelligent clone is not supported on Linux; using sector-by-sector copy."
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

        return self._run_dd_clone(
            source_path,
            target_path,
            source_part.size_bytes,
            context,
            verify,
        )

    def _run_dd_clone(
        self,
        source: str,
        target: str,
        total_bytes: int,
        context: JobContext | None,
        verify: bool,
    ) -> tuple[bool, str]:
        """Run dd for cloning with progress tracking."""
        block_size = 64 * 1024 * 1024  # 64 MB
        count = (total_bytes + block_size - 1) // block_size

        cmd = [
            self.DD,
            f"if={source}",
            f"of={target}",
            f"bs={block_size}",
            f"count={count}",
            "status=progress",
            "conv=fsync",
        ]

        logger.info("Starting clone", source=source, target=target, total_bytes=total_bytes)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Monitor progress from stderr (dd outputs progress there)
            start_time = time.time()
            last_bytes = 0

            while proc.poll() is None:
                if context:
                    context.check_cancelled()
                    context.wait_if_paused()

                # Read progress from stderr
                line = proc.stderr.readline() if proc.stderr else ""
                if line:
                    # Parse dd progress output
                    match = re.search(r"(\d+)\s+bytes", line)
                    if match:
                        bytes_done = int(match.group(1))
                        elapsed = time.time() - start_time
                        rate = bytes_done / elapsed if elapsed > 0 else 0

                        if context:
                            context.update_progress(
                                current=int((bytes_done / total_bytes) * 100),
                                bytes_processed=bytes_done,
                                rate_bytes_per_sec=rate,
                                message=f"Copied {bytes_done:,} bytes",
                            )

                time.sleep(0.1)

            returncode = proc.wait()
            stderr_remaining = proc.stderr.read() if proc.stderr else ""

            if returncode != 0:
                return False, f"dd failed: {stderr_remaining}"

            # Verify if requested
            if verify:
                if context:
                    context.update_progress(message="Verifying clone...")

                success, msg = self._verify_clone(source, target, total_bytes, context)
                if not success:
                    return False, f"Verification failed: {msg}"

            return True, "Clone completed successfully"

        except Exception as e:
            return False, f"Clone failed: {e}"

    def _verify_clone(
        self,
        source: str,
        target: str,
        size_bytes: int,
        context: JobContext | None,
    ) -> tuple[bool, str]:
        """Verify clone by comparing checksums."""
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
                "Intelligent backup is not supported on Linux; using sector-by-sector capture."
            )
        # Check source
        source_info = self.get_disk_info(source_path) or self.get_partition_info(source_path)
        if not source_info:
            return False, f"Source not found: {source_path}", None

        source_size = source_info.size_bytes

        # Determine compression tool
        compress_cmd = None
        image_suffix = ""
        level_flag: list[str] = []

        if compression_level:
            if compression in ("gzip", "gz"):
                level_flag = [
                    "-1"
                    if compression_level == CompressionLevel.FAST
                    else "-9"
                    if compression_level == CompressionLevel.MAXIMUM
                    else "-6"
                ]
            elif compression == "zstd":
                level_flag = [
                    "-1"
                    if compression_level == CompressionLevel.FAST
                    else "-9"
                    if compression_level == CompressionLevel.MAXIMUM
                    else "-3"
                ]
            elif compression == "lz4":
                level_flag = [
                    "-1"
                    if compression_level == CompressionLevel.FAST
                    else "-9"
                    if compression_level == CompressionLevel.MAXIMUM
                    else "-3"
                ]

        if compression == "gzip":
            if not self._check_tool(self.GZIP):
                return False, "gzip not found", None
            compress_cmd = [self.GZIP, "-c", *level_flag]
            image_suffix = ".gz"
        elif compression == "lz4":
            if not self._check_tool(self.LZ4):
                return False, "lz4 not found", None
            compress_cmd = [self.LZ4, "-c", *level_flag]
            image_suffix = ".lz4"
        elif compression == "zstd":
            if not self._check_tool(self.ZSTD):
                return False, "zstd not found", None
            compress_cmd = [self.ZSTD, "-c", *level_flag] if level_flag else [self.ZSTD, "-c", "-3"]
            image_suffix = ".zst"

        final_path = Path(str(image_path) + image_suffix) if image_suffix else image_path

        if context:
            context.update_progress(
                message=f"Creating image of {source_path}",
                bytes_total=source_size,
            )

        if dry_run:
            return True, f"Would create image at {final_path}", None

        # Ensure parent directory exists
        final_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            start_time = datetime.now()
            hasher = hashlib.sha256() if verify else None

            with open(source_path, "rb") as src:
                if compress_cmd:
                    # Pipe through compression
                    with open(final_path, "wb") as out:
                        proc = subprocess.Popen(
                            compress_cmd,
                            stdin=subprocess.PIPE,
                            stdout=out,
                        )

                        bytes_processed = 0
                        block_size = 64 * 1024 * 1024

                        while True:
                            if context:
                                context.check_cancelled()

                            data = src.read(block_size)
                            if not data:
                                break

                            if hasher:
                                hasher.update(data)
                            proc.stdin.write(data)  # type: ignore
                            bytes_processed += len(data)

                            if context:
                                elapsed = (datetime.now() - start_time).total_seconds()
                                rate = bytes_processed / elapsed if elapsed > 0 else 0
                                context.update_progress(
                                    current=int((bytes_processed / source_size) * 100),
                                    bytes_processed=bytes_processed,
                                    rate_bytes_per_sec=rate,
                                )

                        proc.stdin.close()  # type: ignore
                        proc.wait()

                        if proc.returncode != 0:
                            return False, "Compression failed", None
                else:
                    # No compression
                    with open(final_path, "wb") as out:
                        bytes_processed = 0
                        block_size = 64 * 1024 * 1024

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
                compression=compression,
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

        # Get image info
        image_info = self.get_image_info(image_path)
        if not image_info:
            return False, "Could not read image metadata"

        # Check target
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

        # Check if mounted
        if isinstance(target_info, Partition) and target_info.is_mounted:
            return False, f"Target is mounted at {target_info.mountpoint}"
        elif isinstance(target_info, Disk):
            for part in target_info.partitions:
                if part.is_mounted:
                    return False, f"Partition {part.device_path} is mounted"

        if context:
            context.update_progress(
                message=f"Restoring image to {target_path}",
                bytes_total=image_info.source_size_bytes,
            )

        if dry_run:
            return True, f"Would restore {image_path} to {target_path}"

        # Determine decompression
        decompress_cmd = None
        if image_info.compression == "gzip" or str(image_path).endswith(".gz"):
            decompress_cmd = [self.GZIP, "-d", "-c"]
        elif image_info.compression == "lz4" or str(image_path).endswith(".lz4"):
            decompress_cmd = [self.LZ4, "-d", "-c"]
        elif image_info.compression == "zstd" or str(image_path).endswith(".zst"):
            decompress_cmd = [self.ZSTD, "-d", "-c"]

        try:
            start_time = datetime.now()
            hasher = hashlib.sha256() if verify else None

            with open(target_path, "wb") as tgt:
                if decompress_cmd:
                    # Decompress
                    decompress_cmd.append(str(image_path))
                    proc = subprocess.Popen(
                        decompress_cmd,
                        stdout=subprocess.PIPE,
                    )

                    bytes_processed = 0
                    block_size = 64 * 1024 * 1024

                    while True:
                        if context:
                            context.check_cancelled()

                        data = proc.stdout.read(block_size)  # type: ignore
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

                    proc.wait()
                    if proc.returncode != 0:
                        return False, "Decompression failed"
                else:
                    # No decompression
                    with open(image_path, "rb") as src:
                        bytes_processed = 0
                        block_size = 64 * 1024 * 1024

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

            # Verify checksum
            if verify and hasher and image_info.checksum:
                if hasher.hexdigest() != image_info.checksum:
                    return False, "Checksum verification failed"

            # Sync
            os.sync()

            return True, f"Image restored to {target_path}"

        except Exception as e:
            return False, f"Failed to restore image: {e}"

    def get_image_info(self, image_path: Path) -> ImageInfo | None:
        """Get information about an image file."""
        # Try to read metadata file
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

        # Infer from file
        if not image_path.exists():
            return None

        compression = None
        if str(image_path).endswith(".gz"):
            compression = "gzip"
        elif str(image_path).endswith(".lz4"):
            compression = "lz4"
        elif str(image_path).endswith(".zst"):
            compression = "zstd"

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
        """Create bootable rescue media (ISO) for Linux."""
        artifacts: dict[str, Any] = {}

        if not self._check_tool(self.XORRISO):
            return False, "xorriso not found (required for ISO creation)", artifacts

        if context:
            context.update_progress(message="Creating rescue media structure")

        if dry_run:
            return True, f"Would create rescue ISO at {output_path}", artifacts

        try:
            # Create temporary directory structure
            with tempfile.TemporaryDirectory() as tmpdir:
                tmppath = Path(tmpdir)
                iso_root = tmppath / "iso"
                iso_root.mkdir()

                # Create directory structure
                (iso_root / "boot" / "grub").mkdir(parents=True)
                (iso_root / "diskforge").mkdir()
                (iso_root / "scripts").mkdir()

                # Create GRUB config
                grub_cfg = iso_root / "boot" / "grub" / "grub.cfg"
                grub_cfg.write_text(self._generate_grub_config())
                artifacts["grub_config"] = str(grub_cfg)

                # Create rescue script
                rescue_script = iso_root / "scripts" / "diskforge-rescue.sh"
                rescue_script.write_text(self._generate_rescue_script())
                rescue_script.chmod(0o755)
                artifacts["rescue_script"] = str(rescue_script)

                # Create instructions file
                readme = iso_root / "README.txt"
                readme.write_text(self._generate_rescue_readme())
                artifacts["readme"] = str(readme)

                if context:
                    context.update_progress(message="Building ISO image")

                # Build ISO with xorriso
                output_path.parent.mkdir(parents=True, exist_ok=True)

                xorriso_cmd = [
                    self.XORRISO,
                    "-as", "mkisofs",
                    "-o", str(output_path),
                    "-iso-level", "3",
                    "-full-iso9660-filenames",
                    "-volid", "DISKFORGE_RESCUE",
                    "-eltorito-boot", "boot/grub/grub.cfg",
                    "-no-emul-boot",
                    "-boot-load-size", "4",
                    "-boot-info-table",
                    str(iso_root),
                ]

                result = self.run_command(xorriso_cmd, timeout=600)

                if not result.success:
                    # Fall back to creating a tar archive
                    tar_path = output_path.with_suffix(".tar.gz")
                    import tarfile

                    with tarfile.open(tar_path, "w:gz") as tar:
                        tar.add(iso_root, arcname="diskforge-rescue")

                    artifacts["archive"] = str(tar_path)
                    return True, f"Created rescue archive at {tar_path} (xorriso unavailable)", artifacts

                artifacts["iso"] = str(output_path)
                return True, f"Rescue ISO created at {output_path}", artifacts

        except Exception as e:
            return False, f"Failed to create rescue media: {e}", artifacts

    def _generate_grub_config(self) -> str:
        """Generate GRUB configuration for rescue ISO."""
        return """# DiskForge Rescue Media GRUB Configuration

set default=0
set timeout=10

menuentry "DiskForge Rescue Environment" {
    echo "Loading DiskForge rescue environment..."
    echo "Note: This ISO provides rescue scripts."
    echo "Boot your Linux system and mount this ISO."
    echo ""
    echo "Usage:"
    echo "  mount -o loop diskforge-rescue.iso /mnt"
    echo "  /mnt/scripts/diskforge-rescue.sh"
    echo ""
    echo "Press any key to continue..."
    sleep 5
}

menuentry "Boot from first hard drive" {
    chainloader (hd0)+1
}
"""

    def _generate_rescue_script(self) -> str:
        """Generate rescue shell script."""
        return """#!/bin/bash
# DiskForge Rescue Script
# Run this from a Linux live environment

set -e

echo "=================================="
echo "  DiskForge Rescue Environment"
echo "=================================="
echo ""

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Check for required tools
for tool in lsblk blkid dd; do
    if ! command -v $tool &> /dev/null; then
        echo "Required tool not found: $tool"
        exit 1
    fi
done

echo "System Information:"
echo "-------------------"
uname -a
echo ""

echo "Available Disks:"
echo "----------------"
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT
echo ""

echo "Disk UUIDs:"
echo "-----------"
blkid
echo ""

echo "DiskForge rescue environment ready."
echo "Use standard tools for disk operations:"
echo "  - lsblk, blkid: Disk information"
echo "  - dd: Disk cloning/imaging"
echo "  - sfdisk/parted: Partition management"
echo "  - mkfs.*: Filesystem creation"
echo ""

# Interactive menu
while true; do
    echo "Options:"
    echo "  1) Show disk information"
    echo "  2) Show partition details"
    echo "  3) Clone disk (interactive)"
    echo "  4) Create disk image"
    echo "  5) Exit"
    echo ""
    read -p "Select option: " choice

    case $choice in
        1)
            lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL
            ;;
        2)
            read -p "Enter device (e.g., /dev/sda): " device
            if [ -b "$device" ]; then
                sfdisk -l "$device" 2>/dev/null || fdisk -l "$device"
            else
                echo "Invalid device"
            fi
            ;;
        3)
            echo "Clone disk:"
            read -p "Source device: " source
            read -p "Target device: " target
            if [ -b "$source" ] && [ -b "$target" ]; then
                echo "WARNING: This will DESTROY all data on $target"
                read -p "Type 'yes' to continue: " confirm
                if [ "$confirm" == "yes" ]; then
                    dd if="$source" of="$target" bs=64M status=progress conv=fsync
                    echo "Clone complete"
                fi
            else
                echo "Invalid devices"
            fi
            ;;
        4)
            echo "Create disk image:"
            read -p "Source device: " source
            read -p "Output file path: " output
            if [ -b "$source" ]; then
                dd if="$source" bs=64M status=progress | gzip > "$output"
                echo "Image created: $output"
            else
                echo "Invalid source device"
            fi
            ;;
        5)
            exit 0
            ;;
        *)
            echo "Invalid option"
            ;;
    esac
    echo ""
done
"""

    def _generate_rescue_readme(self) -> str:
        """Generate README for rescue media."""
        return """DiskForge Rescue Media
======================

This rescue media provides tools for disk management in emergency situations.

USAGE
-----
1. Boot from a Linux live USB/CD (Ubuntu, Fedora, etc.)
2. Mount this ISO:
   mount -o loop diskforge-rescue.iso /mnt

3. Run the rescue script:
   /mnt/scripts/diskforge-rescue.sh

INCLUDED TOOLS
--------------
- diskforge-rescue.sh: Interactive disk management menu
- Standard Linux disk tools (lsblk, blkid, dd, etc.)

COMMON OPERATIONS
-----------------
Clone a disk:
  dd if=/dev/sda of=/dev/sdb bs=64M status=progress conv=fsync

Create disk image:
  dd if=/dev/sda bs=64M status=progress | gzip > disk.img.gz

Restore disk image:
  gunzip -c disk.img.gz | dd of=/dev/sda bs=64M status=progress

List disks:
  lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT

WARNING
-------
Disk operations are DESTRUCTIVE. Always verify source and target devices
before proceeding. Back up important data first.

For more information, visit: https://diskforge.dev/docs/rescue
"""

    # ==================== Mount Operations ====================

    def mount_partition(
        self,
        partition_path: str,
        mount_point: str,
        options: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Mount a partition."""
        # Validate partition
        if not self.validate_device_path(partition_path)[0]:
            return False, f"Invalid partition path: {partition_path}"

        # Create mount point if needed
        Path(mount_point).mkdir(parents=True, exist_ok=True)

        cmd = [self.MOUNT]
        if options:
            cmd.extend(["-o", ",".join(options)])
        cmd.extend([partition_path, mount_point])

        result = self.run_command(cmd)
        if result.success:
            return True, f"Mounted {partition_path} at {mount_point}"
        return False, f"Mount failed: {result.stderr}"

    def unmount_partition(
        self,
        partition_path: str,
        force: bool = False,
    ) -> tuple[bool, str]:
        """Unmount a partition."""
        cmd = [self.UMOUNT]
        if force:
            cmd.append("-f")
        cmd.append(partition_path)

        result = self.run_command(cmd)
        if result.success:
            return True, f"Unmounted {partition_path}"
        return False, f"Unmount failed: {result.stderr}"

    # ==================== SMART Operations ====================

    def get_smart_info(self, device_path: str) -> dict[str, Any] | None:
        """Get SMART information for a disk."""
        if not self._check_tool(self.SMARTCTL):
            return None

        result = self.run_command(
            [self.SMARTCTL, "-j", "-a", device_path],
            check=False,
        )

        if not result.success:
            return None

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    # ==================== Utility Methods ====================

    def validate_device_path(self, path: str) -> tuple[bool, str]:
        """Validate a device path."""
        if not path.startswith("/dev/"):
            return False, "Device path must start with /dev/"

        if not os.path.exists(path):
            return False, f"Device does not exist: {path}"

        try:
            mode = os.stat(path).st_mode
            import stat

            if not stat.S_ISBLK(mode):
                return False, f"Not a block device: {path}"
        except OSError as e:
            return False, f"Cannot stat device: {e}"

        return True, "Valid device path"

    def is_device_mounted(self, device_path: str) -> bool:
        """Check if a device is mounted."""
        mounts = self._get_mounts()
        return device_path in mounts

    def get_mounted_devices(self) -> dict[str, str]:
        """Get mapping of mounted devices to mount points."""
        return self._get_mounts()

    def is_system_device(self, device_path: str) -> bool:
        """Check if a device is the system disk."""
        system_devices = self._get_system_devices()
        return device_path in system_devices
