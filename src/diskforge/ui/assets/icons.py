"""Icon registry for DiskForge UI assets."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

_ICON_DIR = Path(__file__).resolve().parent / "icons"


class DiskForgeIcons:
    """Icon names and helpers."""

    REFRESH = "refresh"
    EXIT = "exit"
    CLONE_DISK = "clone_disk"
    CLONE_PARTITION = "clone_partition"
    CREATE_BACKUP = "create_backup"
    RESTORE_BACKUP = "restore_backup"
    RESCUE_MEDIA = "rescue_media"
    DANGER_MODE = "danger_mode"
    ABOUT = "about"
    CREATE_PARTITION = "create_partition"
    FORMAT_PARTITION = "format_partition"
    DELETE_PARTITION = "delete_partition"

    RIBBON_SIZE = QSize(32, 32)
    MENU_SIZE = QSize(16, 16)
    NAV_SIZE = QSize(18, 18)

    @staticmethod
    def icon(name: str) -> QIcon:
        """Return a themed icon with disabled state."""
        return _load_icon(name)


@lru_cache(maxsize=None)
def _load_icon(name: str) -> QIcon:
    icon = QIcon()
    normal_path = _ICON_DIR / f"{name}.svg"
    disabled_path = _ICON_DIR / f"{name}_disabled.svg"
    icon.addFile(str(normal_path), DiskForgeIcons.RIBBON_SIZE, QIcon.Normal, QIcon.Off)
    if disabled_path.exists():
        icon.addFile(str(disabled_path), DiskForgeIcons.RIBBON_SIZE, QIcon.Disabled, QIcon.Off)
    return icon
