"""
DiskForge Inventory Plugin.

Provides disk inventory and information jobs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from diskforge.core.job import Job, JobContext
from diskforge.core.models import DiskInventory
from diskforge.core.safety import OperationType
from diskforge.plugins.base import Plugin, PluginMetadata, PluginRegistry

if TYPE_CHECKING:
    from diskforge.core.session import Session


class InventoryJob(Job[DiskInventory]):
    """Job to retrieve disk inventory."""

    operation_type = OperationType.READ_ONLY

    def __init__(self, include_smart: bool = False) -> None:
        super().__init__(
            name="disk_inventory",
            description="Retrieve disk and partition inventory",
        )
        self.include_smart = include_smart
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        """Set the session for platform access."""
        self._session = session

    def execute(self, context: JobContext) -> DiskInventory:
        """Execute the inventory job."""
        context.update_progress(message="Scanning disk inventory...")

        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform
        inventory = platform.get_disk_inventory()

        if self.include_smart:
            context.update_progress(message="Retrieving SMART data...")
            for disk in inventory.disks:
                smart_info = platform.get_smart_info(disk.device_path)
                if smart_info:
                    from diskforge.core.models import SMARTInfo

                    disk.smart_info = SMARTInfo(
                        available=True,
                        healthy=smart_info.get("Status") != "Error",
                        raw_data=smart_info,
                    )

        context.update_progress(
            current=100,
            message=f"Found {inventory.total_disks} disks, {inventory.total_partitions} partitions",
        )

        return inventory

    def get_plan(self) -> str:
        """Return execution plan."""
        lines = [
            "Disk Inventory Scan",
            "==================",
            "This operation will scan all disk devices.",
            "",
            "Steps:",
            "1. Query system for block devices",
            "2. Retrieve partition information",
            "3. Query filesystem details",
        ]
        if self.include_smart:
            lines.append("4. Query SMART health data")
        lines.extend(["", "This is a read-only operation."])
        return "\n".join(lines)


class DiskInfoJob(Job[dict]):
    """Job to get detailed information about a specific disk."""

    operation_type = OperationType.READ_ONLY

    def __init__(self, device_path: str, include_smart: bool = True) -> None:
        super().__init__(
            name="disk_info",
            description=f"Get detailed information for {device_path}",
        )
        self.device_path = device_path
        self.include_smart = include_smart
        self._session: Session | None = None

    def set_session(self, session: Session) -> None:
        """Set the session for platform access."""
        self._session = session

    def execute(self, context: JobContext) -> dict:
        """Execute the disk info job."""
        context.update_progress(message=f"Querying {self.device_path}...")

        if self._session is None:
            raise RuntimeError("Session not set")

        platform = self._session.platform
        disk = platform.get_disk_info(self.device_path)

        if disk is None:
            raise ValueError(f"Disk not found: {self.device_path}")

        result = disk.to_dict()

        if self.include_smart:
            context.update_progress(message="Querying SMART data...")
            smart_info = platform.get_smart_info(self.device_path)
            if smart_info:
                result["smart"] = smart_info

        return result

    def get_plan(self) -> str:
        """Return execution plan."""
        return f"""Disk Information Query
=====================
Target: {self.device_path}

Steps:
1. Query disk properties
2. Retrieve partition list
{"3. Query SMART data" if self.include_smart else ""}

This is a read-only operation."""


class InventoryPlugin(Plugin):
    """Plugin providing disk inventory features."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="inventory",
            version="1.0.0",
            description="Disk inventory and information features",
            author="DiskForge Team",
            tags=["core", "inventory"],
        )

    def initialize(self, session: Session) -> None:
        """Initialize the inventory plugin."""
        # Register with plugin registry if available
        if hasattr(session, "plugin_manager"):
            registry = session.plugin_manager.registry
            registry.register_job("inventory", InventoryJob)
            registry.register_job("disk_info", DiskInfoJob)

            # Register CLI commands
            registry.register_command(
                "list-disks",
                self._cmd_list_disks,
                "List all disks",
            )
            registry.register_command(
                "disk-info",
                self._cmd_disk_info,
                "Show disk details",
            )

    def _cmd_list_disks(self, session: Session, include_smart: bool = False) -> DiskInventory:
        """CLI command to list disks."""
        job = InventoryJob(include_smart=include_smart)
        job.set_session(session)
        result = session.run_job(job)
        if result.success and result.data:
            return result.data
        raise RuntimeError(result.error or "Failed to get inventory")

    def _cmd_disk_info(self, session: Session, device_path: str) -> dict:
        """CLI command to get disk info."""
        job = DiskInfoJob(device_path)
        job.set_session(session)
        result = session.run_job(job)
        if result.success and result.data:
            return result.data
        raise RuntimeError(result.error or "Failed to get disk info")
