"""
DiskForge Job Model.

Qt model for displaying and tracking jobs.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QTimer
from PySide6.QtGui import QColor, QBrush

from diskforge.core.job import Job, JobRunner, JobStatus, JobProgress


class JobModel(QAbstractTableModel):
    """Qt model for job queue display."""

    jobStatusChanged = Signal(str, JobStatus)
    jobProgressChanged = Signal(str, JobProgress)

    HEADERS = ["ID", "Name", "Status", "Progress", "Duration"]

    def __init__(self, job_runner: JobRunner, parent: Any = None) -> None:
        super().__init__(parent)
        self._job_runner = job_runner
        self._jobs: list[Job[Any]] = []
        self._job_order: list[str] = []

        # Set up job runner callbacks
        self._job_runner.add_status_callback(self._on_status_change)

        # Refresh timer for progress updates
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_progress)
        self._refresh_timer.start(500)  # 500ms refresh

    def addJob(self, job: Job[Any]) -> None:
        """Add a job to the model."""
        self.beginInsertRows(QModelIndex(), len(self._jobs), len(self._jobs))
        self._jobs.append(job)
        self._job_order.append(job.id)
        self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._jobs)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._jobs):
            return None

        job = self._jobs[index.row()]

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return job.id[:8]
            elif index.column() == 1:
                return job.name
            elif index.column() == 2:
                return job.status.name
            elif index.column() == 3:
                progress = job.context.get_progress()
                return f"{progress.percentage:.0f}%"
            elif index.column() == 4:
                if job.result and job.result.duration_seconds:
                    return f"{job.result.duration_seconds:.1f}s"
                return ""

        if role == Qt.BackgroundRole:
            status_colors = {
                JobStatus.PENDING: QColor(200, 200, 200),
                JobStatus.RUNNING: QColor(200, 200, 255),
                JobStatus.PAUSED: QColor(255, 255, 200),
                JobStatus.COMPLETED: QColor(200, 255, 200),
                JobStatus.FAILED: QColor(255, 200, 200),
                JobStatus.CANCELLED: QColor(255, 220, 200),
            }
            return QBrush(status_colors.get(job.status, QColor(255, 255, 255)))

        if role == Qt.UserRole:
            return job

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section] if section < len(self.HEADERS) else None
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def getJobAtRow(self, row: int) -> Job[Any] | None:
        """Get job at the specified row."""
        if 0 <= row < len(self._jobs):
            return self._jobs[row]
        return None

    def getJobById(self, job_id: str) -> Job[Any] | None:
        """Get job by ID."""
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def _on_status_change(self, job_id: str, status: JobStatus) -> None:
        """Handle job status changes."""
        for i, job in enumerate(self._jobs):
            if job.id == job_id:
                index = self.createIndex(i, 2)
                self.dataChanged.emit(index, index)
                self.jobStatusChanged.emit(job_id, status)
                break

    def _refresh_progress(self) -> None:
        """Refresh progress display for running jobs."""
        for i, job in enumerate(self._jobs):
            if job.status == JobStatus.RUNNING:
                index = self.createIndex(i, 3)
                self.dataChanged.emit(index, index)
                self.jobProgressChanged.emit(job.id, job.context.get_progress())

    def clearCompleted(self) -> None:
        """Remove completed jobs from the model."""
        completed_indices = [
            i
            for i, job in enumerate(self._jobs)
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]

        # Remove in reverse order to maintain indices
        for i in reversed(completed_indices):
            self.beginRemoveRows(QModelIndex(), i, i)
            del self._jobs[i]
            del self._job_order[i]
            self.endRemoveRows()


class PendingOperationsModel(QAbstractTableModel):
    """Qt model for pending operations list."""

    pendingCountChanged = Signal(int)

    HEADERS = ["Operation", "Details"]

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._pending_jobs: list[Job[Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._pending_jobs)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._pending_jobs):
            return None

        job = self._pending_jobs[index.row()]

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return job.name
            if index.column() == 1:
                plan = job.get_plan()
                return plan if plan else job.description

        if role == Qt.UserRole:
            return job

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section] if section < len(self.HEADERS) else None
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def pendingCount(self) -> int:
        """Return the number of pending operations."""
        return len(self._pending_jobs)

    def addOperation(self, job: Job[Any]) -> None:
        """Add a job to the pending operations list."""
        row = len(self._pending_jobs)
        self.beginInsertRows(QModelIndex(), row, row)
        self._pending_jobs.append(job)
        self.endInsertRows()
        self.pendingCountChanged.emit(len(self._pending_jobs))

    def getOperationAtRow(self, row: int) -> Job[Any] | None:
        """Get pending operation at the specified row."""
        if 0 <= row < len(self._pending_jobs):
            return self._pending_jobs[row]
        return None

    def removeOperation(self, row: int) -> Job[Any] | None:
        """Remove a pending operation by row."""
        if row < 0 or row >= len(self._pending_jobs):
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        job = self._pending_jobs.pop(row)
        self.endRemoveRows()
        self.pendingCountChanged.emit(len(self._pending_jobs))
        return job

    def undoLastOperation(self) -> Job[Any] | None:
        """Undo the most recently added pending operation."""
        if not self._pending_jobs:
            return None
        return self.removeOperation(len(self._pending_jobs) - 1)

    def clearOperations(self) -> None:
        """Clear all pending operations."""
        if not self._pending_jobs:
            return
        self.beginResetModel()
        self._pending_jobs.clear()
        self.endResetModel()
        self.pendingCountChanged.emit(len(self._pending_jobs))

    def takeOperations(self) -> list[Job[Any]]:
        """Remove and return all pending operations."""
        if not self._pending_jobs:
            return []
        self.beginResetModel()
        jobs = list(self._pending_jobs)
        self._pending_jobs.clear()
        self.endResetModel()
        self.pendingCountChanged.emit(0)
        return jobs
