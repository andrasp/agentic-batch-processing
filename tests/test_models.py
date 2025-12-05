"""Tests for core data models."""

import pytest
from datetime import datetime

from agentic_batch_processor.core.models import (
    Job,
    WorkUnit,
    WorkerProcess,
    JobStatus,
    WorkUnitStatus,
    WorkerStatus,
)


class TestWorkUnit:
    """Tests for WorkUnit model."""

    def test_to_dict_serialization(self):
        """WorkUnit.to_dict() produces valid serializable output."""
        unit = WorkUnit(
            unit_id="test-unit-123",
            job_id="test-job-456",
            unit_type="file",
            status=WorkUnitStatus.PENDING,
            payload={"file_path": "/tmp/test.txt"},
            created_at=datetime(2024, 1, 15, 10, 30, 0),
        )

        result = unit.to_dict()

        assert result["unit_id"] == "test-unit-123"
        assert result["job_id"] == "test-job-456"
        assert result["status"] == "pending"
        assert result["payload"] == {"file_path": "/tmp/test.txt"}
        assert result["created_at"] == "2024-01-15T10:30:00"

    def test_can_retry_within_limit(self):
        """can_retry() returns True when under max_retries."""
        unit = WorkUnit(
            unit_id="test",
            job_id="test",
            unit_type="file",
            status=WorkUnitStatus.FAILED,
            payload={},
            created_at=datetime.now(),
            retry_count=1,
            max_retries=3,
        )

        assert unit.can_retry() is True

    def test_can_retry_at_limit(self):
        """can_retry() returns False when at max_retries."""
        unit = WorkUnit(
            unit_id="test",
            job_id="test",
            unit_type="file",
            status=WorkUnitStatus.FAILED,
            payload={},
            created_at=datetime.now(),
            retry_count=3,
            max_retries=3,
        )

        assert unit.can_retry() is False


class TestJob:
    """Tests for Job model."""

    def test_progress_percentage_calculation(self):
        """progress_percentage() calculates correctly."""
        job = Job(
            job_id="test-job",
            name="Test Job",
            description="A test",
            status=JobStatus.RUNNING,
            worker_prompt_template="Do something",
            unit_type="file",
            total_units=100,
            completed_units=25,
            created_at=datetime.now(),
        )

        assert job.progress_percentage() == 25.0

    def test_progress_percentage_zero_total(self):
        """progress_percentage() handles zero total units."""
        job = Job(
            job_id="test-job",
            name="Test Job",
            description="A test",
            status=JobStatus.CREATED,
            worker_prompt_template="Do something",
            unit_type="file",
            total_units=0,
            created_at=datetime.now(),
        )

        assert job.progress_percentage() == 0.0

    def test_to_dict_serialization(self):
        """Job.to_dict() produces valid serializable output."""
        job = Job(
            job_id="test-job-789",
            name="Test Job",
            description="Testing serialization",
            status=JobStatus.COMPLETED,
            worker_prompt_template="Process {file_path}",
            unit_type="file",
            total_units=10,
            completed_units=10,
            created_at=datetime(2024, 1, 15, 10, 0, 0),
            completed_at=datetime(2024, 1, 15, 11, 0, 0),
        )

        result = job.to_dict()

        assert result["job_id"] == "test-job-789"
        assert result["status"] == "completed"
        assert result["total_units"] == 10
        assert result["completed_units"] == 10


class TestWorkerProcess:
    """Tests for WorkerProcess model."""

    def test_to_dict_serialization(self):
        """WorkerProcess.to_dict() produces valid serializable output."""
        worker = WorkerProcess(
            worker_id="worker-abc",
            status=WorkerStatus.BUSY,
            job_id="job-123",
            current_unit_id="unit-456",
            started_at=datetime(2024, 1, 15, 10, 0, 0),
            units_completed=5,
        )

        result = worker.to_dict()

        assert result["worker_id"] == "worker-abc"
        assert result["status"] == "busy"
        assert result["job_id"] == "job-123"
        assert result["units_completed"] == 5


class TestStatusEnums:
    """Tests for status enum values."""

    def test_job_status_values(self):
        """JobStatus enum has expected values."""
        assert JobStatus.CREATED.value == "created"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"

    def test_work_unit_status_values(self):
        """WorkUnitStatus enum has expected values."""
        assert WorkUnitStatus.PENDING.value == "pending"
        assert WorkUnitStatus.PROCESSING.value == "processing"
        assert WorkUnitStatus.COMPLETED.value == "completed"
        assert WorkUnitStatus.FAILED.value == "failed"

    def test_worker_status_values(self):
        """WorkerStatus enum has expected values."""
        assert WorkerStatus.IDLE.value == "idle"
        assert WorkerStatus.BUSY.value == "busy"
        assert WorkerStatus.TERMINATED.value == "terminated"
