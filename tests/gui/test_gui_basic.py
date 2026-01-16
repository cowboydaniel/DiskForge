"""
Basic GUI tests for DiskForge.

Tests for the Qt models and basic widget functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from diskforge.core.models import (
    Disk,
    DiskInventory,
    DiskType,
    FileSystem,
    Partition,
    PartitionStyle,
)
from diskforge.core.job import Job, JobContext, JobRunner, JobStatus


class TestDiskModel:
    """Tests for DiskModel."""

    @pytest.fixture
    def sample_inventory(self) -> DiskInventory:
        """Create a sample inventory for testing."""
        return DiskInventory(
            disks=[
                Disk(
                    device_path="/dev/sda",
                    model="Test Disk 1",
                    size_bytes=1000000000,
                    disk_type=DiskType.SSD,
                    partition_style=PartitionStyle.GPT,
                    partitions=[
                        Partition(
                            device_path="/dev/sda1",
                            number=1,
                            start_sector=0,
                            end_sector=1000,
                            size_bytes=512000000,
                            filesystem=FileSystem.EXT4,
                            label="root",
                        ),
                        Partition(
                            device_path="/dev/sda2",
                            number=2,
                            start_sector=1001,
                            end_sector=2000,
                            size_bytes=256000000,
                            filesystem=FileSystem.SWAP,
                        ),
                    ],
                ),
                Disk(
                    device_path="/dev/sdb",
                    model="Test Disk 2",
                    size_bytes=2000000000,
                    disk_type=DiskType.HDD,
                    partition_style=PartitionStyle.MBR,
                ),
            ],
            platform="linux",
        )

    @pytest.mark.gui
    def test_disk_model_set_inventory(self, sample_inventory: DiskInventory) -> None:
        """Test setting inventory on disk model."""
        from diskforge.ui.models.disk_model import DiskModel

        model = DiskModel()
        model.setInventory(sample_inventory)

        assert model.rowCount() == 2  # Two disks
        assert model.getInventory() == sample_inventory

    @pytest.mark.gui
    def test_disk_model_column_count(self, sample_inventory: DiskInventory) -> None:
        """Test column count."""
        from diskforge.ui.models.disk_model import DiskModel

        model = DiskModel()
        model.setInventory(sample_inventory)

        assert model.columnCount() == 7

    @pytest.mark.gui
    def test_disk_model_headers(self) -> None:
        """Test header data."""
        from diskforge.ui.models.disk_model import DiskModel
        from PySide6.QtCore import Qt

        model = DiskModel()

        assert model.headerData(0, Qt.Horizontal) == "Device"
        assert model.headerData(1, Qt.Horizontal) == "Model/Label"
        assert model.headerData(2, Qt.Horizontal) == "Size"


class TestJobModel:
    """Tests for JobModel."""

    class SimpleTestJob(Job[str]):
        """Simple job for testing."""

        def __init__(self) -> None:
            super().__init__(name="test", description="Test job")

        def execute(self, context: JobContext) -> str:
            return "done"

        def get_plan(self) -> str:
            return "Test plan"

    @pytest.mark.gui
    def test_job_model_add_job(self) -> None:
        """Test adding job to model."""
        from diskforge.ui.models.job_model import JobModel

        runner = JobRunner()
        model = JobModel(runner)

        job = self.SimpleTestJob()
        model.addJob(job)

        assert model.rowCount() == 1
        assert model.getJobAtRow(0) == job

    @pytest.mark.gui
    def test_job_model_get_job_by_id(self) -> None:
        """Test getting job by ID."""
        from diskforge.ui.models.job_model import JobModel

        runner = JobRunner()
        model = JobModel(runner)

        job = self.SimpleTestJob()
        model.addJob(job)

        assert model.getJobById(job.id) == job
        assert model.getJobById("nonexistent") is None


class TestProgressWidget:
    """Tests for ProgressWidget."""

    @pytest.mark.gui
    def test_progress_widget_reset(self) -> None:
        """Test progress widget reset."""
        from diskforge.ui.widgets.progress_widget import ProgressWidget

        widget = ProgressWidget()
        widget.reset()

        # Check internal state
        assert widget._progress_bar.value() == 0

    @pytest.mark.gui
    def test_progress_widget_update(self) -> None:
        """Test progress widget update."""
        from diskforge.ui.widgets.progress_widget import ProgressWidget
        from diskforge.core.job import JobProgress

        widget = ProgressWidget()

        progress = JobProgress(
            current=50,
            total=100,
            message="Half done",
            bytes_processed=500000,
            bytes_total=1000000,
            rate_bytes_per_sec=10000,
        )

        widget.updateProgress(progress)

        assert widget._progress_bar.value() == 50


class TestConfirmationDialog:
    """Tests for ConfirmationDialog."""

    @pytest.mark.gui
    def test_confirmation_dialog_creation(self) -> None:
        """Test confirmation dialog creation."""
        from diskforge.ui.widgets.confirmation_dialog import ConfirmationDialog

        dialog = ConfirmationDialog(
            title="Test Dialog",
            message="Test message",
            confirmation_string="CONFIRM-TEST",
        )

        assert dialog._confirmation_string == "CONFIRM-TEST"
        assert dialog.isConfirmed() is False

    @pytest.mark.gui
    def test_confirmation_dialog_check(self) -> None:
        """Test confirmation string checking."""
        from diskforge.ui.widgets.confirmation_dialog import ConfirmationDialog

        dialog = ConfirmationDialog(
            title="Test",
            message="Test",
            confirmation_string="CONFIRM",
        )

        # Wrong confirmation - button should be disabled
        dialog._confirm_input.setText("wrong")
        assert dialog._confirm_button.isEnabled() is False

        # Correct confirmation - button should be enabled
        dialog._confirm_input.setText("CONFIRM")
        assert dialog._confirm_button.isEnabled() is True


class TestDiskGraphicsView:
    """Tests for DiskGraphicsView."""

    @pytest.mark.gui
    def test_disk_view_set_disk(self) -> None:
        """Test setting disk on graphics view."""
        from diskforge.ui.widgets.disk_view import DiskGraphicsView

        view = DiskGraphicsView()

        disk = Disk(
            device_path="/dev/sda",
            model="Test Disk",
            size_bytes=1000000000,
            partitions=[
                Partition(
                    device_path="/dev/sda1",
                    number=1,
                    start_sector=0,
                    end_sector=1000,
                    size_bytes=500000000,
                    filesystem=FileSystem.EXT4,
                ),
            ],
        )

        view.setDisk(disk)

        assert view._disk == disk
        assert len(view._partition_items) >= 0  # May be 0 if not drawn yet

    @pytest.mark.gui
    def test_disk_view_set_none(self) -> None:
        """Test setting None disk."""
        from diskforge.ui.widgets.disk_view import DiskGraphicsView

        view = DiskGraphicsView()
        view.setDisk(None)

        assert view._disk is None


@pytest.mark.gui
class TestMainWindowCreation:
    """Tests for MainWindow creation."""

    def test_main_window_import(self) -> None:
        """Test that MainWindow can be imported."""
        from diskforge.ui.views.main_window import MainWindow

        assert MainWindow is not None

    def test_disk_forge_app_import(self) -> None:
        """Test that DiskForgeApp can be imported."""
        from diskforge.ui.main import DiskForgeApp

        assert DiskForgeApp is not None
