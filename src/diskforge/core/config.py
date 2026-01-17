"""
DiskForge configuration management.

Provides centralized configuration with validation using Pydantic.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoggingConfig(BaseModel):
    """Configuration for structured logging."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    file_enabled: bool = True
    console_enabled: bool = True
    json_format: bool = False
    log_directory: Path = Field(default_factory=lambda: Path.home() / ".diskforge" / "logs")

    @field_validator("log_directory", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()


class SafetyConfig(BaseModel):
    """Configuration for safety features."""

    danger_mode_enabled: bool = False
    require_confirmation: bool = True
    confirmation_timeout_seconds: int = 300
    preflight_checks_enabled: bool = True
    dry_run_default: bool = True
    smart_check_enabled: bool = True
    mounted_volume_protection: bool = True
    system_disk_protection: bool = True


class BackupConfig(BaseModel):
    """Configuration for backup operations."""

    default_compression: Literal["none", "gzip", "lz4", "zstd"] = "zstd"
    compression_level: int = Field(default=3, ge=1, le=22)
    verify_after_write: bool = True
    chunk_size_mb: int = Field(default=64, ge=1, le=1024)
    temp_directory: Path | None = None


class SystemBackupConfig(BaseModel):
    """Configuration for system-level backups."""

    include_recovery_partitions: bool = True
    include_swap_partitions: bool = False
    include_hidden_partitions: bool = True
    include_reserved_partitions: bool = True
    required_mountpoints: list[str] = Field(default_factory=lambda: ["/", "/boot", "/boot/efi"])
    capture_partition_table: bool = True
    capture_boot_metadata: bool = True


class UIConfig(BaseModel):
    """Configuration for the GUI."""

    theme: Literal["system", "light", "dark"] = "system"
    refresh_interval_ms: int = Field(default=5000, ge=1000, le=60000)
    show_hidden_partitions: bool = False
    confirm_dialog_timeout_seconds: int = 30


class DiskForgeConfig(BaseModel):
    """Main DiskForge configuration."""

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    system_backup: SystemBackupConfig = Field(default_factory=SystemBackupConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    session_directory: Path = Field(default_factory=lambda: Path.home() / ".diskforge" / "sessions")
    plugin_directories: list[Path] = Field(default_factory=list)

    @field_validator("session_directory", mode="before")
    @classmethod
    def expand_session_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()

    @classmethod
    def load(cls, config_path: Path | None = None) -> DiskForgeConfig:
        """Load configuration from file or create default."""
        if config_path is None:
            config_path = Path.home() / ".diskforge" / "config.json"

        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
            return cls.model_validate(data)

        return cls()

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to file."""
        if config_path is None:
            config_path = Path.home() / ".diskforge" / "config.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2, default=str)

    def ensure_directories(self) -> None:
        """Create all required directories."""
        self.logging.log_directory.mkdir(parents=True, exist_ok=True)
        self.session_directory.mkdir(parents=True, exist_ok=True)
        if self.backup.temp_directory:
            self.backup.temp_directory.mkdir(parents=True, exist_ok=True)

    def get_session_file(self) -> Path:
        """Get path for a new session report file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.session_directory / f"session_{timestamp}.json"


def get_default_config() -> DiskForgeConfig:
    """Get the default configuration."""
    return DiskForgeConfig()


def load_config(config_path: Path | None = None) -> DiskForgeConfig:
    """Load or create configuration."""
    config = DiskForgeConfig.load(config_path)
    config.ensure_directories()
    return config
