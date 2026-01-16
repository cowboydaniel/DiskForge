"""
DiskForge Linux Platform Backend.

Implements disk operations using standard Linux tools:
- lsblk, blkid for inventory
- sfdisk/parted for partitioning
- mkfs.* for formatting
- dd for cloning/imaging
- resize2fs, xfs_growfs, btrfs for resizing
"""

from diskforge.platform.linux.backend import LinuxBackend
from diskforge.platform.linux.parsers import (
    parse_lsblk_json,
    parse_blkid_output,
    parse_sfdisk_dump,
)

__all__ = [
    "LinuxBackend",
    "parse_lsblk_json",
    "parse_blkid_output",
    "parse_sfdisk_dump",
]
