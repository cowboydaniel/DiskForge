"""UI wiring tests for the DiskForge main window."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QItemSelectionModel

from diskforge.core.config import DiskForgeConfig
from diskforge.core.job import JobRunner
from diskforge.core.models import Disk, DiskInventory, DiskType, FileSystem, Partition, PartitionStyle
from diskforge.core.safety import DangerMode
from diskforge.ui.views.main_window import MainWindow


class FakePlatform:
    def __init__(self, inventory: DiskInventory) -> None:
        self.name = "linux"
        self._inventory = inventory

    def get_disk_inventory(self) -> DiskInventory:
        return self._inventory

    def is_admin(self) -> bool:
        return True


class FakeSession:
    def __init__(self, config: DiskForgeConfig, inventory: DiskInventory) -> None:
        self.config = config
        self.job_runner = JobRunner()
        self._platform_backend = FakePlatform(inventory)
        self.submitted_jobs = []

    @property
    def platform(self) -> FakePlatform:
        return self._platform_backend

    @property
    def danger_mode(self) -> DangerMode:
        return DangerMode.DISABLED

    def submit_job(self, job) -> str:  # type: ignore[no-untyped-def]
        self.submitted_jobs.append(job)
        return self.job_runner.submit(job)


def _build_inventory() -> DiskInventory:
    partition = Partition(
        device_path="/dev/sda1",
        number=1,
        start_sector=2048,
        end_sector=4095,
        size_bytes=500_000_000,
        filesystem=FileSystem.NTFS,
        label="System",
        mountpoint="/",
        is_mounted=True,
        used_space_bytes=200_000_000,
        free_space_bytes=300_000_000,
    )
    disk = Disk(
        device_path="/dev/sda",
        model="DiskForge Test",
        size_bytes=1_000_000_000,
        disk_type=DiskType.SSD,
        partition_style=PartitionStyle.GPT,
        partitions=[partition],
        is_system_disk=True,
    )
    return DiskInventory(disks=[disk])


@pytest.mark.gui
def test_main_window_selection_updates_usage(qapp, tmp_path) -> None:
    config = DiskForgeConfig()
    config.logging.log_directory = tmp_path / "logs"
    config.session_directory = tmp_path / "sessions"
    config.sync.status_file = tmp_path / "sync.json"
    config.ui.refresh_interval_ms = 60_000

    session = FakeSession(config, _build_inventory())
    window = MainWindow(session)

    disk_index = window._disk_model.index(0, 0)
    window._disk_tree.selectionModel().select(
        disk_index,
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )
    window._on_disk_selection_changed()
    assert window._selection_actions_panel._properties_button.isEnabled()
    assert window._usage_chart.usage_ratio is not None

    partition_index = window._disk_model.index(0, 0, disk_index)
    window._disk_tree.selectionModel().select(
        partition_index,
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
    )
    window._on_disk_selection_changed()
    assert window._selection_actions_panel._properties_button.isEnabled()
    assert window._usage_chart.usage_ratio is not None

    window.close()


@pytest.mark.gui
def test_bitlocker_actions_disabled_on_non_windows(qapp, tmp_path) -> None:
    config = DiskForgeConfig()
    config.logging.log_directory = tmp_path / "logs"
    config.session_directory = tmp_path / "sessions"
    config.sync.status_file = tmp_path / "sync.json"

    session = FakeSession(config, _build_inventory())
    window = MainWindow(session)

    assert not window._actions["bitlocker_status"].isEnabled()
    assert not window._actions["bitlocker_enable"].isEnabled()
    assert not window._actions["bitlocker_disable"].isEnabled()

    window.close()
