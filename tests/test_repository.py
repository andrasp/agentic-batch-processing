"""Tests for Repository persistence layer."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from agentic_batch_processor.persistence.repository import Repository
from agentic_batch_processor.core.models import (
    Job,
    WorkUnit,
    WorkerProcess,
    JobStatus,
    WorkUnitStatus,
    WorkerStatus,
)


@pytest.fixture
def repository():
    """Create a repository with a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield Repository(db_path)


@pytest.fixture
def sample_job():
    """Create a sample job for testing."""
    return Job(
        job_id="test-job-123",
        name="Test Job",
        description="Process test files",
        status=JobStatus.CREATED,
        worker_prompt_template="Process this: {file_path}",
        unit_type="file",
        total_units=3,
        max_workers=2,
        created_at=datetime.now(),
    )


@pytest.fixture
def sample_work_unit(sample_job):
    """Create a sample work unit for testing."""
    return WorkUnit(
        unit_id="test-unit-456",
        job_id=sample_job.job_id,
        unit_type="file",
        status=WorkUnitStatus.PENDING,
        payload={"file_path": "/path/to/file.txt"},
        created_at=datetime.now(),
        max_retries=3,
    )


class TestJobCRUD:
    """Tests for Job CRUD operations."""

    def test_create_and_get_job(self, repository, sample_job):
        """Test creating and retrieving a job."""
        assert repository.create_job(sample_job) is True

        retrieved = repository.get_job(sample_job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == sample_job.job_id
        assert retrieved.name == sample_job.name
        assert retrieved.status == JobStatus.CREATED
        assert retrieved.total_units == 3

    def test_get_nonexistent_job(self, repository):
        """Test getting a job that doesn't exist."""
        result = repository.get_job("nonexistent-id")
        assert result is None

    def test_update_job(self, repository, sample_job):
        """Test updating a job."""
        repository.create_job(sample_job)

        sample_job.status = JobStatus.RUNNING
        sample_job.started_at = datetime.now()
        sample_job.completed_units = 2
        assert repository.update_job(sample_job) is True

        retrieved = repository.get_job(sample_job.job_id)
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.completed_units == 2
        assert retrieved.started_at is not None

    def test_list_jobs(self, repository):
        """Test listing jobs."""
        for i in range(3):
            job = Job(
                job_id=f"job-{i}",
                name=f"Job {i}",
                description="Test",
                status=JobStatus.CREATED if i < 2 else JobStatus.COMPLETED,
                worker_prompt_template="prompt",
                unit_type="file",
                total_units=1,
                max_workers=1,
                created_at=datetime.now(),
            )
            repository.create_job(job)

        all_jobs = repository.list_jobs()
        assert len(all_jobs) == 3

        created_jobs = repository.list_jobs(status="created")
        assert len(created_jobs) == 2

    def test_job_metadata_persistence(self, repository, sample_job):
        """Test that job metadata is persisted correctly."""
        sample_job.metadata = {"executor_pid": 12345, "custom_field": "value"}
        repository.create_job(sample_job)

        retrieved = repository.get_job(sample_job.job_id)
        assert retrieved.metadata["executor_pid"] == 12345
        assert retrieved.metadata["custom_field"] == "value"


class TestWorkUnitCRUD:
    """Tests for WorkUnit CRUD operations."""

    def test_create_and_get_work_unit(self, repository, sample_job, sample_work_unit):
        """Test creating and retrieving a work unit."""
        repository.create_job(sample_job)
        assert repository.create_work_unit(sample_work_unit) is True

        retrieved = repository.get_work_unit(sample_work_unit.unit_id)
        assert retrieved is not None
        assert retrieved.unit_id == sample_work_unit.unit_id
        assert retrieved.job_id == sample_job.job_id
        assert retrieved.status == WorkUnitStatus.PENDING
        assert retrieved.payload["file_path"] == "/path/to/file.txt"

    def test_update_work_unit(self, repository, sample_job, sample_work_unit):
        """Test updating a work unit."""
        repository.create_job(sample_job)
        repository.create_work_unit(sample_work_unit)

        sample_work_unit.status = WorkUnitStatus.COMPLETED
        sample_work_unit.completed_at = datetime.now()
        sample_work_unit.result = {"output": "Success!"}
        sample_work_unit.execution_time_seconds = 5.5
        sample_work_unit.cost_usd = 0.01
        assert repository.update_work_unit(sample_work_unit) is True

        retrieved = repository.get_work_unit(sample_work_unit.unit_id)
        assert retrieved.status == WorkUnitStatus.COMPLETED
        assert retrieved.result["output"] == "Success!"
        assert retrieved.execution_time_seconds == 5.5
        assert retrieved.cost_usd == 0.01

    def test_get_pending_units(self, repository, sample_job):
        """Test getting pending work units."""
        repository.create_job(sample_job)

        for i, status in enumerate([WorkUnitStatus.PENDING, WorkUnitStatus.PENDING, WorkUnitStatus.COMPLETED]):
            unit = WorkUnit(
                unit_id=f"unit-{i}",
                job_id=sample_job.job_id,
                unit_type="file",
                status=status,
                payload={"file": f"file{i}.txt"},
                created_at=datetime.now(),
            )
            repository.create_work_unit(unit)

        pending = repository.get_pending_units(sample_job.job_id)
        assert len(pending) == 2
        assert all(u.status == WorkUnitStatus.PENDING for u in pending)

    def test_count_units_by_status(self, repository, sample_job):
        """Test counting units by status."""
        repository.create_job(sample_job)

        statuses = [
            WorkUnitStatus.PENDING,
            WorkUnitStatus.PENDING,
            WorkUnitStatus.COMPLETED,
            WorkUnitStatus.FAILED,
        ]
        for i, status in enumerate(statuses):
            unit = WorkUnit(
                unit_id=f"unit-{i}",
                job_id=sample_job.job_id,
                unit_type="file",
                status=status,
                payload={},
                created_at=datetime.now(),
            )
            repository.create_work_unit(unit)

        counts = repository.count_units_by_status(sample_job.job_id)
        assert counts["pending"] == 2
        assert counts["completed"] == 1
        assert counts["failed"] == 1


class TestStuckUnitRecovery:
    """Tests for stuck unit and stale worker cleanup."""

    def test_reset_stuck_units(self, repository, sample_job):
        """Test resetting stuck units to pending."""
        repository.create_job(sample_job)

        statuses = [
            WorkUnitStatus.PENDING,
            WorkUnitStatus.ASSIGNED,
            WorkUnitStatus.PROCESSING,
            WorkUnitStatus.COMPLETED,
        ]
        for i, status in enumerate(statuses):
            unit = WorkUnit(
                unit_id=f"unit-{i}",
                job_id=sample_job.job_id,
                unit_type="file",
                status=status,
                payload={},
                created_at=datetime.now(),
                worker_id=f"worker-{i}" if status in (WorkUnitStatus.ASSIGNED, WorkUnitStatus.PROCESSING) else None,
            )
            repository.create_work_unit(unit)

        reset_count = repository.reset_stuck_units(sample_job.job_id)
        assert reset_count == 2  # ASSIGNED and PROCESSING

        pending = repository.get_pending_units(sample_job.job_id, limit=10)
        assert len(pending) == 3  # Original PENDING + 2 reset

        # Verify worker_id was cleared
        for unit in pending:
            assert unit.worker_id is None

    def test_cleanup_stale_workers(self, repository, sample_job):
        """Test cleaning up stale workers."""
        repository.create_job(sample_job)

        workers = [
            WorkerProcess(
                worker_id="worker-1",
                status=WorkerStatus.BUSY,
                job_id=sample_job.job_id,
                current_unit_id="unit-1",
                started_at=datetime.now(),
            ),
            WorkerProcess(
                worker_id="worker-2",
                status=WorkerStatus.IDLE,
                job_id=sample_job.job_id,
                current_unit_id=None,
                started_at=datetime.now(),
            ),
            WorkerProcess(
                worker_id="worker-3",
                status=WorkerStatus.TERMINATED,
                job_id=sample_job.job_id,
                current_unit_id=None,
                started_at=datetime.now(),
            ),
        ]
        for w in workers:
            repository.create_worker(w)

        cleaned = repository.cleanup_stale_workers(sample_job.job_id)
        assert cleaned == 2  # BUSY and IDLE

        active = repository.get_active_workers(sample_job.job_id)
        assert len(active) == 0


class TestConversationStreaming:
    """Tests for real-time conversation streaming."""

    def test_append_conversation_event(self, repository, sample_job, sample_work_unit):
        """Test appending conversation events."""
        repository.create_job(sample_job)
        repository.create_work_unit(sample_work_unit)

        event1 = {"type": "user", "message": "Hello"}
        event2 = {"type": "assistant", "message": "Hi there"}

        assert repository.append_conversation_event(sample_work_unit.unit_id, event1) is True
        assert repository.append_conversation_event(sample_work_unit.unit_id, event2) is True

        retrieved = repository.get_work_unit(sample_work_unit.unit_id)
        assert retrieved.conversation is not None
        assert len(retrieved.conversation) == 2
        assert retrieved.conversation[0]["type"] == "user"
        assert retrieved.conversation[1]["type"] == "assistant"

    def test_set_work_unit_session_id(self, repository, sample_job, sample_work_unit):
        """Test setting session ID on work unit."""
        repository.create_job(sample_job)
        repository.create_work_unit(sample_work_unit)

        assert repository.set_work_unit_session_id(sample_work_unit.unit_id, "session-abc") is True

        retrieved = repository.get_work_unit(sample_work_unit.unit_id)
        assert retrieved.session_id == "session-abc"

    def test_set_work_unit_process_id(self, repository, sample_job, sample_work_unit):
        """Test setting process ID on work unit."""
        repository.create_job(sample_job)
        repository.create_work_unit(sample_work_unit)

        assert repository.set_work_unit_process_id(sample_work_unit.unit_id, 12345) is True

        retrieved = repository.get_work_unit(sample_work_unit.unit_id)
        assert retrieved.process_id == 12345


class TestLogging:
    """Tests for log operations."""

    def test_add_and_get_logs(self, repository, sample_job):
        """Test adding and retrieving logs."""
        repository.create_job(sample_job)

        repository.add_log(sample_job.job_id, "orchestrator", "info", "Job started")
        repository.add_log(sample_job.job_id, "worker", "error", "Unit failed", unit_id="unit-1")

        logs = repository.get_logs(sample_job.job_id)
        assert len(logs) == 2
        # Logs are returned in DESC order
        assert logs[0]["level"] == "error"
        assert logs[1]["level"] == "info"

    def test_get_log_count(self, repository, sample_job):
        """Test getting log count."""
        repository.create_job(sample_job)

        for i in range(5):
            repository.add_log(sample_job.job_id, "test", "info", f"Log {i}")

        count = repository.get_log_count(sample_job.job_id)
        assert count == 5


class TestCostTracking:
    """Tests for cost tracking."""

    def test_get_job_total_cost(self, repository, sample_job):
        """Test getting total cost for a job."""
        repository.create_job(sample_job)

        for i, cost in enumerate([0.01, 0.02, 0.015, None]):
            unit = WorkUnit(
                unit_id=f"unit-{i}",
                job_id=sample_job.job_id,
                unit_type="file",
                status=WorkUnitStatus.COMPLETED,
                payload={},
                created_at=datetime.now(),
                cost_usd=cost,
            )
            repository.create_work_unit(unit)

        total = repository.get_job_total_cost(sample_job.job_id)
        assert total == pytest.approx(0.045, rel=1e-3)
