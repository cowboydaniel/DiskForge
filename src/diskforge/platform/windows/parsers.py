"""
Windows output parsers.

Parsers for PowerShell, diskpart, and WMI output.
"""

from __future__ import annotations

import json
import re
from typing import Any

from diskforge.core.models import (
    Disk,
    DiskInventory,
    DiskType,
    FileSystem,
    Partition,
    PartitionFlag,
    PartitionStyle,
)


def parse_powershell_json(output: str) -> list[dict[str, Any]]:
    """Parse JSON output from PowerShell commands."""
    output = output.strip()
    if not output:
        return []

    try:
        data = json.loads(output)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        return []


def parse_disk_type_windows(bus_type: str | None, media_type: str | None) -> DiskType:
    """Determine disk type from Windows properties."""
    if bus_type:
        bus_lower = bus_type.lower()
        if "nvme" in bus_lower:
            return DiskType.NVME
        if "usb" in bus_lower:
            return DiskType.USB
        if "virtual" in bus_lower:
            return DiskType.VIRTUAL

    if media_type:
        media_lower = media_type.lower()
        if "ssd" in media_lower:
            return DiskType.SSD
        if "hdd" in media_lower:
            return DiskType.HDD

    return DiskType.UNKNOWN


def parse_partition_style_windows(style: str | int | None) -> PartitionStyle:
    """Parse partition style from Windows property."""
    if style is None:
        return PartitionStyle.UNKNOWN

    if isinstance(style, int):
        if style == 1:
            return PartitionStyle.MBR
        elif style == 2:
            return PartitionStyle.GPT
        return PartitionStyle.UNKNOWN

    style_lower = str(style).lower()
    if "gpt" in style_lower:
        return PartitionStyle.GPT
    if "mbr" in style_lower:
        return PartitionStyle.MBR
    if "raw" in style_lower:
        return PartitionStyle.RAW

    return PartitionStyle.UNKNOWN


def parse_filesystem_windows(fs_type: str | None) -> FileSystem:
    """Parse filesystem type from Windows."""
    if not fs_type:
        return FileSystem.UNKNOWN

    fs_map = {
        "ntfs": FileSystem.NTFS,
        "fat32": FileSystem.FAT32,
        "fat": FileSystem.FAT32,
        "exfat": FileSystem.EXFAT,
        "refs": FileSystem.REFS,
        "raw": FileSystem.RAW,
    }

    return fs_map.get(fs_type.lower(), FileSystem.UNKNOWN)


def parse_partition_flags_windows(
    is_boot: bool | None,
    is_system: bool | None,
    is_hidden: bool | None,
    is_active: bool | None,
    gpt_type: str | None,
) -> list[PartitionFlag]:
    """Parse partition flags from Windows properties."""
    flags = []

    if is_boot:
        flags.append(PartitionFlag.BOOT)
    if is_system:
        flags.append(PartitionFlag.SYSTEM)
    if is_hidden:
        flags.append(PartitionFlag.HIDDEN)
    if is_active:
        flags.append(PartitionFlag.ACTIVE)

    # Check GPT type GUIDs
    if gpt_type:
        gpt_lower = gpt_type.lower()
        gpt_types = {
            "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": PartitionFlag.ESP,
            "e3c9e316-0b5c-4db8-817d-f92df00215ae": PartitionFlag.MSFTRES,
            "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": PartitionFlag.MSFTDATA,
            "de94bba4-06d1-4d40-a16a-bfd50179d6ac": PartitionFlag.DIAG,
        }
        if gpt_lower in gpt_types:
            flags.append(gpt_types[gpt_lower])

    return flags


def parse_diskpart_output(output: str) -> dict[str, Any]:
    """
    Parse diskpart list output.

    Returns structured data about disks or partitions.
    """
    result: dict[str, Any] = {"items": []}
    lines = output.strip().split("\n")

    current_section = None
    headers: list[str] = []
    header_positions: list[tuple[int, int]] = []

    for line in lines:
        line_stripped = line.strip()

        # Detect section headers
        if line_stripped.startswith("Disk ###"):
            current_section = "disks"
            headers = ["number", "status", "size", "free", "dyn", "gpt"]
            continue
        elif line_stripped.startswith("Volume ###"):
            current_section = "volumes"
            headers = ["number", "letter", "label", "fs", "type", "size", "status", "info"]
            continue
        elif line_stripped.startswith("Partition ###"):
            current_section = "partitions"
            headers = ["number", "type", "size", "offset"]
            continue

        # Skip separator lines
        if set(line_stripped) <= {"-", " ", ""}:
            continue

        # Parse data lines
        if current_section and line_stripped:
            # Try to parse based on section
            if current_section == "disks":
                match = re.match(
                    r"Disk\s+(\d+)\s+(\w+)\s+([\d\s]+\w+)\s+([\d\s]+\w+)?\s*(\*?)\s*(\*?)",
                    line_stripped,
                )
                if match:
                    result["items"].append(
                        {
                            "type": "disk",
                            "number": int(match.group(1)),
                            "status": match.group(2),
                            "size": match.group(3).strip(),
                            "free": match.group(4).strip() if match.group(4) else "0 B",
                            "dynamic": bool(match.group(5)),
                            "gpt": bool(match.group(6)),
                        }
                    )

            elif current_section == "volumes":
                match = re.match(
                    r"Volume\s+(\d+)\s+([A-Z]?)\s*(\S*)\s*(\w+)\s+(\w+)\s+([\d\s]+\w+)\s+(\w+)\s*(\w*)",
                    line_stripped,
                )
                if match:
                    result["items"].append(
                        {
                            "type": "volume",
                            "number": int(match.group(1)),
                            "letter": match.group(2) or None,
                            "label": match.group(3) or None,
                            "filesystem": match.group(4),
                            "vol_type": match.group(5),
                            "size": match.group(6).strip(),
                            "status": match.group(7),
                            "info": match.group(8) or None,
                        }
                    )

            elif current_section == "partitions":
                match = re.match(
                    r"Partition\s+(\d+)\s+(\w+)\s+([\d\s]+\w+)\s+([\d\s]+\w+)",
                    line_stripped,
                )
                if match:
                    result["items"].append(
                        {
                            "type": "partition",
                            "number": int(match.group(1)),
                            "part_type": match.group(2),
                            "size": match.group(3).strip(),
                            "offset": match.group(4).strip(),
                        }
                    )

    return result


def build_disk_from_powershell(
    disk_data: dict[str, Any],
    partitions: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    system_disk_number: int | None,
) -> Disk:
    """Build a Disk object from PowerShell disk data."""
    disk_number = disk_data.get("Number", disk_data.get("DiskNumber", 0))
    device_path = f"\\\\.\\PhysicalDrive{disk_number}"

    disk = Disk(
        device_path=device_path,
        model=disk_data.get("FriendlyName", disk_data.get("Model", "Unknown")),
        serial=disk_data.get("SerialNumber"),
        size_bytes=int(disk_data.get("Size", 0)),
        sector_size=int(disk_data.get("LogicalSectorSize", 512)),
        disk_type=parse_disk_type_windows(
            disk_data.get("BusType"),
            disk_data.get("MediaType"),
        ),
        partition_style=parse_partition_style_windows(disk_data.get("PartitionStyle")),
        is_removable=disk_data.get("IsOffline", False)
        or disk_data.get("BusType", "").lower() == "usb",
        is_read_only=disk_data.get("IsReadOnly", False),
        vendor=disk_data.get("Manufacturer"),
        is_system_disk=(disk_number == system_disk_number),
    )

    # Add partitions
    disk_partitions = [p for p in partitions if p.get("DiskNumber") == disk_number]
    for part_data in disk_partitions:
        partition = build_partition_from_powershell(part_data, volumes, disk_number)
        if partition:
            disk.partitions.append(partition)

    return disk


def build_partition_from_powershell(
    part_data: dict[str, Any],
    volumes: list[dict[str, Any]],
    disk_number: int,
) -> Partition | None:
    """Build a Partition object from PowerShell partition data."""
    part_number = part_data.get("PartitionNumber", 0)
    device_path = f"\\\\.\\PhysicalDrive{disk_number}Partition{part_number}"

    # Find matching volume for drive letter and filesystem
    drive_letter = None
    filesystem = FileSystem.UNKNOWN
    label = None
    free_space = None
    used_space = None

    access_paths = part_data.get("AccessPaths", [])
    if access_paths and isinstance(access_paths, list):
        for path in access_paths:
            if isinstance(path, str) and len(path) >= 2 and path[1] == ":":
                drive_letter = path[0]
                break

    # Match with volume data
    for vol in volumes:
        vol_letter = vol.get("DriveLetter")
        if vol_letter and drive_letter and vol_letter == drive_letter:
            filesystem = parse_filesystem_windows(vol.get("FileSystem"))
            label = vol.get("FileSystemLabel")
            size_remaining = vol.get("SizeRemaining")
            vol_size = vol.get("Size")
            if size_remaining is not None:
                free_space = int(size_remaining)
            if vol_size is not None and free_space is not None:
                used_space = int(vol_size) - free_space
            break

    # Also check partition's own filesystem type
    if filesystem == FileSystem.UNKNOWN:
        fs_type = part_data.get("Type", "")
        if fs_type:
            filesystem = parse_filesystem_windows(fs_type)

    return Partition(
        device_path=device_path,
        number=part_number,
        start_sector=int(part_data.get("Offset", 0)) // 512,
        end_sector=(int(part_data.get("Offset", 0)) + int(part_data.get("Size", 0))) // 512,
        size_bytes=int(part_data.get("Size", 0)),
        filesystem=filesystem,
        label=label,
        uuid=part_data.get("Guid"),
        mountpoint=f"{drive_letter}:\\" if drive_letter else None,
        flags=parse_partition_flags_windows(
            part_data.get("IsBoot"),
            part_data.get("IsSystem"),
            part_data.get("IsHidden"),
            part_data.get("IsActive"),
            part_data.get("GptType"),
        ),
        partition_type_uuid=part_data.get("GptType"),
        is_mounted=drive_letter is not None,
        free_space_bytes=free_space,
        used_space_bytes=used_space,
    )


def parse_size_string(size_str: str) -> int:
    """Parse size string like '100 GB' to bytes."""
    match = re.match(r"([\d.]+)\s*(\w+)", size_str.strip())
    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2).upper()

    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }

    return int(value * multipliers.get(unit, 1))
