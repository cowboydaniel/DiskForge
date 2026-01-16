"""
Tests for diskforge.core.models module.
"""

import pytest
from datetime import datetime

from diskforge.core.models import (
    Disk,
    DiskInventory,
    DiskType,
    FileSystem,
    ImageInfo,
    Partition,
    PartitionFlag,
    PartitionStyle,
    SMARTInfo,
)


class TestFileSystem:
    """Tests for FileSystem enum."""

    def test_from_string_exact(self) -> None:
        assert FileSystem.from_string("ext4") == FileSystem.EXT4
        assert FileSystem.from_string("ntfs") == FileSystem.NTFS
        assert FileSystem.from_string("xfs") == FileSystem.XFS

    def test_from_string_case_insensitive(self) -> None:
        assert FileSystem.from_string("EXT4") == FileSystem.EXT4
        assert FileSystem.from_string("NTFS") == FileSystem.NTFS

    def test_from_string_vfat_alias(self) -> None:
        assert FileSystem.from_string("vfat") == FileSystem.FAT32

    def test_from_string_unknown(self) -> None:
        assert FileSystem.from_string("nonexistent") == FileSystem.UNKNOWN


class TestSMARTInfo:
    """Tests for SMARTInfo."""

    def test_default_values(self) -> None:
        smart = SMARTInfo()
        assert smart.available is False
        assert smart.healthy is True

    def test_status_text_unavailable(self) -> None:
        smart = SMARTInfo(available=False)
        assert "not available" in smart.status_text.lower()

    def test_status_text_healthy(self) -> None:
        smart = SMARTInfo(available=True, healthy=True)
        assert smart.status_text == "Healthy"

    def test_status_text_warning(self) -> None:
        smart = SMARTInfo(available=True, healthy=False)
        assert "warning" in smart.status_text.lower()


class TestPartition:
    """Tests for Partition."""

    def test_basic_partition(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=2048,
            end_sector=1048575,
            size_bytes=512 * 1024 * 1024,
            filesystem=FileSystem.EXT4,
        )
        assert part.device_path == "/dev/sda1"
        assert part.number == 1

    def test_size_sectors(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=99,
            size_bytes=51200,
            filesystem=FileSystem.EXT4,
        )
        assert part.size_sectors == 100

    def test_is_boot(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=0,
            size_bytes=0,
            filesystem=FileSystem.EXT4,
            flags=[PartitionFlag.BOOT],
        )
        assert part.is_boot is True

    def test_is_boot_esp(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=0,
            size_bytes=0,
            filesystem=FileSystem.FAT32,
            flags=[PartitionFlag.ESP],
        )
        assert part.is_boot is True

    def test_is_system(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=0,
            size_bytes=0,
            filesystem=FileSystem.EXT4,
            flags=[PartitionFlag.SYSTEM],
        )
        assert part.is_system is True

    def test_to_dict(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=100,
            size_bytes=51200,
            filesystem=FileSystem.EXT4,
            label="test",
            uuid="abc-123",
        )
        data = part.to_dict()

        assert data["device_path"] == "/dev/sda1"
        assert data["number"] == 1
        assert data["filesystem"] == "ext4"
        assert data["label"] == "test"
        assert data["uuid"] == "abc-123"


class TestDisk:
    """Tests for Disk."""

    def test_basic_disk(self) -> None:
        disk = Disk(
            device_path="/dev/sda",
            model="Test Disk",
            size_bytes=1024 * 1024 * 1024,
        )
        assert disk.device_path == "/dev/sda"
        assert disk.model == "Test Disk"
        assert disk.size_bytes == 1024 * 1024 * 1024

    def test_size_sectors(self) -> None:
        disk = Disk(
            device_path="/dev/sda",
            model="Test Disk",
            size_bytes=512000,
            sector_size=512,
        )
        assert disk.size_sectors == 1000

    def test_total_partition_size(self) -> None:
        disk = Disk(
            device_path="/dev/sda",
            model="Test Disk",
            size_bytes=1024 * 1024,
            partitions=[
                Partition(
                    device_path="/dev/sda1",
                    number=1,
                    start_sector=0,
                    end_sector=0,
                    size_bytes=512 * 1024,
                    filesystem=FileSystem.EXT4,
                ),
                Partition(
                    device_path="/dev/sda2",
                    number=2,
                    start_sector=0,
                    end_sector=0,
                    size_bytes=256 * 1024,
                    filesystem=FileSystem.EXT4,
                ),
            ],
        )
        assert disk.total_partition_size == 768 * 1024

    def test_unallocated_bytes(self) -> None:
        disk = Disk(
            device_path="/dev/sda",
            model="Test Disk",
            size_bytes=1024 * 1024,
            partitions=[
                Partition(
                    device_path="/dev/sda1",
                    number=1,
                    start_sector=0,
                    end_sector=0,
                    size_bytes=512 * 1024,
                    filesystem=FileSystem.EXT4,
                ),
            ],
        )
        assert disk.unallocated_bytes == 512 * 1024

    def test_display_name(self) -> None:
        disk = Disk(
            device_path="/dev/sda",
            model="Model X",
            vendor="Vendor Y",
        )
        assert "Vendor Y" in disk.display_name
        assert "Model X" in disk.display_name

    def test_get_partition_by_number(self) -> None:
        part1 = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=0,
            size_bytes=512,
            filesystem=FileSystem.EXT4,
        )
        part2 = Partition(
            device_path="/dev/sda2",
            number=2,
            start_sector=0,
            end_sector=0,
            size_bytes=512,
            filesystem=FileSystem.EXT4,
        )
        disk = Disk(
            device_path="/dev/sda",
            model="Test",
            partitions=[part1, part2],
        )

        assert disk.get_partition_by_number(1) == part1
        assert disk.get_partition_by_number(2) == part2
        assert disk.get_partition_by_number(3) is None

    def test_to_dict(self) -> None:
        disk = Disk(
            device_path="/dev/sda",
            model="Test Disk",
            size_bytes=1024 * 1024,
            disk_type=DiskType.SSD,
            partition_style=PartitionStyle.GPT,
        )
        data = disk.to_dict()

        assert data["device_path"] == "/dev/sda"
        assert data["model"] == "Test Disk"
        assert data["disk_type"] == "SSD"
        assert data["partition_style"] == "GPT"


class TestDiskInventory:
    """Tests for DiskInventory."""

    def test_empty_inventory(self) -> None:
        inventory = DiskInventory()
        assert inventory.total_disks == 0
        assert inventory.total_partitions == 0
        assert inventory.total_capacity_bytes == 0

    def test_inventory_totals(self) -> None:
        inventory = DiskInventory(
            disks=[
                Disk(
                    device_path="/dev/sda",
                    model="Disk 1",
                    size_bytes=1000,
                    partitions=[
                        Partition(
                            device_path="/dev/sda1",
                            number=1,
                            start_sector=0,
                            end_sector=0,
                            size_bytes=500,
                            filesystem=FileSystem.EXT4,
                        ),
                    ],
                ),
                Disk(
                    device_path="/dev/sdb",
                    model="Disk 2",
                    size_bytes=2000,
                    partitions=[
                        Partition(
                            device_path="/dev/sdb1",
                            number=1,
                            start_sector=0,
                            end_sector=0,
                            size_bytes=1000,
                            filesystem=FileSystem.NTFS,
                        ),
                        Partition(
                            device_path="/dev/sdb2",
                            number=2,
                            start_sector=0,
                            end_sector=0,
                            size_bytes=500,
                            filesystem=FileSystem.NTFS,
                        ),
                    ],
                ),
            ]
        )

        assert inventory.total_disks == 2
        assert inventory.total_partitions == 3
        assert inventory.total_capacity_bytes == 3000

    def test_get_disk_by_path(self) -> None:
        disk = Disk(device_path="/dev/sda", model="Test")
        inventory = DiskInventory(disks=[disk])

        assert inventory.get_disk_by_path("/dev/sda") == disk
        assert inventory.get_disk_by_path("/dev/sdb") is None

    def test_get_partition_by_path(self) -> None:
        part = Partition(
            device_path="/dev/sda1",
            number=1,
            start_sector=0,
            end_sector=0,
            size_bytes=512,
            filesystem=FileSystem.EXT4,
        )
        disk = Disk(device_path="/dev/sda", model="Test", partitions=[part])
        inventory = DiskInventory(disks=[disk])

        result = inventory.get_partition_by_path("/dev/sda1")
        assert result is not None
        assert result[0] == disk
        assert result[1] == part

    def test_get_mounted_paths(self) -> None:
        inventory = DiskInventory(
            disks=[
                Disk(
                    device_path="/dev/sda",
                    model="Test",
                    partitions=[
                        Partition(
                            device_path="/dev/sda1",
                            number=1,
                            start_sector=0,
                            end_sector=0,
                            size_bytes=512,
                            filesystem=FileSystem.EXT4,
                            is_mounted=True,
                        ),
                        Partition(
                            device_path="/dev/sda2",
                            number=2,
                            start_sector=0,
                            end_sector=0,
                            size_bytes=512,
                            filesystem=FileSystem.EXT4,
                            is_mounted=False,
                        ),
                    ],
                ),
            ]
        )

        mounted = inventory.get_mounted_paths()
        assert "/dev/sda1" in mounted
        assert "/dev/sda2" not in mounted


class TestImageInfo:
    """Tests for ImageInfo."""

    def test_basic_image_info(self) -> None:
        info = ImageInfo(
            path="/backup/disk.img",
            source_device="/dev/sda",
            source_size_bytes=1000000,
            image_size_bytes=500000,
            compression="zstd",
        )
        assert info.path == "/backup/disk.img"
        assert info.compression == "zstd"

    def test_to_dict(self) -> None:
        info = ImageInfo(
            path="/backup/disk.img",
            source_device="/dev/sda",
            source_size_bytes=1000000,
            image_size_bytes=500000,
            compression="gzip",
            checksum="abc123",
        )
        data = info.to_dict()

        assert data["path"] == "/backup/disk.img"
        assert data["compression"] == "gzip"
        assert data["checksum"] == "abc123"
