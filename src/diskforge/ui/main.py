"""
DiskForge GUI Entry Point.

Launches the PySide6 graphical user interface.
"""

from __future__ import annotations

import sys
from typing import Any

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from diskforge import __version__
from diskforge.core.config import load_config
from diskforge.core.session import Session
from diskforge.ui.views.main_window import MainWindow


class DiskForgeApp:
    """Main application class."""

    def __init__(self, args: list[str] | None = None) -> None:
        self.args = args or sys.argv
        self.app: QApplication | None = None
        self.window: MainWindow | None = None
        self.session: Session | None = None

    def run(self) -> int:
        """Run the application."""
        # Create Qt application
        self.app = QApplication(self.args)
        self.app.setApplicationName("DiskForge")
        self.app.setApplicationVersion(__version__)
        self.app.setOrganizationName("DiskForge")

        # Set application style
        self.app.setStyle("Fusion")

        try:
            # Load configuration
            config = load_config()

            # Create session
            self.session = Session(config=config)

            # Create main window
            self.window = MainWindow(self.session)
            self.window.show()

            # Run event loop
            return self.app.exec()

        except Exception as e:
            QMessageBox.critical(
                None,
                "Startup Error",
                f"Failed to start DiskForge:\n\n{e}",
            )
            return 1

        finally:
            if self.session:
                try:
                    self.session.close()
                except Exception:
                    pass


def main() -> None:
    """Main entry point for GUI."""
    app = DiskForgeApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
