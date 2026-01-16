"""
DiskForge Platform Abstraction Layer.

Provides platform-specific implementations for disk operations
on Linux and Windows.
"""

from __future__ import annotations

import platform
import sys
from typing import TYPE_CHECKING

from diskforge.platform.base import PlatformBackend

if TYPE_CHECKING:
    pass


def get_platform_backend() -> PlatformBackend:
    """Get the appropriate platform backend for the current OS."""
    system = platform.system().lower()

    if system == "linux":
        from diskforge.platform.linux import LinuxBackend

        return LinuxBackend()
    elif system == "windows":
        from diskforge.platform.windows import WindowsBackend

        return WindowsBackend()
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def get_platform_name() -> str:
    """Get the current platform name."""
    return platform.system().lower()


def is_linux() -> bool:
    """Check if running on Linux."""
    return platform.system().lower() == "linux"


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == "windows"


def is_admin() -> bool:
    """Check if running with administrative privileges."""
    system = platform.system().lower()

    if system == "linux":
        import os

        return os.geteuid() == 0
    elif system == "windows":
        import ctypes

        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return False


__all__ = [
    "PlatformBackend",
    "get_platform_backend",
    "get_platform_name",
    "is_linux",
    "is_windows",
    "is_admin",
]
