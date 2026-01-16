"""
DiskForge Plugin System Base.

Provides the foundation for creating and managing plugins.
"""

from __future__ import annotations

import importlib.util
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from diskforge.core.logging import get_logger

if TYPE_CHECKING:
    from diskforge.core.job import Job
    from diskforge.core.session import Session

logger = get_logger(__name__)


@dataclass
class PluginMetadata:
    """Metadata for a plugin."""

    name: str
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    requires_admin: bool = False
    platforms: list[str] = field(default_factory=lambda: ["linux", "windows"])
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Base class for all DiskForge plugins."""

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""

    @abstractmethod
    def initialize(self, session: Session) -> None:
        """
        Initialize the plugin.

        Called when the plugin is loaded. Use this to register
        commands, jobs, and UI components.
        """

    def shutdown(self) -> None:
        """
        Shutdown the plugin.

        Called when the plugin is unloaded. Use this for cleanup.
        """

    def is_available(self) -> tuple[bool, str]:
        """
        Check if the plugin is available on the current platform.

        Returns (available, reason).
        """
        from diskforge.platform import get_platform_name

        current_platform = get_platform_name()
        if current_platform in self.metadata.platforms:
            return True, "Plugin available"
        return False, f"Plugin not available on {current_platform}"


class PluginRegistry:
    """
    Registry for plugin features.

    Plugins register their features here for discovery by the UI and CLI.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, type[Job[Any]]] = {}
        self._commands: dict[str, Callable[..., Any]] = {}
        self._menu_items: list[dict[str, Any]] = []
        self._validators: dict[str, Callable[..., list[str]]] = {}

    def register_job(self, name: str, job_class: type[Job[Any]]) -> None:
        """Register a job type."""
        logger.debug("Registering job", name=name, job_class=job_class.__name__)
        self._jobs[name] = job_class

    def register_command(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str = "",
    ) -> None:
        """Register a CLI command."""
        logger.debug("Registering command", name=name)
        self._commands[name] = handler

    def register_menu_item(
        self,
        menu: str,
        label: str,
        action: Callable[..., Any],
        icon: str | None = None,
    ) -> None:
        """Register a UI menu item."""
        self._menu_items.append(
            {
                "menu": menu,
                "label": label,
                "action": action,
                "icon": icon,
            }
        )

    def register_validator(
        self,
        operation: str,
        validator: Callable[..., list[str]],
    ) -> None:
        """Register a validator for an operation."""
        self._validators[operation] = validator

    def get_job(self, name: str) -> type[Job[Any]] | None:
        """Get a registered job class."""
        return self._jobs.get(name)

    def get_command(self, name: str) -> Callable[..., Any] | None:
        """Get a registered command handler."""
        return self._commands.get(name)

    def get_menu_items(self, menu: str | None = None) -> list[dict[str, Any]]:
        """Get registered menu items."""
        if menu is None:
            return self._menu_items.copy()
        return [item for item in self._menu_items if item["menu"] == menu]

    def get_validator(self, operation: str) -> Callable[..., list[str]] | None:
        """Get a registered validator."""
        return self._validators.get(operation)

    def list_jobs(self) -> list[str]:
        """List all registered job names."""
        return list(self._jobs.keys())

    def list_commands(self) -> list[str]:
        """List all registered command names."""
        return list(self._commands.keys())


class PluginManager:
    """Manages plugin lifecycle and discovery."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = PluginRegistry()
        self._plugins: dict[str, Plugin] = {}
        self._loaded_paths: set[Path] = set()

    def load_plugin(self, plugin: Plugin) -> bool:
        """Load and initialize a plugin."""
        metadata = plugin.metadata

        # Check availability
        available, reason = plugin.is_available()
        if not available:
            logger.warning(
                "Plugin not available",
                plugin=metadata.name,
                reason=reason,
            )
            return False

        # Check if already loaded
        if metadata.name in self._plugins:
            logger.warning("Plugin already loaded", plugin=metadata.name)
            return False

        # Check dependencies
        for dep in metadata.dependencies:
            if dep not in self._plugins:
                logger.error(
                    "Plugin dependency not loaded",
                    plugin=metadata.name,
                    dependency=dep,
                )
                return False

        try:
            plugin.initialize(self.session)
            self._plugins[metadata.name] = plugin
            logger.info(
                "Plugin loaded",
                plugin=metadata.name,
                version=metadata.version,
            )
            return True
        except Exception as e:
            logger.error(
                "Failed to load plugin",
                plugin=metadata.name,
                error=str(e),
            )
            return False

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return False

        try:
            plugin.shutdown()
            del self._plugins[name]
            logger.info("Plugin unloaded", plugin=name)
            return True
        except Exception as e:
            logger.error(
                "Failed to unload plugin",
                plugin=name,
                error=str(e),
            )
            return False

    def load_from_path(self, path: Path) -> int:
        """
        Load plugins from a directory path.

        Returns number of plugins loaded.
        """
        if not path.exists() or not path.is_dir():
            logger.warning("Plugin path not found", path=str(path))
            return 0

        if path in self._loaded_paths:
            return 0

        self._loaded_paths.add(path)
        loaded = 0

        for plugin_file in path.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"diskforge_plugin_{plugin_file.stem}",
                    plugin_file,
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)

                # Look for Plugin subclass
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Plugin)
                        and attr is not Plugin
                    ):
                        plugin = attr()
                        if self.load_plugin(plugin):
                            loaded += 1

            except Exception as e:
                logger.error(
                    "Failed to load plugin file",
                    path=str(plugin_file),
                    error=str(e),
                )

        return loaded

    def get_plugin(self, name: str) -> Plugin | None:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginMetadata]:
        """List all loaded plugins."""
        return [p.metadata for p in self._plugins.values()]

    def shutdown_all(self) -> None:
        """Shutdown all plugins."""
        for name in list(self._plugins.keys()):
            self.unload_plugin(name)
