"""
Tests for diskforge.core.job module.
"""

import threading
import time
from typing import Any

import pytest

from diskforge.core.job import (
    Job,
    JobContext,
    JobCancelledException,
    JobProgress,
    JobPriority,
    JobResult,
    JobRunner,
    JobStatus,
)


class SimpleJob(Job[str]):
    """Simple test job."""

    def __init__(self, result_value: str = "success", delay: float = 0) -> None:
        super().__init__(name="simple_job", description="A simple test job")
        self.result_value = result_value
        self.delay = delay

    def execute(self, context: JobContext) -> str:
        if self.delay > 0:
            time.sleep(self.delay)
        context.update_progress(current=100, message="Done")
        return self.result_value

    def get_plan(self) -> str:
        return "Execute simple job"


class FailingJob(Job[str]):
    """Job that raises an exception."""

    def __init__(self, error_message: str = "Test error") -> None:
        super().__init__(name="failing_job", description="A failing job")
        self.error_message = error_message

    def execute(self, context: JobContext) -> str:
        raise RuntimeError(self.error_message)

    def get_plan(self) -> str:
        return "Execute failing job"


class CancellableJob(Job[str]):
    """Job that can be cancelled."""

    def __init__(self) -> None:
        super().__init__(name="cancellable_job", description="A cancellable job")

    def execute(self, context: JobContext) -> str:
        for i in range(100):
            context.check_cancelled()
            context.update_progress(current=i, message=f"Step {i}")
            time.sleep(0.01)
        return "completed"

    def get_plan(self) -> str:
        return "Execute cancellable job"


class TestJobProgress:
    """Tests for JobProgress."""

    def test_default_values(self) -> None:
        progress = JobProgress()
        assert progress.current == 0
        assert progress.total == 100
        assert progress.percentage == 0.0

    def test_percentage_calculation(self) -> None:
        progress = JobProgress(current=50, total=100)
        assert progress.percentage == 50.0

        progress = JobProgress(current=25, total=100)
        assert progress.percentage == 25.0

    def test_percentage_zero_total(self) -> None:
        progress = JobProgress(current=50, total=0)
        assert progress.percentage == 0.0

    def test_eta_calculation(self) -> None:
        progress = JobProgress(
            bytes_processed=500,
            bytes_total=1000,
            rate_bytes_per_sec=100,
        )
        assert progress.eta_seconds == 5.0

    def test_eta_none_when_no_rate(self) -> None:
        progress = JobProgress(bytes_total=1000)
        assert progress.eta_seconds is None


class TestJobContext:
    """Tests for JobContext."""

    def test_initial_state(self) -> None:
        context = JobContext()
        assert not context.is_cancelled
        assert not context.is_paused

    def test_cancellation(self) -> None:
        context = JobContext()
        context.cancel()
        assert context.is_cancelled

    def test_check_cancelled_raises(self) -> None:
        context = JobContext()
        context.cancel()
        with pytest.raises(JobCancelledException):
            context.check_cancelled()

    def test_pause_resume(self) -> None:
        context = JobContext()
        context.pause()
        assert context.is_paused

        context.resume()
        assert not context.is_paused

    def test_update_progress(self) -> None:
        context = JobContext()
        context.update_progress(current=50, message="Half done")

        progress = context.get_progress()
        assert progress.current == 50
        assert progress.message == "Half done"

    def test_progress_callback(self) -> None:
        context = JobContext()
        callback_values: list[JobProgress] = []

        context.add_progress_callback(lambda p: callback_values.append(p))
        context.update_progress(current=50)

        assert len(callback_values) == 1
        assert callback_values[0].current == 50

    def test_warnings(self) -> None:
        context = JobContext()
        context.add_warning("Warning 1")
        context.add_warning("Warning 2")

        warnings = context.get_warnings()
        assert len(warnings) == 2
        assert "Warning 1" in warnings
        assert "Warning 2" in warnings


class TestJobResult:
    """Tests for JobResult."""

    def test_success_result(self) -> None:
        result: JobResult[str] = JobResult(success=True, data="test data")
        assert result.success is True
        assert result.data == "test data"
        assert result.error is None

    def test_failure_result(self) -> None:
        result: JobResult[str] = JobResult(success=False, error="Something failed")
        assert result.success is False
        assert result.error == "Something failed"

    def test_duration_calculation(self) -> None:
        from datetime import datetime, timedelta

        start = datetime.now()
        end = start + timedelta(seconds=5)

        result: JobResult[str] = JobResult(
            success=True, start_time=start, end_time=end
        )
        assert result.duration_seconds == 5.0


class TestJob:
    """Tests for Job base class."""

    def test_job_creation(self) -> None:
        job = SimpleJob()
        assert job.name == "simple_job"
        assert job.description == "A simple test job"
        assert job.status == JobStatus.PENDING
        assert job.id is not None

    def test_job_validation(self) -> None:
        job = SimpleJob()
        errors = job.validate()
        assert errors == []

    def test_job_can_cancel(self) -> None:
        job = SimpleJob()
        assert job.can_cancel() is True

    def test_job_can_pause(self) -> None:
        job = SimpleJob()
        assert job.can_pause() is True


class TestJobRunner:
    """Tests for JobRunner."""

    def test_submit_job(self) -> None:
        runner = JobRunner()
        job = SimpleJob()

        job_id = runner.submit(job)

        assert job_id == job.id
        assert runner.get_job(job_id) == job

    def test_run_sync_success(self) -> None:
        runner = JobRunner()
        job = SimpleJob(result_value="test result")

        result = runner.run_sync(job)

        assert result.success is True
        assert result.data == "test result"
        assert job.status == JobStatus.COMPLETED

    def test_run_sync_failure(self) -> None:
        runner = JobRunner()
        job = FailingJob(error_message="Test failure")

        result = runner.run_sync(job)

        assert result.success is False
        assert "Test failure" in str(result.error)
        assert job.status == JobStatus.FAILED

    def test_get_status(self) -> None:
        runner = JobRunner()
        job = SimpleJob()

        runner.submit(job)
        assert runner.get_status(job.id) == JobStatus.PENDING

    def test_get_progress(self) -> None:
        runner = JobRunner()
        job = SimpleJob()

        runner.submit(job)
        progress = runner.get_progress(job.id)

        assert progress is not None
        assert progress.current == 0

    def test_list_jobs(self) -> None:
        runner = JobRunner()
        job1 = SimpleJob()
        job2 = SimpleJob()

        runner.submit(job1)
        runner.submit(job2)

        jobs = runner.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_by_status(self) -> None:
        runner = JobRunner()
        job1 = SimpleJob()
        job2 = SimpleJob()

        runner.submit(job1)
        runner.run_sync(job2)

        pending_jobs = runner.list_jobs(status=JobStatus.PENDING)
        completed_jobs = runner.list_jobs(status=JobStatus.COMPLETED)

        assert len(pending_jobs) == 1
        assert len(completed_jobs) == 1

    def test_status_callback(self) -> None:
        runner = JobRunner()
        status_changes: list[tuple[str, JobStatus]] = []

        runner.add_status_callback(
            lambda jid, status: status_changes.append((jid, status))
        )

        job = SimpleJob()
        runner.run_sync(job)

        assert len(status_changes) >= 2  # At least RUNNING and COMPLETED
        assert status_changes[-1][1] == JobStatus.COMPLETED

    def test_cancel_running_job(self) -> None:
        runner = JobRunner()
        job = CancellableJob()

        runner.submit(job)
        runner.start(job.id)

        time.sleep(0.1)  # Let job start

        result = runner.cancel(job.id)
        assert result is True

        # Wait for cancellation
        runner.wait(job.id, timeout=2.0)
        assert job.status == JobStatus.CANCELLED

    def test_job_with_warnings(self) -> None:
        class WarningJob(Job[str]):
            def execute(self, context: JobContext) -> str:
                context.add_warning("Test warning")
                return "done"

            def get_plan(self) -> str:
                return "Job with warnings"

        runner = JobRunner()
        job = WarningJob(name="warning_job", description="Job with warnings")

        result = runner.run_sync(job)

        assert result.success is True
        assert "Test warning" in result.warnings
