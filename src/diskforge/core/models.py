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
    skip_unallocated: bool = True
    compression: str | None = None  # For imaging
    chunk_size_bytes: int = 64 * 1024 * 1024  # 64 MB


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
class MigrationOptions:
    """Options for OS/system migration."""

    source_disk_path: str
    target_disk_path: str
    include_data: bool = True
    resize_target: bool = True
