"""
DiskForge Windows Platform Backend.

Implements disk operations using Windows tools:
- PowerShell Get-Disk, Get-Partition, Get-Volume
- WMI/CIM for disk information
- diskpart for partitioning
- wbadmin for backup operations
"""

from diskforge.platform.windows.backend import WindowsBackend
from diskforge.platform.windows.parsers import (
    parse_powershell_json,
    parse_diskpart_output,
)

__all__ = [
    "WindowsBackend",
    "parse_powershell_json",
    "parse_diskpart_output",
]
