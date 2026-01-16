"""
DiskForge Plugin System.

Provides an extensible plugin architecture for adding new features
and operations to DiskForge.
"""

from diskforge.plugins.base import (
    Plugin,
    PluginMetadata,
    PluginRegistry,
    PluginManager,
)

__all__ = [
    "Plugin",
    "PluginMetadata",
    "PluginRegistry",
    "PluginManager",
]
