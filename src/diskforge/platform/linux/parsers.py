"""
Linux output parsers.

Parsers for lsblk, blkid, sfdisk, and other Linux disk tools.
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


def parse_disk_type(tran: str | None, rota: str | None, path: str) -> DiskType:
    """Determine disk type from transport and rotation info."""
    if tran:
        tran_lower = tran.lower()
        if "nvme" in tran_lower or path.startswith("/dev/nvme"):
            return DiskType.NVME
        if "usb" in tran_lower:
            return DiskType.USB
        if "sata" in tran_lower or "ata" in tran_lower:
            if rota == "0":
                return DiskType.SSD
            return DiskType.HDD

    if path.startswith("/dev/loop"):
        return DiskType.LOOP
    if path.startswith("/dev/md"):
        return DiskType.RAID
    if path.startswith("/dev/dm-") or path.startswith("/dev/mapper/"):
        return DiskType.VIRTUAL

    # Default based on rotation
    if rota == "0":
        return DiskType.SSD
    elif rota == "1":
        return DiskType.HDD

    return DiskType.UNKNOWN


def parse_partition_flags(pttype: str | None, parttype: str | None) -> list[PartitionFlag]:
    """Parse partition flags from partition type."""
    flags = []

    # Known GPT partition type GUIDs
    gpt_types = {
        "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": PartitionFlag.ESP,
        "21686148-6449-6e6f-744e-656564454649": PartitionFlag.BOOT,  # BIOS boot
        "0657fd6d-a4ab-43c4-84e5-0933c84b4f4f": PartitionFlag.SWAP,
        "e6d6d379-f507-44c2-a23c-238f2a3df928": PartitionFlag.LVM,
        "a19d880f-05fc-4d3b-a006-743f0f84911e": PartitionFlag.RAID,
        "e3c9e316-0b5c-4db8-817d-f92df00215ae": PartitionFlag.MSFTRES,
        "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": PartitionFlag.MSFTDATA,
        "de94bba4-06d1-4d40-a16a-bfd50179d6ac": PartitionFlag.DIAG,
    }

    if parttype:
        parttype_lower = parttype.lower()
        if parttype_lower in gpt_types:
            flags.append(gpt_types[parttype_lower])

    return flags


def parse_lsblk_json(output: str) -> list[dict[str, Any]]:
    """Parse JSON output from lsblk."""
    try:
        data = json.loads(output)
        return data.get("blockdevices", [])
    except json.JSONDecodeError:
        return []


def parse_blkid_output(output: str) -> dict[str, dict[str, str]]:
    """
    Parse blkid output.

    Example input:
    /dev/sda1: UUID="xxxx" TYPE="ext4" PARTUUID="xxxx"
    """
    result: dict[str, dict[str, str]] = {}

    for line in output.strip().split("\n"):
        if not line or ":" not in line:
            continue

        device, rest = line.split(":", 1)
        device = device.strip()
        attrs: dict[str, str] = {}

        # Parse KEY="VALUE" pairs
        for match in re.finditer(r'(\w+)="([^"]*)"', rest):
            key, value = match.groups()
            attrs[key.upper()] = value

        result[device] = attrs

    return result


def parse_sfdisk_dump(output: str) -> dict[str, Any]:
    """
    Parse sfdisk dump output.

    Returns partition table information.
    """
    result: dict[str, Any] = {
        "label": None,
        "label_id": None,
        "device": None,
        "unit": "sectors",
        "partitions": [],
    }

    for line in output.strip().split("\n"):
        line = line.strip()

        if line.startswith("label:"):
            result["label"] = line.split(":", 1)[1].strip()
        elif line.startswith("label-id:"):
            result["label_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("device:"):
            result["device"] = line.split(":", 1)[1].strip()
        elif line.startswith("unit:"):
            result["unit"] = line.split(":", 1)[1].strip()
        elif line.startswith("/dev/"):
            # Partition line
            parts = line.split(":")
            if len(parts) >= 2:
                device = parts[0].strip()
                attrs_str = parts[1].strip()
                attrs: dict[str, str] = {}

                for attr in attrs_str.split(","):
                    attr = attr.strip()
                    if "=" in attr:
                        key, value = attr.split("=", 1)
                        attrs[key.strip()] = value.strip()

                result["partitions"].append({"device": device, "attrs": attrs})

    return result


def parse_partition_style(pttype: str | None) -> PartitionStyle:
    """Parse partition table type."""
    if not pttype:
        return PartitionStyle.UNKNOWN

    pttype_lower = pttype.lower()
    if pttype_lower == "gpt":
        return PartitionStyle.GPT
    elif pttype_lower in ("dos", "mbr", "msdos"):
        return PartitionStyle.MBR
    elif pttype_lower == "loop":
        return PartitionStyle.RAW

    return PartitionStyle.UNKNOWN


def build_disk_from_lsblk(
    block: dict[str, Any],
    blkid_info: dict[str, dict[str, str]],
    mounts: dict[str, str],
    system_devices: set[str],
) -> Disk:
    """Build a Disk object from lsblk block device data."""
    device_path = block.get("path", block.get("name", ""))
    if not device_path.startswith("/dev/"):
        device_path = f"/dev/{device_path}"

    # Determine disk type
    disk_type = parse_disk_type(
        block.get("tran"),
        block.get("rota"),
        device_path,
    )

    # Parse size
    size_str = block.get("size", "0")
    if isinstance(size_str, int):
        size_bytes = size_str
    else:
        try:
            size_bytes = int(size_str)
        except ValueError:
            size_bytes = 0

    # Parse sector size
    phy_sec = block.get("phy-sec", block.get("log-sec", 512))
    try:
        sector_size = int(phy_sec)
    except (ValueError, TypeError):
        sector_size = 512

    disk = Disk(
        device_path=device_path,
        model=block.get("model", "Unknown").strip() if block.get("model") else "Unknown",
        serial=block.get("serial"),
        size_bytes=size_bytes,
        sector_size=sector_size,
        disk_type=disk_type,
        partition_style=parse_partition_style(block.get("pttype")),
        is_removable=block.get("rm", False) in (True, "1", 1),
        is_read_only=block.get("ro", False) in (True, "1", 1),
        vendor=block.get("vendor", "").strip() if block.get("vendor") else None,
        wwn=block.get("wwn"),
        interface=block.get("tran"),
        is_system_disk=device_path in system_devices,
    )

    # Process partitions (children)
    for child in block.get("children", []):
        partition = build_partition_from_lsblk(child, blkid_info, mounts)
        if partition:
            disk.partitions.append(partition)

    return disk


def build_partition_from_lsblk(
    block: dict[str, Any],
    blkid_info: dict[str, dict[str, str]],
    mounts: dict[str, str],
) -> Partition | None:
    """Build a Partition object from lsblk child device data."""
    device_path = block.get("path", block.get("name", ""))
    if not device_path.startswith("/dev/"):
        device_path = f"/dev/{device_path}"

    # Skip non-partition types
    block_type = block.get("type", "")
    if block_type not in ("part", "partition", ""):
        return None

    # Get blkid info for this partition
    part_blkid = blkid_info.get(device_path, {})

    # Parse filesystem
    fstype = block.get("fstype") or part_blkid.get("TYPE", "")
    filesystem = FileSystem.from_string(fstype) if fstype else FileSystem.UNKNOWN

    # Parse size
    size_str = block.get("size", "0")
    if isinstance(size_str, int):
        size_bytes = size_str
    else:
        try:
            size_bytes = int(size_str)
        except ValueError:
            size_bytes = 0

    # Extract partition number from path
    part_num_match = re.search(r"(\d+)$", device_path)
    part_num = int(part_num_match.group(1)) if part_num_match else 0

    # Get mount info
    mountpoint = mounts.get(device_path) or block.get("mountpoint")
    is_mounted = bool(mountpoint)

    # Parse usage info
    fsused = block.get("fsused")
    fssize = block.get("fssize")
    used_bytes = None
    free_bytes = None

    if fsused:
        try:
            used_bytes = int(fsused)
        except (ValueError, TypeError):
            used_bytes = None

    if fssize and used_bytes is not None:
        try:
            free_bytes = int(fssize) - used_bytes
        except (ValueError, TypeError):
            free_bytes = None

    return Partition(
        device_path=device_path,
        number=part_num,
        start_sector=0,  # Would need sfdisk for exact values
        end_sector=0,
        size_bytes=size_bytes,
        filesystem=filesystem,
        label=block.get("label") or part_blkid.get("LABEL"),
        uuid=block.get("uuid") or part_blkid.get("UUID"),
        mountpoint=mountpoint,
        flags=parse_partition_flags(block.get("pttype"), block.get("parttype")),
        partition_type_uuid=block.get("parttype"),
        is_mounted=is_mounted,
        free_space_bytes=free_bytes,
        used_space_bytes=used_bytes,
    )


def parse_findmnt_json(output: str) -> dict[str, str]:
    """Parse findmnt JSON output to get mount mapping."""
    result: dict[str, str] = {}
    try:
        data = json.loads(output)
        filesystems = data.get("filesystems", [])

        def process_fs(fs: dict[str, Any]) -> None:
            source = fs.get("source", "")
            target = fs.get("target", "")
            if source and target and source.startswith("/dev/"):
                result[source] = target
            for child in fs.get("children", []):
                process_fs(child)

        for fs in filesystems:
            process_fs(fs)

    except json.JSONDecodeError:
        pass

    return result


def parse_proc_mounts() -> dict[str, str]:
    """Parse /proc/mounts as fallback."""
    result: dict[str, str] = {}
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("/dev/"):
                    result[parts[0]] = parts[1]
    except (OSError, IOError):
        pass
    return result


def parse_df_output(output: str) -> dict[str, dict[str, int]]:
    """Parse df output for filesystem usage."""
    result: dict[str, dict[str, int]] = {}

    lines = output.strip().split("\n")
    if len(lines) < 2:
        return result

    for line in lines[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 6 and parts[0].startswith("/dev/"):
            device = parts[0]
            try:
                result[device] = {
                    "total": int(parts[1]) * 1024,  # df uses 1K blocks
                    "used": int(parts[2]) * 1024,
                    "available": int(parts[3]) * 1024,
                }
            except ValueError:
                continue

    return result
