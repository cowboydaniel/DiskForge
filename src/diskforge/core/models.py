"""
DiskForge data models.

Defines the core data structures for disks, partitions, and operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any


class DiskType(Enum):
    """Type of disk device."""

    HDD = auto()
    SSD = auto()
    NVME = auto()
    USB = auto()
    VIRTUAL = auto()
    RAID = auto()
    LOOP = auto()
    UNKNOWN = auto()


class PartitionStyle(Enum):
    """Partition table style."""

    GPT = auto()
    MBR = auto()
    RAW = auto()
    UNKNOWN = auto()


class PartitionRole(Enum):
    """Partition role for MBR partitioning."""

    PRIMARY = auto()
    LOGICAL = auto()


class DiskLayout(Enum):
    """Disk layout type (basic vs dynamic)."""

    BASIC = auto()
    DYNAMIC = auto()
    UNKNOWN = auto()


class FileSystem(Enum):
    """File system types."""

    NTFS = "ntfs"
    FAT32 = "vfat"
    FAT16 = "fat16"
    EXFAT = "exfat"
    EXT2 = "ext2"
    EXT3 = "ext3"
    EXT4 = "ext4"
    XFS = "xfs"
    BTRFS = "btrfs"
    ZFS = "zfs"
    SWAP = "swap"
    APFS = "apfs"
    HFS_PLUS = "hfsplus"
    REFS = "refs"
    RAW = "raw"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> FileSystem:
        """Create FileSystem from string value."""
        value_lower = value.lower().strip()
        for fs in cls:
            if fs.value == value_lower or fs.name.lower() == value_lower:
                return fs
        # Handle common aliases
        aliases = {
            "vfat": cls.FAT32,
            "fat": cls.FAT32,
            "linux_raid_member": cls.RAW,
            "lvm2_member": cls.RAW,
            "crypto_luks": cls.RAW,
        }
        return aliases.get(value_lower, cls.UNKNOWN)


class CloneMode(Enum):
    """Clone/backup strategy."""

    INTELLIGENT = "intelligent"
    SECTOR_BY_SECTOR = "sector_by_sector"


class CompressionLevel(Enum):
    """Compression level presets."""

    FAST = "fast"
    BALANCED = "balanced"
    MAXIMUM = "maximum"


class PartitionFlag(Enum):
    """Partition flags/attributes."""

    BOOT = auto()
    ESP = auto()  # EFI System Partition
    HIDDEN = auto()
    SYSTEM = auto()
    ACTIVE = auto()
    LVM = auto()
    RAID = auto()
    SWAP = auto()
    MSFTRES = auto()  # Microsoft Reserved
    MSFTDATA = auto()  # Basic data partition
    DIAG = auto()  # Recovery/diagnostic
    READONLY = auto()


@dataclass
class SMARTInfo:
    """SMART health information for a disk."""

    available: bool = False
    healthy: bool = True
    temperature_celsius: int | None = None
    power_on_hours: int | None = None
    reallocated_sectors: int | None = None
    pending_sectors: int | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def status_text(self) -> str:
        if not self.available:
            return "SMART not available"
        if self.healthy:
            return "Healthy"
        return "Warning: Issues detected"


@dataclass
class Partition:
    """Represents a disk partition."""

    device_path: str  # e.g., /dev/sda1 or \\.\PhysicalDrive0Partition1
    number: int
    start_sector: int
    end_sector: int
    size_bytes: int
    filesystem: FileSystem
    label: str | None = None
    uuid: str | None = None
    mountpoint: str | None = None  # Linux mount path or Windows drive letter
    flags: list[PartitionFlag] = field(default_factory=list)
    partition_type_uuid: str | None = None  # GPT partition type GUID
    partition_type_name: str | None = None
    is_mounted: bool = False
    free_space_bytes: int | None = None
    used_space_bytes: int | None = None

    @property
    def size_sectors(self) -> int:
        return self.end_sector - self.start_sector + 1

    @property
    def is_boot(self) -> bool:
        return PartitionFlag.BOOT in self.flags or PartitionFlag.ESP in self.flags

    @property
    def is_system(self) -> bool:
        return PartitionFlag.SYSTEM in self.flags

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_path": self.device_path,
            "number": self.number,
            "start_sector": self.start_sector,
            "end_sector": self.end_sector,
            "size_bytes": self.size_bytes,
            "filesystem": self.filesystem.value,
            "label": self.label,
            "uuid": self.uuid,
            "mountpoint": self.mountpoint,
            "flags": [f.name for f in self.flags],
            "is_mounted": self.is_mounted,
            "free_space_bytes": self.free_space_bytes,
            "used_space_bytes": self.used_space_bytes,
        }


@dataclass
class Disk:
    """Represents a physical or virtual disk."""

    device_path: str  # e.g., /dev/sda or \\.\PhysicalDrive0
    model: str
    serial: str | None = None
    size_bytes: int = 0
    sector_size: int = 512
    disk_type: DiskType = DiskType.UNKNOWN
    partition_style: PartitionStyle = PartitionStyle.UNKNOWN
    partitions: list[Partition] = field(default_factory=list)
    smart_info: SMARTInfo | None = None
    is_removable: bool = False
    is_system_disk: bool = False
    is_read_only: bool = False
    vendor: str | None = None
    firmware_version: str | None = None
    interface: str | None = None  # SATA, NVMe, USB, etc.
    wwn: str | None = None  # World Wide Name

    @property
    def size_sectors(self) -> int:
        return self.size_bytes // self.sector_size if self.sector_size > 0 else 0

    @property
    def total_partition_size(self) -> int:
        return sum(p.size_bytes for p in self.partitions)

    @property
    def unallocated_bytes(self) -> int:
        return max(0, self.size_bytes - self.total_partition_size)

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        parts = []
        if self.vendor:
            parts.append(self.vendor)
        if self.model:
            parts.append(self.model)
        if not parts:
            parts.append(self.device_path)
        return " ".join(parts)

    def get_partition_by_number(self, number: int) -> Partition | None:
        """Get partition by its number."""
        for p in self.partitions:
            if p.number == number:
                return p
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_path": self.device_path,
            "model": self.model,
            "serial": self.serial,
            "size_bytes": self.size_bytes,
            "sector_size": self.sector_size,
            "disk_type": self.disk_type.name,
            "partition_style": self.partition_style.name,
            "partitions": [p.to_dict() for p in self.partitions],
            "is_removable": self.is_removable,
            "is_system_disk": self.is_system_disk,
            "is_read_only": self.is_read_only,
            "vendor": self.vendor,
            "interface": self.interface,
            "unallocated_bytes": self.unallocated_bytes,
        }


@dataclass
class DiskInventory:
    """Complete inventory of all disks in the system."""

    disks: list[Disk] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    platform: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def total_disks(self) -> int:
        return len(self.disks)

    @property
    def total_partitions(self) -> int:
        return sum(len(d.partitions) for d in self.disks)

    @property
    def total_capacity_bytes(self) -> int:
        return sum(d.size_bytes for d in self.disks)

    def get_disk_by_path(self, path: str) -> Disk | None:
        """Find disk by device path."""
        for disk in self.disks:
            if disk.device_path == path:
                return disk
        return None

    def get_partition_by_path(self, path: str) -> tuple[Disk, Partition] | None:
        """Find partition by device path."""
        for disk in self.disks:
            for partition in disk.partitions:
                if partition.device_path == path:
                    return disk, partition
        return None

    def get_mounted_paths(self) -> list[str]:
        """Get all currently mounted device paths."""
        paths = []
        for disk in self.disks:
            for partition in disk.partitions:
                if partition.is_mounted:
                    paths.append(partition.device_path)
        return paths

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "platform": self.platform,
            "total_disks": self.total_disks,
            "total_partitions": self.total_partitions,
            "total_capacity_bytes": self.total_capacity_bytes,
            "disks": [d.to_dict() for d in self.disks],
            "errors": self.errors,
        }


@dataclass
class CloneOptions:
    """Options for disk/partition cloning."""

    source_path: str
    target_path: str
    verify: bool = True
    mode: CloneMode = CloneMode.INTELLIGENT
    schedule: str | None = None
    compression: str | None = None  # For imaging
    compression_level: CompressionLevel | None = None
    chunk_size_bytes: int = 64 * 1024 * 1024  # 64 MB


@dataclass
class ImageOptions:
    """Options for creating disk/partition images."""

    source_path: str
    image_path: Path
    compression: str | None = "zstd"
    compression_level: CompressionLevel | None = None
    verify: bool = True
    mode: CloneMode = CloneMode.INTELLIGENT
    schedule: str | None = None


@dataclass
class ImageInfo:
    """Information about a disk/partition image file."""

    path: str
    source_device: str
    source_size_bytes: int
    image_size_bytes: int
    compression: str | None = None
    created_at: datetime | None = None
    checksum: str | None = None
    checksum_algorithm: str = "sha256"
    format_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_device": self.source_device,
            "source_size_bytes": self.source_size_bytes,
            "image_size_bytes": self.image_size_bytes,
            "compression": self.compression,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "checksum": self.checksum,
            "checksum_algorithm": self.checksum_algorithm,
            "format_version": self.format_version,
            "metadata": self.metadata,
        }


@dataclass
class PartitionCreateOptions:
    """Options for creating a new partition."""

    disk_path: str
    size_bytes: int | None = None  # None = use all available space
    filesystem: FileSystem = FileSystem.EXT4
    label: str | None = None
    start_sector: int | None = None  # None = auto
    partition_type: str | None = None  # GPT type GUID
    align_to_mb: int = 1  # Alignment in MB


@dataclass
class FormatOptions:
    """Options for formatting a partition."""

    partition_path: str
    filesystem: FileSystem
    label: str | None = None
    quick: bool = True
    force: bool = False


@dataclass
class ResizeMoveOptions:
    """Options for resizing or moving a partition."""

    partition_path: str
    new_size_bytes: int | None = None
    new_start_sector: int | None = None
    align_to_mb: int = 1


@dataclass
class DynamicVolumeResizeMoveOptions:
    """Options for resizing or moving a dynamic volume."""

    volume_id: str
    new_size_bytes: int | None = None
    new_start_sector: int | None = None


@dataclass
class MergePartitionsOptions:
    """Options for merging two partitions."""

    primary_partition_path: str
    secondary_partition_path: str


@dataclass
class SplitPartitionOptions:
    """Options for splitting a partition into two."""

    partition_path: str
    split_size_bytes: int
    filesystem: FileSystem | None = None
    label: str | None = None
    align_to_mb: int = 1


@dataclass
class WipeOptions:
    """Options for wiping a disk or partition."""

    target_path: str
    method: str = "zero"
    passes: int = 1


@dataclass
class PartitionRecoveryOptions:
    """Options for partition recovery."""

    disk_path: str
    output_path: Path | None = None
    quick_scan: bool = True


@dataclass
class AlignOptions:
    """Options for alignment operations."""

    partition_path: str
    alignment_bytes: int = 4096


@dataclass
class ConvertDiskOptions:
    """Options for converting disk partition style."""

    disk_path: str
    target_style: PartitionStyle


@dataclass
class ConvertSystemDiskOptions:
    """Options for converting a system disk partition style."""

    disk_path: str
    target_style: PartitionStyle
    allow_full_os: bool = True


@dataclass
class ConvertFilesystemOptions:
    """Options for converting a partition filesystem."""

    partition_path: str
    target_filesystem: FileSystem
    allow_format: bool = False


@dataclass
class ConvertPartitionRoleOptions:
    """Options for converting a partition between primary/logical."""

    partition_path: str
    target_role: PartitionRole


@dataclass
class ConvertDiskLayoutOptions:
    """Options for converting a disk between basic/dynamic."""

    disk_path: str
    target_layout: DiskLayout


@dataclass
class MigrationOptions:
    """Options for OS/system migration."""

    source_disk_path: str
    target_disk_path: str
    include_data: bool = True
    resize_target: bool = True


@dataclass
class AllocateFreeSpaceOptions:
    """Options for allocating free space between partitions."""

    disk_path: str
    source_partition_path: str
    target_partition_path: str
    size_bytes: int | None = None


@dataclass
class OneClickAdjustOptions:
    """Options for one-click space adjustment."""

    disk_path: str
    target_partition_path: str | None = None
    prioritize_system: bool = True


@dataclass
class QuickPartitionOptions:
    """Options for quick disk partitioning."""

    disk_path: str
    partition_count: int = 1
    filesystem: FileSystem = FileSystem.EXT4
    label_prefix: str | None = None
    partition_size_bytes: int | None = None
    use_entire_disk: bool = True


@dataclass
class PartitionAttributeOptions:
    """Options for updating partition attributes."""

    partition_path: str
    drive_letter: str | None = None
    label: str | None = None
    partition_type_id: str | None = None
    serial_number: str | None = None


@dataclass
class InitializeDiskOptions:
    """Options for initializing a disk."""

    disk_path: str
    partition_style: PartitionStyle = PartitionStyle.GPT


@dataclass
class JunkFile:
    path: str
    size_bytes: int
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "category": self.category,
        }


@dataclass
class JunkScanResult:
    roots: list[str]
    total_size_bytes: int
    file_count: int
    files: list[JunkFile]
    skipped_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": self.roots,
            "total_size_bytes": self.total_size_bytes,
            "file_count": self.file_count,
            "files": [item.to_dict() for item in self.files],
            "skipped_paths": self.skipped_paths,
        }


@dataclass
class JunkCleanupResult:
    roots: list[str]
    removed_files: list[str]
    failed_files: list[str]
    freed_bytes: int
    total_files_removed: int
    total_files_failed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": self.roots,
            "removed_files": self.removed_files,
            "failed_files": self.failed_files,
            "freed_bytes": self.freed_bytes,
            "total_files_removed": self.total_files_removed,
            "total_files_failed": self.total_files_failed,
        }


@dataclass
class LargeFileEntry:
    path: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes}


@dataclass
class LargeFileScanResult:
    roots: list[str]
    min_size_bytes: int
    total_size_bytes: int
    file_count: int
    files: list[LargeFileEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": self.roots,
            "min_size_bytes": self.min_size_bytes,
            "total_size_bytes": self.total_size_bytes,
            "file_count": self.file_count,
            "files": [entry.to_dict() for entry in self.files],
        }


@dataclass
class DuplicateFileGroup:
    size_bytes: int
    file_hash: str
    paths: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "size_bytes": self.size_bytes,
            "file_hash": self.file_hash,
            "paths": self.paths,
        }


@dataclass
class DuplicateScanResult:
    roots: list[str]
    min_size_bytes: int
    total_wasted_bytes: int
    duplicate_groups: list[DuplicateFileGroup]
    skipped_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": self.roots,
            "min_size_bytes": self.min_size_bytes,
            "total_wasted_bytes": self.total_wasted_bytes,
            "duplicate_groups": [group.to_dict() for group in self.duplicate_groups],
            "skipped_paths": self.skipped_paths,
        }


@dataclass
class FileRemovalResult:
    removed: list[str]
    failed: list[str]
    freed_bytes: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "removed": self.removed,
            "failed": self.failed,
            "freed_bytes": self.freed_bytes,
            "message": self.message,
        }


@dataclass
class FreeSpaceReport:
    roots: list[str]
    total_reclaimable_bytes: int
    junk_bytes: int
    large_files_bytes: int
    duplicate_bytes: int
    junk_files: list[JunkFile] = field(default_factory=list)
    large_files: list[LargeFileEntry] = field(default_factory=list)
    duplicate_groups: list[DuplicateFileGroup] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots": self.roots,
            "total_reclaimable_bytes": self.total_reclaimable_bytes,
            "junk_bytes": self.junk_bytes,
            "large_files_bytes": self.large_files_bytes,
            "duplicate_bytes": self.duplicate_bytes,
            "junk_files": [item.to_dict() for item in self.junk_files],
            "large_files": [item.to_dict() for item in self.large_files],
            "duplicate_groups": [item.to_dict() for item in self.duplicate_groups],
        }


@dataclass
class FreeSpaceOptions:
    roots: list[str]
    exclude_patterns: list[str] = field(default_factory=list)
    junk_max_files: int | None = None
    large_min_size_bytes: int = 512 * 1024 * 1024
    large_max_results: int | None = 25
    duplicate_min_size_bytes: int = 32 * 1024 * 1024


@dataclass
class JunkCleanupOptions:
    roots: list[str]
    exclude_patterns: list[str] = field(default_factory=list)
    max_files: int | None = None


@dataclass
class LargeFileScanOptions:
    roots: list[str]
    min_size_bytes: int
    max_results: int | None = None
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class DuplicateScanOptions:
    roots: list[str]
    min_size_bytes: int
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class DuplicateRemovalOptions:
    duplicate_groups: list[DuplicateFileGroup]
    keep_strategy: str = "first"


@dataclass
class FileRemovalOptions:
    paths: list[str]


@dataclass
class MoveApplicationOptions:
    source_path: str
    destination_root: str


@dataclass
class MoveApplicationResult:
    success: bool
    message: str
    source_path: str
    destination_path: str
    bytes_moved: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "bytes_moved": self.bytes_moved,
        }
