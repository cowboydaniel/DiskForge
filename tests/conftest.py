"""
Pytest configuration and fixtures for DiskForge tests.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_platform_backend() -> Mock:
    """Create a mock platform backend."""
    backend = Mock()
    backend.name = "mock"
    backend.requires_admin = True
    backend.is_admin.return_value = False

    # Mock inventory
    from diskforge.core.models import DiskInventory

    backend.get_disk_inventory.return_value = DiskInventory(platform="mock")

    return backend


@pytest.fixture
def sample_config() -> "DiskForgeConfig":
    """Create a sample configuration for testing."""
    from diskforge.core.config import DiskForgeConfig

    with tempfile.TemporaryDirectory() as tmpdir:
        config = DiskForgeConfig(
            session_directory=Path(tmpdir) / "sessions",
        )
        config.logging.log_directory = Path(tmpdir) / "logs"
        config.ensure_directories()
        yield config


@pytest.fixture
def mock_session(sample_config: "DiskForgeConfig", mock_platform_backend: Mock) -> Mock:
    """Create a mock session for testing."""
    session = Mock()
    session.id = "test-session-id"
    session.config = sample_config
    session.platform = mock_platform_backend
    session.danger_mode = Mock()

    from diskforge.core.safety import DangerMode

    session.danger_mode = DangerMode.DISABLED

    return session


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "gui: GUI tests requiring Qt")
    config.addinivalue_line("markers", "slow: Slow running tests")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Modify test collection based on available resources."""
    # Skip GUI tests if Qt is not available or if running in CI without display
    try:
        from PySide6.QtWidgets import QApplication

        # Check if display is available
        if os.environ.get("DISPLAY") is None and sys.platform != "win32":
            skip_gui = pytest.mark.skip(reason="No display available")
            for item in items:
                if "gui" in item.keywords:
                    item.add_marker(skip_gui)
    except ImportError:
        skip_gui = pytest.mark.skip(reason="PySide6 not available")
        for item in items:
            if "gui" in item.keywords:
                item.add_marker(skip_gui)


@pytest.fixture
def qapp() -> Generator["QApplication", None, None]:
    """Create a QApplication for GUI tests."""
    try:
        from PySide6.QtWidgets import QApplication

        # Check if app already exists
        app = QApplication.instance()
        if app is None:
            app = QApplication([])

        yield app

        # Don't quit the app as it may be reused
    except ImportError:
        pytest.skip("PySide6 not available")
