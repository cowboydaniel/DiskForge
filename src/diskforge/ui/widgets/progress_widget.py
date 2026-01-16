"""
DiskForge Progress Widget.

Displays job progress with details.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QFrame,
)
from PySide6.QtCore import Signal, Slot
import humanize

from diskforge.core.job import JobProgress


class ProgressWidget(QWidget):
    """Widget showing job progress with controls."""

    cancelRequested = Signal()
    pauseRequested = Signal()
    resumeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._is_paused = False

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Progress info frame
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.StyledPanel)
        info_layout = QVBoxLayout(info_frame)

        # Stage label
        self._stage_label = QLabel("Idle")
        self._stage_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addWidget(self._stage_label)

        # Message label
        self._message_label = QLabel("")
        info_layout.addWidget(self._message_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        info_layout.addWidget(self._progress_bar)

        # Stats row
        stats_layout = QHBoxLayout()

        self._bytes_label = QLabel("")
        stats_layout.addWidget(self._bytes_label)

        stats_layout.addStretch()

        self._rate_label = QLabel("")
        stats_layout.addWidget(self._rate_label)

        stats_layout.addStretch()

        self._eta_label = QLabel("")
        stats_layout.addWidget(self._eta_label)

        info_layout.addLayout(stats_layout)

        layout.addWidget(info_frame)

        # Control buttons
        button_layout = QHBoxLayout()

        self._pause_button = QPushButton("Pause")
        self._pause_button.clicked.connect(self._on_pause_clicked)
        self._pause_button.setEnabled(False)
        button_layout.addWidget(self._pause_button)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self.cancelRequested.emit)
        self._cancel_button.setEnabled(False)
        button_layout.addWidget(self._cancel_button)

        button_layout.addStretch()

        layout.addLayout(button_layout)

    @Slot(JobProgress)
    def updateProgress(self, progress: JobProgress) -> None:
        """Update the progress display."""
        self._progress_bar.setValue(int(progress.percentage))

        if progress.stage:
            self._stage_label.setText(progress.stage)

        if progress.message:
            self._message_label.setText(progress.message)

        # Bytes progress
        if progress.bytes_total > 0:
            processed = humanize.naturalsize(progress.bytes_processed, binary=True)
            total = humanize.naturalsize(progress.bytes_total, binary=True)
            self._bytes_label.setText(f"{processed} / {total}")
        else:
            self._bytes_label.setText("")

        # Rate
        if progress.rate_bytes_per_sec > 0:
            rate = humanize.naturalsize(progress.rate_bytes_per_sec, binary=True)
            self._rate_label.setText(f"{rate}/s")
        else:
            self._rate_label.setText("")

        # ETA
        eta = progress.eta_seconds
        if eta is not None and eta > 0:
            self._eta_label.setText(f"ETA: {humanize.naturaldelta(eta)}")
        else:
            self._eta_label.setText("")

    def setRunning(self, running: bool) -> None:
        """Set whether a job is running."""
        self._pause_button.setEnabled(running)
        self._cancel_button.setEnabled(running)

        if not running:
            self._is_paused = False
            self._pause_button.setText("Pause")

    def reset(self) -> None:
        """Reset the progress display."""
        self._progress_bar.setValue(0)
        self._stage_label.setText("Idle")
        self._message_label.setText("")
        self._bytes_label.setText("")
        self._rate_label.setText("")
        self._eta_label.setText("")
        self._is_paused = False
        self._pause_button.setText("Pause")
        self.setRunning(False)

    def _on_pause_clicked(self) -> None:
        """Handle pause/resume button click."""
        if self._is_paused:
            self._is_paused = False
            self._pause_button.setText("Pause")
            self.resumeRequested.emit()
        else:
            self._is_paused = True
            self._pause_button.setText("Resume")
            self.pauseRequested.emit()
