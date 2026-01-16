"""
Tests for diskforge.core.config module.
"""

import json
import tempfile
from pathlib import Path

import pytest

from diskforge.core.config import (
    DiskForgeConfig,
    LoggingConfig,
    SafetyConfig,
    BackupConfig,
    UIConfig,
    load_config,
)


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_default_values(self) -> None:
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.file_enabled is True
        assert config.console_enabled is True
        assert config.json_format is False

    def test_custom_values(self) -> None:
        config = LoggingConfig(level="DEBUG", json_format=True)
        assert config.level == "DEBUG"
        assert config.json_format is True

    def test_path_expansion(self) -> None:
        config = LoggingConfig(log_directory="~/logs")
        assert "~" not in str(config.log_directory)


class TestSafetyConfig:
    """Tests for SafetyConfig."""

    def test_default_values(self) -> None:
        config = SafetyConfig()
        assert config.danger_mode_enabled is False
        assert config.require_confirmation is True
        assert config.preflight_checks_enabled is True
        assert config.dry_run_default is True
        assert config.system_disk_protection is True

    def test_custom_values(self) -> None:
        config = SafetyConfig(danger_mode_enabled=True, dry_run_default=False)
        assert config.danger_mode_enabled is True
        assert config.dry_run_default is False


class TestBackupConfig:
    """Tests for BackupConfig."""

    def test_default_compression(self) -> None:
        config = BackupConfig()
        assert config.default_compression == "zstd"
        assert config.compression_level == 3
        assert config.verify_after_write is True

    def test_compression_level_bounds(self) -> None:
        config = BackupConfig(compression_level=1)
        assert config.compression_level == 1

        config = BackupConfig(compression_level=22)
        assert config.compression_level == 22

    def test_chunk_size_bounds(self) -> None:
        config = BackupConfig(chunk_size_mb=1)
        assert config.chunk_size_mb == 1

        config = BackupConfig(chunk_size_mb=1024)
        assert config.chunk_size_mb == 1024


class TestUIConfig:
    """Tests for UIConfig."""

    def test_default_values(self) -> None:
        config = UIConfig()
        assert config.theme == "system"
        assert config.refresh_interval_ms == 5000
        assert config.show_hidden_partitions is False


class TestDiskForgeConfig:
    """Tests for DiskForgeConfig."""

    def test_default_config(self) -> None:
        config = DiskForgeConfig()
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.safety, SafetyConfig)
        assert isinstance(config.backup, BackupConfig)
        assert isinstance(config.ui, UIConfig)

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create and save config
            original = DiskForgeConfig(
                safety=SafetyConfig(dry_run_default=False),
                backup=BackupConfig(compression_level=10),
            )
            original.save(config_path)

            # Load config
            loaded = DiskForgeConfig.load(config_path)

            assert loaded.safety.dry_run_default is False
            assert loaded.backup.compression_level == 10

    def test_load_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nonexistent.json"
            config = DiskForgeConfig.load(config_path)
            # Should return default config
            assert config.safety.dry_run_default is True

    def test_ensure_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DiskForgeConfig(
                logging=LoggingConfig(log_directory=Path(tmpdir) / "logs"),
                session_directory=Path(tmpdir) / "sessions",
            )
            config.ensure_directories()

            assert config.logging.log_directory.exists()
            assert config.session_directory.exists()

    def test_get_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DiskForgeConfig(session_directory=Path(tmpdir))
            session_file = config.get_session_file()
            assert str(session_file).startswith(tmpdir)
            assert "session_" in str(session_file)
            assert session_file.suffix == ".json"
