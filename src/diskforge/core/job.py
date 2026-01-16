"""
DiskForge Job Runner.

Provides a robust job execution system with progress tracking,
cancellation support, and proper error handling.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from diskforge.core.logging import get_logger

T = TypeVar("T")
logger = get_logger(__name__)


class JobStatus(Enum):
    """Status of a job execution."""

    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class JobPriority(Enum):
    """Job priority levels."""

    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


@dataclass
class JobProgress:
    """Progress information for a running job."""

    current: int = 0
    total: int = 100
    message: str = ""
    stage: str = ""
    bytes_processed: int = 0
    bytes_total: int = 0
    rate_bytes_per_sec: float = 0.0

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100)

    @property
    def eta_seconds(self) -> float | None:
        if self.rate_bytes_per_sec <= 0 or self.bytes_total == 0:
            return None
        remaining = self.bytes_total - self.bytes_processed
        return remaining / self.rate_bytes_per_sec


@dataclass
class JobResult(Generic[T]):
    """Result of a completed job."""

    success: bool
    data: T | None = None
    error: str | None = None
    error_traceback: str | None = None
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class JobContext:
    """Context passed to job execution for progress and cancellation."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._paused = threading.Event()
        self._progress = JobProgress()
        self._progress_callbacks: list[Callable[[JobProgress], None]] = []
        self._lock = threading.Lock()
        self._warnings: list[str] = []

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def cancel(self) -> None:
        """Request cancellation of the job."""
        self._cancelled.set()

    def pause(self) -> None:
        """Pause the job."""
        self._paused.set()

    def resume(self) -> None:
        """Resume a paused job."""
        self._paused.clear()

    def check_cancelled(self) -> None:
        """Check if cancelled and raise if so."""
        if self._cancelled.is_set():
            raise JobCancelledException("Job was cancelled")

    def wait_if_paused(self, check_interval: float = 0.1) -> None:
        """Block while paused, periodically checking for cancellation."""
        while self._paused.is_set():
            if self._cancelled.is_set():
                raise JobCancelledException("Job was cancelled while paused")
            time.sleep(check_interval)

    def update_progress(
        self,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
        stage: str | None = None,
        bytes_processed: int | None = None,
        bytes_total: int | None = None,
        rate_bytes_per_sec: float | None = None,
    ) -> None:
        """Update progress information."""
        with self._lock:
            if current is not None:
                self._progress.current = current
            if total is not None:
                self._progress.total = total
            if message is not None:
                self._progress.message = message
            if stage is not None:
                self._progress.stage = stage
            if bytes_processed is not None:
                self._progress.bytes_processed = bytes_processed
            if bytes_total is not None:
                self._progress.bytes_total = bytes_total
            if rate_bytes_per_sec is not None:
                self._progress.rate_bytes_per_sec = rate_bytes_per_sec

            progress_copy = JobProgress(
                current=self._progress.current,
                total=self._progress.total,
                message=self._progress.message,
                stage=self._progress.stage,
                bytes_processed=self._progress.bytes_processed,
                bytes_total=self._progress.bytes_total,
                rate_bytes_per_sec=self._progress.rate_bytes_per_sec,
            )

        # Notify callbacks outside lock
        for callback in self._progress_callbacks:
            try:
                callback(progress_copy)
            except Exception as e:
                logger.warning("Progress callback error", error=str(e))

    def add_progress_callback(self, callback: Callable[[JobProgress], None]) -> None:
        """Add a callback to be notified of progress updates."""
        self._progress_callbacks.append(callback)

    def get_progress(self) -> JobProgress:
        """Get current progress snapshot."""
        with self._lock:
            return JobProgress(
                current=self._progress.current,
                total=self._progress.total,
                message=self._progress.message,
                stage=self._progress.stage,
                bytes_processed=self._progress.bytes_processed,
                bytes_total=self._progress.bytes_total,
                rate_bytes_per_sec=self._progress.rate_bytes_per_sec,
            )

    def add_warning(self, warning: str) -> None:
        """Add a warning to the job result."""
        self._warnings.append(warning)

    def get_warnings(self) -> list[str]:
        """Get all warnings."""
        return self._warnings.copy()


class JobCancelledException(Exception):
    """Raised when a job is cancelled."""


class Job(ABC, Generic[T]):
    """Base class for all DiskForge jobs."""

    def __init__(
        self,
        name: str,
        description: str,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.priority = priority
        self.status = JobStatus.PENDING
        self.context = JobContext()
        self.result: JobResult[T] | None = None
        self.created_at = datetime.now()
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None

    @abstractmethod
    def execute(self, context: JobContext) -> T:
        """Execute the job. Subclasses must implement this."""

    @abstractmethod
    def get_plan(self) -> str:
        """Return a human-readable execution plan."""

    def validate(self) -> list[str]:
        """
        Validate job parameters before execution.
        Returns a list of validation errors (empty if valid).
        """
        return []

    def can_cancel(self) -> bool:
        """Whether this job supports cancellation."""
        return True

    def can_pause(self) -> bool:
        """Whether this job supports pausing."""
        return True


class JobRunner:
    """Executes jobs with proper lifecycle management."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job[Any]] = {}
        self._running_threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._status_callbacks: list[Callable[[str, JobStatus], None]] = []

    def submit(self, job: Job[T]) -> str:
        """Submit a job for execution. Returns job ID."""
        with self._lock:
            self._jobs[job.id] = job

        logger.info(
            "Job submitted",
            job_id=job.id,
            job_name=job.name,
            priority=job.priority.name,
        )
        return job.id

    def start(self, job_id: str) -> None:
        """Start executing a submitted job."""
        job = self._get_job(job_id)

        # Validate first
        errors = job.validate()
        if errors:
            job.status = JobStatus.FAILED
            job.result = JobResult(
                success=False,
                error="Validation failed: " + "; ".join(errors),
                start_time=datetime.now(),
                end_time=datetime.now(),
            )
            self._notify_status(job_id, JobStatus.FAILED)
            return

        # Start execution thread
        thread = threading.Thread(
            target=self._execute_job,
            args=(job,),
            name=f"job-{job_id[:8]}",
            daemon=True,
        )

        with self._lock:
            self._running_threads[job_id] = thread

        thread.start()

    def run_sync(self, job: Job[T]) -> JobResult[T]:
        """Run a job synchronously and return result."""
        self.submit(job)

        # Validate first
        errors = job.validate()
        if errors:
            job.status = JobStatus.FAILED
            result: JobResult[T] = JobResult(
                success=False,
                error="Validation failed: " + "; ".join(errors),
                start_time=datetime.now(),
                end_time=datetime.now(),
            )
            job.result = result
            return result

        self._execute_job(job)
        return job.result  # type: ignore

    def _execute_job(self, job: Job[Any]) -> None:
        """Internal job execution."""
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        self._notify_status(job.id, JobStatus.RUNNING)

        logger.info("Job started", job_id=job.id, job_name=job.name)

        try:
            result_data = job.execute(job.context)
            job.status = JobStatus.COMPLETED
            job.result = JobResult(
                success=True,
                data=result_data,
                warnings=job.context.get_warnings(),
                start_time=job.started_at,
                end_time=datetime.now(),
            )
            logger.info(
                "Job completed",
                job_id=job.id,
                job_name=job.name,
                duration_seconds=job.result.duration_seconds,
            )

        except JobCancelledException:
            job.status = JobStatus.CANCELLED
            job.result = JobResult(
                success=False,
                error="Job was cancelled",
                warnings=job.context.get_warnings(),
                start_time=job.started_at,
                end_time=datetime.now(),
            )
            logger.info("Job cancelled", job_id=job.id, job_name=job.name)

        except Exception as e:
            job.status = JobStatus.FAILED
            job.result = JobResult(
                success=False,
                error=str(e),
                error_traceback=traceback.format_exc(),
                warnings=job.context.get_warnings(),
                start_time=job.started_at,
                end_time=datetime.now(),
            )
            logger.error(
                "Job failed",
                job_id=job.id,
                job_name=job.name,
                error=str(e),
            )

        finally:
            job.completed_at = datetime.now()
            self._notify_status(job.id, job.status)

            with self._lock:
                self._running_threads.pop(job.id, None)

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of a job."""
        job = self._get_job(job_id)

        if job.status not in (JobStatus.RUNNING, JobStatus.PAUSED):
            return False

        if not job.can_cancel():
            return False

        job.context.cancel()
        logger.info("Job cancellation requested", job_id=job_id)
        return True

    def pause(self, job_id: str) -> bool:
        """Pause a running job."""
        job = self._get_job(job_id)

        if job.status != JobStatus.RUNNING:
            return False

        if not job.can_pause():
            return False

        job.context.pause()
        job.status = JobStatus.PAUSED
        self._notify_status(job_id, JobStatus.PAUSED)
        logger.info("Job paused", job_id=job_id)
        return True

    def resume(self, job_id: str) -> bool:
        """Resume a paused job."""
        job = self._get_job(job_id)

        if job.status != JobStatus.PAUSED:
            return False

        job.context.resume()
        job.status = JobStatus.RUNNING
        self._notify_status(job_id, JobStatus.RUNNING)
        logger.info("Job resumed", job_id=job_id)
        return True

    def get_job(self, job_id: str) -> Job[Any] | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def get_status(self, job_id: str) -> JobStatus | None:
        """Get the status of a job."""
        job = self._jobs.get(job_id)
        return job.status if job else None

    def get_progress(self, job_id: str) -> JobProgress | None:
        """Get the progress of a running job."""
        job = self._jobs.get(job_id)
        return job.context.get_progress() if job else None

    def get_result(self, job_id: str) -> JobResult[Any] | None:
        """Get the result of a completed job."""
        job = self._jobs.get(job_id)
        return job.result if job else None

    def wait(self, job_id: str, timeout: float | None = None) -> JobResult[Any] | None:
        """Wait for a job to complete."""
        thread = self._running_threads.get(job_id)
        if thread:
            thread.join(timeout)

        job = self._jobs.get(job_id)
        return job.result if job else None

    def list_jobs(self, status: JobStatus | None = None) -> list[Job[Any]]:
        """List all jobs, optionally filtered by status."""
        with self._lock:
            jobs = list(self._jobs.values())

        if status is not None:
            jobs = [j for j in jobs if j.status == status]

        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def add_status_callback(self, callback: Callable[[str, JobStatus], None]) -> None:
        """Add a callback to be notified of job status changes."""
        self._status_callbacks.append(callback)

    def _get_job(self, job_id: str) -> Job[Any]:
        """Get a job or raise KeyError."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job

    def _notify_status(self, job_id: str, status: JobStatus) -> None:
        """Notify all status callbacks."""
        for callback in self._status_callbacks:
            try:
                callback(job_id, status)
            except Exception as e:
                logger.warning("Status callback error", error=str(e))
