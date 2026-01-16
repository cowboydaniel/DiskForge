"""
Tests for diskforge.platform.linux module.

Uses mocking to test without requiring admin privileges.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from diskforge.core.models import DiskType, FileSystem, PartitionStyle
from diskforge.platform.base import CommandResult
from diskforge.platform.linux.parsers import (
    parse_lsblk_json,
    parse_blkid_output,
    parse_partition_style,
    parse_disk_type,
    build_disk_from_lsblk,
)


class TestLinuxParsers:
    """Tests for Linux output parsers."""

    def test_parse_lsblk_json_valid(self) -> None:
        output = json.dumps(
            {
                "blockdevices": [
                    {"name": "sda", "size": 1000000, "type": "disk"},
                    {"name": "sdb", "size": 2000000, "type": "disk"},
                ]
            }
        )
        result = parse_lsblk_json(output)
        assert len(result) == 2
        assert result[0]["name"] == "sda"

    def test_parse_lsblk_json_empty(self) -> None:
        result = parse_lsblk_json("")
        assert result == []

    def test_parse_lsblk_json_invalid(self) -> None:
        result = parse_lsblk_json("not json")
        assert result == []

    def test_parse_blkid_output(self) -> None:
        output = '/dev/sda1: UUID="abc-123" TYPE="ext4" PARTUUID="xyz-789"'
        result = parse_blkid_output(output)

        assert "/dev/sda1" in result
        assert result["/dev/sda1"]["UUID"] == "abc-123"
        assert result["/dev/sda1"]["TYPE"] == "ext4"

    def test_parse_blkid_output_multiple(self) -> None:
        output = """/dev/sda1: UUID="abc" TYPE="ext4"
/dev/sda2: UUID="def" TYPE="xfs"
/dev/sdb1: UUID="ghi" TYPE="ntfs\""""
        result = parse_blkid_output(output)

        assert len(result) == 3
        assert result["/dev/sda1"]["TYPE"] == "ext4"
        assert result["/dev/sda2"]["TYPE"] == "xfs"

    def test_parse_partition_style_gpt(self) -> None:
        assert parse_partition_style("gpt") == PartitionStyle.GPT
        assert parse_partition_style("GPT") == PartitionStyle.GPT

    def test_parse_partition_style_mbr(self) -> None:
        assert parse_partition_style("dos") == PartitionStyle.MBR
        assert parse_partition_style("mbr") == PartitionStyle.MBR
        assert parse_partition_style("msdos") == PartitionStyle.MBR

    def test_parse_partition_style_unknown(self) -> None:
        assert parse_partition_style(None) == PartitionStyle.UNKNOWN
        assert parse_partition_style("unknown") == PartitionStyle.UNKNOWN

    def test_parse_disk_type_nvme(self) -> None:
        assert parse_disk_type("nvme", None, "/dev/nvme0n1") == DiskType.NVME
        assert parse_disk_type(None, None, "/dev/nvme0n1") == DiskType.NVME

    def test_parse_disk_type_usb(self) -> None:
        assert parse_disk_type("usb", None, "/dev/sda") == DiskType.USB

    def test_parse_disk_type_ssd(self) -> None:
        assert parse_disk_type("sata", "0", "/dev/sda") == DiskType.SSD

    def test_parse_disk_type_hdd(self) -> None:
        assert parse_disk_type("sata", "1", "/dev/sda") == DiskType.HDD

    def test_parse_disk_type_loop(self) -> None:
        assert parse_disk_type(None, None, "/dev/loop0") == DiskType.LOOP

    def test_parse_disk_type_raid(self) -> None:
        assert parse_disk_type(None, None, "/dev/md0") == DiskType.RAID


class TestBuildDiskFromLsblk:
    """Tests for build_disk_from_lsblk function."""

    def test_build_disk_basic(self) -> None:
        block = {
            "name": "sda",
            "path": "/dev/sda",
            "size": 1000000000,
            "type": "disk",
            "model": "Test Disk",
            "serial": "ABC123",
            "tran": "sata",
            "rota": "0",
            "pttype": "gpt",
            "children": [],
        }

        disk = build_disk_from_lsblk(block, {}, {}, set())

        assert disk.device_path == "/dev/sda"
        assert disk.model == "Test Disk"
        assert disk.serial == "ABC123"
        assert disk.size_bytes == 1000000000
        assert disk.disk_type == DiskType.SSD
        assert disk.partition_style == PartitionStyle.GPT

    def test_build_disk_with_partitions(self) -> None:
        block = {
            "name": "sda",
            "path": "/dev/sda",
            "size": 1000000000,
            "type": "disk",
            "model": "Test Disk",
            "pttype": "gpt",
            "children": [
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "size": 500000000,
                    "type": "part",
                    "fstype": "ext4",
                    "label": "root",
                    "uuid": "abc-123",
                },
                {
                    "name": "sda2",
                    "path": "/dev/sda2",
                    "size": 500000000,
                    "type": "part",
                    "fstype": "xfs",
                },
            ],
        }

        disk = build_disk_from_lsblk(block, {}, {}, set())

        assert len(disk.partitions) == 2
        assert disk.partitions[0].filesystem == FileSystem.EXT4
        assert disk.partitions[0].label == "root"
        assert disk.partitions[1].filesystem == FileSystem.XFS

    def test_build_disk_system_disk(self) -> None:
        block = {
            "name": "sda",
            "path": "/dev/sda",
            "size": 1000000000,
            "type": "disk",
            "model": "Test Disk",
            "children": [],
        }

        disk = build_disk_from_lsblk(block, {}, {}, {"/dev/sda"})

        assert disk.is_system_disk is True


@pytest.mark.integration
class TestLinuxBackend:
    """Tests for LinuxBackend with mocked commands."""

    @pytest.fixture
    def mock_backend(self) -> Mock:
        """Create a LinuxBackend with mocked command execution."""
        with patch("diskforge.platform.linux.backend.LinuxBackend") as MockBackend:
            backend = MockBackend.return_value
            backend.name = "linux"
            backend.requires_admin = True

            yield backend

    def test_get_disk_inventory_mocked(self, mock_backend: Mock) -> None:
        """Test inventory with mocked lsblk output."""
        from diskforge.platform.linux.backend import LinuxBackend

        backend = LinuxBackend()

        # Mock run_command to return test data
        lsblk_output = json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "sda",
                        "path": "/dev/sda",
                        "size": 1000000000,
                        "type": "disk",
                        "model": "Test Disk",
                        "pttype": "gpt",
                        "children": [
                            {
                                "name": "sda1",
                                "path": "/dev/sda1",
                                "size": 500000000,
                                "type": "part",
                                "fstype": "ext4",
                            }
                        ],
                    }
                ]
            }
        )

        with patch.object(backend, "run_command") as mock_run:
            mock_run.side_effect = [
                CommandResult(0, lsblk_output, "", ["lsblk"]),
                CommandResult(0, "", "", ["blkid"]),
            ]

            with patch.object(backend, "_get_mounts", return_value={}):
                with patch.object(backend, "_get_system_devices", return_value=set()):
                    inventory = backend.get_disk_inventory()

        assert len(inventory.disks) == 1
        assert inventory.disks[0].model == "Test Disk"
        assert len(inventory.disks[0].partitions) == 1

    def test_validate_device_path(self) -> None:
        """Test device path validation."""
        from diskforge.platform.linux.backend import LinuxBackend

        backend = LinuxBackend()

        # Invalid path (not starting with /dev/)
        valid, msg = backend.validate_device_path("/tmp/file")
        assert valid is False
        assert "/dev/" in msg

        # Path doesn't exist (mocked)
        with patch("os.path.exists", return_value=False):
            valid, msg = backend.validate_device_path("/dev/nonexistent")
            assert valid is False

    def test_format_partition_dry_run(self) -> None:
        """Test format partition in dry run mode."""
        from diskforge.platform.linux.backend import LinuxBackend
        from diskforge.core.models import FormatOptions, FileSystem

        backend = LinuxBackend()

        options = FormatOptions(
            partition_path="/dev/sda1",
            filesystem=FileSystem.EXT4,
            label="test",
        )

        # Mock partition info
        with patch.object(backend, "get_partition_info") as mock_info:
            mock_part = Mock()
            mock_part.is_mounted = False
            mock_info.return_value = mock_part

            with patch.object(backend, "_check_tool", return_value=True):
                success, message = backend.format_partition(options, dry_run=True)

        assert success is True
        assert "Would run" in message

    def test_clone_disk_dry_run(self) -> None:
        """Test clone disk in dry run mode."""
        from diskforge.platform.linux.backend import LinuxBackend
        from diskforge.core.models import Disk

        backend = LinuxBackend()

        # Mock disk info
        with patch.object(backend, "get_disk_info") as mock_info:
            source_disk = Mock()
            source_disk.size_bytes = 1000000
            source_disk.is_system_disk = False
            source_disk.partitions = []

            target_disk = Mock()
            target_disk.size_bytes = 2000000
            target_disk.is_system_disk = False
            target_disk.partitions = []

            mock_info.side_effect = [source_disk, target_disk]

            success, message = backend.clone_disk(
                "/dev/sda", "/dev/sdb", dry_run=True
            )

        assert success is True
        assert "Would clone" in message

    def test_create_image_dry_run(self) -> None:
        """Test create image in dry run mode."""
        from diskforge.platform.linux.backend import LinuxBackend
        from pathlib import Path

        backend = LinuxBackend()

        # Mock source info
        with patch.object(backend, "get_disk_info") as mock_info:
            source = Mock()
            source.size_bytes = 1000000
            mock_info.return_value = source

            success, message, info = backend.create_image(
                "/dev/sda",
                Path("/tmp/test.img"),
                compression="zstd",
                dry_run=True,
            )

        assert success is True
        assert "Would create image" in message
