"""
DiskForge - Production-grade cross-platform disk management application.

A comprehensive disk management tool providing partition management,
disk cloning, image backup/restore, and bootable rescue media creation.
"""

__version__ = "1.0.0"
__author__ = "DiskForge Team"

from diskforge.core.config import DiskForgeConfig
from diskforge.core.session import Session

__all__ = ["DiskForgeConfig", "Session", "__version__"]
