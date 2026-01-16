"""
DiskForge Session Management.

Manages user sessions with comprehensive logging, state tracking,
and report generation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from diskforge.core.config import DiskForgeConfig, load_config
from diskforge.core.job import Job, JobResult, JobRunner, JobStatus
from diskforge.core.logging import SessionLogger, get_logger, setup_logging
from diskforge.core.safety import DangerMode, SafetyManager

logger = get_logger(__name__)


@dataclass
class SessionReport:
    """Complete session report for audit and review."""

    session_id: str
    started_at: datetime
    ended_at: datetime | None = None
    operations: list[dict[str, Any]] = field(default_factory=list)
    danger_mode_events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": (
                (self.ended_at - self.started_at).total_seconds()
                if self.ended_at
                else None
            ),
            "operations": self.operations,
            "danger_mode_events": self.danger_mode_events,
            "errors": self.errors,
            "warnings": self.warnings,
            "config_snapshot": self.config_snapshot,
            "summary": {
                "total_operations": len(self.operations),
                "successful_operations": sum(
                    1 for op in self.operations if op.get("success", False)
                ),
                "failed_operations": sum(
                    1 for op in self.operations if not op.get("success", True)
                ),
                "total_errors": len(self.errors),
                "total_warnings": len(self.warnings),
            },
        }

    def save(self, path: Path) -> None:
        """Save report to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


class Session:
    """
    Manages a DiskForge session with configuration, safety, and job execution.

    This is the main entry point for all DiskForge operations.
    """

    def __init__(
        self,
        config: DiskForgeConfig | None = None,
        session_id: str | None = None,
    ) -> None:
        self.id = session_id or str(uuid.uuid4())
        self.config = config or load_config()
        self.started_at = datetime.now()

        # Set up logging
        setup_logging(self.config.logging)

        # Initialize components
        self.safety = SafetyManager(self.config.safety)
        self.job_runner = JobRunner()
        self.session_logger = SessionLogger(
            self.config.get_session_file(),
            get_logger(f"session.{self.id[:8]}"),
        )

        # Initialize report
        self._report = SessionReport(
            session_id=self.id,
            started_at=self.started_at,
            config_snapshot=self.config.model_dump(mode="json"),
        )

        # Platform backend (lazily loaded)
        self._platform_backend: Any | None = None

        logger.info(
            "Session started",
            session_id=self.id,
            danger_mode=self.safety.danger_mode.name,
        )
        self.session_logger.info("Session started", session_id=self.id)

    @property
    def platform(self) -> Any:
        """Get the platform-specific backend."""
        if self._platform_backend is None:
            from diskforge.platform import get_platform_backend

            self._platform_backend = get_platform_backend()
        return self._platform_backend

    @property
    def danger_mode(self) -> DangerMode:
        """Get current danger mode state."""
        return self.safety.danger_mode

    def enable_danger_mode(self, acknowledgment: str) -> bool:
        """Enable danger mode with user acknowledgment."""
        success = self.safety.enable_danger_mode(acknowledgment)

        self._report.danger_mode_events.append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "enable_attempt",
                "success": success,
            }
        )

        if success:
            self.session_logger.warning(
                "Danger mode enabled",
                acknowledgment=acknowledgment[:50],  # Truncate for logging
            )
        else:
            self.session_logger.info("Danger mode enable attempt failed")

        return success

    def disable_danger_mode(self) -> None:
        """Disable danger mode."""
        self.safety.disable_danger_mode()

        self._report.danger_mode_events.append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "disable",
                "success": True,
            }
        )

        self.session_logger.info("Danger mode disabled")

    def run_job(self, job: Job[Any]) -> JobResult[Any]:
        """Run a job synchronously and track in session."""
        # Check if operation is allowed
        from diskforge.core.safety import OperationType

        # Map job types to operation types (subclasses should define this)
        op_type = getattr(job, "operation_type", OperationType.READ_ONLY)
        allowed, reason = self.safety.is_operation_allowed(op_type)

        if not allowed:
            result: JobResult[Any] = JobResult(
                success=False,
                error=reason,
                start_time=datetime.now(),
                end_time=datetime.now(),
            )
            self._track_operation(job, result)
            return result

        # Log plan
        plan = job.get_plan()
        self.session_logger.info(
            "Executing job",
            job_id=job.id,
            job_name=job.name,
            plan=plan,
        )

        # Run job
        result = self.job_runner.run_sync(job)

        # Track in session
        self._track_operation(job, result)

        return result

    def submit_job(self, job: Job[Any]) -> str:
        """Submit a job for async execution."""
        job_id = self.job_runner.submit(job)
        self.job_runner.start(job_id)
        return job_id

    def get_job_status(self, job_id: str) -> JobStatus | None:
        """Get job status."""
        return self.job_runner.get_status(job_id)

    def get_job_result(self, job_id: str) -> JobResult[Any] | None:
        """Get job result."""
        return self.job_runner.get_result(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        return self.job_runner.cancel(job_id)

    def _track_operation(self, job: Job[Any], result: JobResult[Any]) -> None:
        """Track an operation in the session report."""
        operation_record = {
            "timestamp": datetime.now().isoformat(),
            "job_id": job.id,
            "job_name": job.name,
            "job_description": job.description,
            "success": result.success,
            "duration_seconds": result.duration_seconds,
        }

        if result.error:
            operation_record["error"] = result.error
            self._report.errors.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "job_id": job.id,
                    "error": result.error,
                }
            )

        if result.warnings:
            operation_record["warnings"] = result.warnings
            self._report.warnings.extend(result.warnings)

        self._report.operations.append(operation_record)

        # Log
        if result.success:
            self.session_logger.info(
                "Operation completed",
                job_id=job.id,
                job_name=job.name,
            )
        else:
            self.session_logger.error(
                "Operation failed",
                job_id=job.id,
                job_name=job.name,
                error=result.error,
            )

    def close(self) -> Path:
        """Close the session and save reports."""
        self._report.ended_at = datetime.now()

        # Save session log
        self.session_logger.save()

        # Save session report
        report_path = self.config.session_directory / f"report_{self.id[:8]}.json"
        self._report.save(report_path)

        logger.info(
            "Session closed",
            session_id=self.id,
            duration_seconds=(self._report.ended_at - self.started_at).total_seconds(),
            report_path=str(report_path),
        )

        return report_path

    def get_report(self) -> SessionReport:
        """Get the current session report."""
        return self._report

    def __enter__(self) -> Session:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
