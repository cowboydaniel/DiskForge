"""
DiskForge Confirmation Dialog.

Dialog requiring typed confirmation for destructive operations.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class ConfirmationDialog(QDialog):
    """Dialog for confirming destructive operations."""

    def __init__(
        self,
        title: str,
        message: str,
        confirmation_string: str,
        plan_text: str | None = None,
        parent: QDialog | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(500)

        self._confirmation_string = confirmation_string
        self._confirmed = False

        self._setup_ui(message, plan_text)

    def _setup_ui(self, message: str, plan_text: str | None) -> None:
        layout = QVBoxLayout(self)

        # Warning icon and message
        warning_frame = QFrame()
        warning_frame.setStyleSheet(
            "background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 4px;"
        )
        warning_layout = QVBoxLayout(warning_frame)

        warning_label = QLabel("⚠️ " + message)
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("font-size: 14px; color: #856404;")
        warning_layout.addWidget(warning_label)

        layout.addWidget(warning_frame)

        # Plan text (if provided)
        if plan_text:
            plan_label = QLabel("Execution Plan:")
            plan_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            layout.addWidget(plan_label)

            plan_edit = QTextEdit()
            plan_edit.setReadOnly(True)
            plan_edit.setPlainText(plan_text)
            plan_edit.setMaximumHeight(200)
            font = QFont("Consolas", 9)
            plan_edit.setFont(font)
            layout.addWidget(plan_edit)

        # Confirmation input
        confirm_frame = QFrame()
        confirm_frame.setStyleSheet(
            "background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px;"
        )
        confirm_layout = QVBoxLayout(confirm_frame)

        confirm_label = QLabel(
            f"To confirm this operation, type:\n<b>{self._confirmation_string}</b>"
        )
        confirm_label.setStyleSheet("color: #721c24;")
        confirm_layout.addWidget(confirm_label)

        self._confirm_input = QLineEdit()
        self._confirm_input.setPlaceholderText("Type confirmation string here")
        self._confirm_input.textChanged.connect(self._check_confirmation)
        confirm_layout.addWidget(self._confirm_input)

        layout.addWidget(confirm_frame)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self._cancel_button)

        self._confirm_button = QPushButton("Confirm")
        self._confirm_button.setEnabled(False)
        self._confirm_button.setStyleSheet(
            "background-color: #dc3545; color: white; font-weight: bold;"
        )
        self._confirm_button.clicked.connect(self._on_confirm)
        button_layout.addWidget(self._confirm_button)

        layout.addLayout(button_layout)

    def _check_confirmation(self, text: str) -> None:
        """Check if the confirmation string matches."""
        matches = text == self._confirmation_string
        self._confirm_button.setEnabled(matches)

    def _on_confirm(self) -> None:
        """Handle confirm button click."""
        if self._confirm_input.text() == self._confirmation_string:
            self._confirmed = True
            self.accept()

    def isConfirmed(self) -> bool:
        """Check if the operation was confirmed."""
        return self._confirmed

    @staticmethod
    def confirm(
        title: str,
        message: str,
        confirmation_string: str,
        plan_text: str | None = None,
        parent: QDialog | None = None,
    ) -> bool:
        """
        Show a confirmation dialog and return whether confirmed.

        This is a convenience static method.
        """
        dialog = ConfirmationDialog(
            title=title,
            message=message,
            confirmation_string=confirmation_string,
            plan_text=plan_text,
            parent=parent,
        )
        dialog.exec()
        return dialog.isConfirmed()
