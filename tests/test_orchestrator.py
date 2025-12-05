"""Tests for Orchestrator business logic."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from unittest.mock import Mock, patch

import pytest

from agentic_batch_processor.core.orchestrator import Orchestrator
from agentic_batch_processor.core.models import Job, WorkUnit, JobStatus, WorkUnitStatus
from agentic_batch_processor.persistence.repository import Repository
from agentic_batch_processor.workers.base import BaseWorker, WorkerResult


class MockWorker(BaseWorker):
    """Mock worker for testing."""

    def __init__(self, result: Optional[WorkerResult] = None):
        self.result = result or WorkerResult(
            success=True,
            output="Mock output",
            error=None,
            conversation=[{"type": "assistant", "message": "Done"}],
            execution_time=1.5,
            metadata={"total_cost_usd": 0.01},
        )
        self.execute_calls = []

    def execute(
        self,
        prompt: str,
        work_unit_payload: Dict[str, Any],
        timeout: float = 600.0,
        on_stream_event: Optional[Callable] = None,
        on_process_start: Optional[Callable] = None,
    ) -> WorkerResult:
        self.execute_calls.append(
            {
                "prompt": prompt,
                "payload": work_unit_payload,
                "timeout": timeout,
            }
        )
        # Simulate callbacks
        if on_process_start:
            on_process_start(12345)
        if on_stream_event:
            on_stream_event("assistant", {"type": "text", "text": "Working..."})
        return self.result

    def is_available(self) -> bool:
        return True

    def get_name(self) -> str:
        return "mock"


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
def repository(temp_db):
    """Create a repository with a temporary database."""
    return Repository(temp_db)


@pytest.fixture
def mock_worker():
    """Create a mock worker."""
    return MockWorker()


@pytest.fixture
def orchestrator(repository, mock_worker):
    """Create an orchestrator with mock worker."""
    return Orchestrator(repository=repository, worker_implementation=mock_worker)


class TestJobCreation:
    """Tests for job creation via Orchestrator."""

    def test_create_job_with_file_enumerator(self, orchestrator, temp_db):
        """Test creating a job with file enumerator."""
        # Create test files
        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")

        result = orchestrator.create_job(
            name="Test File Job",
            user_intent="Analyze each file",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
        )

        assert result["success"] is True
        assert result["total_items"] == 2
        assert result["enumerator_type"] == "file"
        assert "job_id" in result

        # Verify job was persisted
        job = orchestrator.repository.get_job(result["job_id"])
        assert job is not None
        assert job.status == JobStatus.CREATED
        assert job.total_units == 2

    def test_create_job_with_json_enumerator(self, orchestrator, temp_db):
        """Test creating a job with JSON enumerator."""
        json_file = temp_db.parent / "data.json"
        json_file.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]')

        result = orchestrator.create_job(
            name="Test JSON Job",
            user_intent="Process each item",
            enumerator_type="json",
            enumerator_config={"file_path": str(json_file)},
        )

        assert result["success"] is True
        assert result["total_items"] == 3

    def test_create_job_with_invalid_enumerator(self, orchestrator):
        """Test creating a job with invalid enumerator type."""
        result = orchestrator.create_job(
            name="Bad Job",
            user_intent="Do something",
            enumerator_type="invalid_type",
            enumerator_config={},
        )

        assert result["success"] is False
        assert "error" in result

    def test_create_job_with_empty_directory(self, orchestrator, temp_db):
        """Test creating a job with no matching files."""
        empty_dir = temp_db.parent / "empty"
        empty_dir.mkdir()

        result = orchestrator.create_job(
            name="Empty Job",
            user_intent="Process files",
            enumerator_type="file",
            enumerator_config={"directory": str(empty_dir), "pattern": "*.txt"},
        )

        assert result["success"] is False
        assert "No items found" in result["error"]

    def test_create_job_with_post_processing(self, orchestrator, temp_db):
        """Test creating a job with post-processing prompt."""
        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")

        result = orchestrator.create_job(
            name="Job with Post-Processing",
            user_intent="Analyze file",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
            post_processing_prompt="Summarize all results",
        )

        assert result["success"] is True
        assert result["has_post_processing"] is True

        job = orchestrator.repository.get_job(result["job_id"])
        assert job.post_processing_prompt == "Summarize all results"


class TestStartJobStateMachine:
    """Tests for start_job state machine logic."""

    def _create_test_job(self, orchestrator, temp_db, status=JobStatus.CREATED) -> str:
        """Helper to create a job in a specific state."""
        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir(exist_ok=True)
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")

        result = orchestrator.create_job(
            name="Test Job",
            user_intent="Process files",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
        )
        job_id = result["job_id"]

        if status != JobStatus.CREATED:
            job = orchestrator.repository.get_job(job_id)
            job.status = status
            orchestrator.repository.update_job(job)

        return job_id

    def test_start_job_runs_test_phase(self, orchestrator, temp_db):
        """Test that start_job runs test phase for CREATED jobs."""
        job_id = self._create_test_job(orchestrator, temp_db)

        result = orchestrator.start_job(job_id)

        assert result["status"] == "testing"
        assert result["test_passed"] is True
        assert result["awaiting_user_approval"] is True
        assert "remaining_units" in result

        # Verify job status changed
        job = orchestrator.repository.get_job(job_id)
        assert job.status == JobStatus.TESTING
        assert job.test_unit_id is not None

    def test_start_job_skip_test(self, orchestrator, temp_db):
        """Test that start_job can skip test phase."""
        job_id = self._create_test_job(orchestrator, temp_db)

        with patch("agentic_batch_processor.core.job_executor.JobExecutor") as MockExecutor:
            mock_instance = Mock()
            mock_instance.start_detached.return_value = 99999
            MockExecutor.return_value = mock_instance

            result = orchestrator.start_job(job_id, skip_test=True)

        assert result["success"] is True
        assert result["status"] == "started"
        assert "pid" in result

        job = orchestrator.repository.get_job(job_id)
        assert job.status == JobStatus.RUNNING

    def test_start_job_approve_after_test(self, orchestrator, temp_db):
        """Test approving a job after test phase."""
        job_id = self._create_test_job(orchestrator, temp_db)

        # Run test phase
        orchestrator.start_job(job_id)

        # Approve
        with patch("agentic_batch_processor.core.job_executor.JobExecutor") as MockExecutor:
            mock_instance = Mock()
            mock_instance.start_detached.return_value = 99999
            MockExecutor.return_value = mock_instance

            result = orchestrator.start_job(job_id, approve=True)

        assert result["success"] is True
        assert result["status"] == "started"

        job = orchestrator.repository.get_job(job_id)
        assert job.status == JobStatus.RUNNING

    def test_start_job_reject_after_test(self, orchestrator, temp_db):
        """Test rejecting a job after test phase."""
        job_id = self._create_test_job(orchestrator, temp_db)

        # Run test phase
        orchestrator.start_job(job_id)

        # Reject
        result = orchestrator.start_job(job_id, approve=False)

        assert result["success"] is True
        assert result["status"] == "reset"

        job = orchestrator.repository.get_job(job_id)
        assert job.status == JobStatus.CREATED
        assert job.test_passed is False

    def test_start_job_returns_test_results_without_approval(self, orchestrator, temp_db):
        """Test that calling start_job without approve returns test results."""
        job_id = self._create_test_job(orchestrator, temp_db)

        # Run test phase
        orchestrator.start_job(job_id)

        # Call again without approve
        result = orchestrator.start_job(job_id)

        assert result["status"] == "testing"
        assert result["awaiting_user_approval"] is True

    def test_start_job_nonexistent(self, orchestrator):
        """Test starting a job that doesn't exist."""
        result = orchestrator.start_job("nonexistent-job-id")
        assert "error" in result
        assert "not found" in result["error"]

    def test_start_job_completed_status(self, orchestrator, temp_db):
        """Test starting a job that's already completed."""
        job_id = self._create_test_job(orchestrator, temp_db, status=JobStatus.COMPLETED)

        result = orchestrator.start_job(job_id)

        assert "error" in result
        assert "completed" in result["error"]


class TestTestPhase:
    """Tests for test phase execution."""

    def test_test_phase_records_results(self, orchestrator, temp_db):
        """Test that test phase records results on the work unit."""
        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")

        create_result = orchestrator.create_job(
            name="Test Job",
            user_intent="Process file",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
        )
        job_id = create_result["job_id"]

        result = orchestrator.start_job(job_id)

        # Verify test unit was updated
        job = orchestrator.repository.get_job(job_id)
        test_unit = orchestrator.repository.get_work_unit(job.test_unit_id)

        assert test_unit.status == WorkUnitStatus.COMPLETED
        assert test_unit.result is not None
        assert test_unit.execution_time_seconds == 1.5
        assert test_unit.cost_usd == 0.01

    def test_test_phase_failure(self, orchestrator, temp_db):
        """Test handling of test phase failure."""
        # Create worker that returns failure
        failed_worker = MockWorker(
            WorkerResult(
                success=False,
                output=None,
                error="Something went wrong",
                conversation=[],
                execution_time=0.5,
            )
        )
        orchestrator.worker_implementation = failed_worker

        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")

        create_result = orchestrator.create_job(
            name="Test Job",
            user_intent="Process file",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
        )
        job_id = create_result["job_id"]

        result = orchestrator.start_job(job_id)

        assert result["status"] == "testing"
        assert result["test_passed"] is False
        assert result["error"] == "Something went wrong"

        job = orchestrator.repository.get_job(job_id)
        assert job.test_passed is False


class TestGetJobStatus:
    """Tests for get_job_status."""

    def test_get_job_status(self, orchestrator, temp_db):
        """Test getting job status."""
        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")

        create_result = orchestrator.create_job(
            name="Test Job",
            user_intent="Process files",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
        )
        job_id = create_result["job_id"]

        with patch("agentic_batch_processor.core.job_executor.JobExecutor") as MockExecutor:
            MockExecutor.get_executor_status.return_value = {"status": "not_found"}

            result = orchestrator.get_job_status(job_id)

        assert result["job_id"] == job_id
        assert result["status"] == "created"
        assert result["progress"]["total"] == 2
        assert result["progress"]["completed"] == 0

    def test_get_job_status_nonexistent(self, orchestrator):
        """Test getting status of nonexistent job."""
        with patch("agentic_batch_processor.core.job_executor.JobExecutor"):
            result = orchestrator.get_job_status("nonexistent-id")

        assert "error" in result
        assert "not found" in result["error"]


class TestEnvironmentVariables:
    """Tests for environment variable handling."""

    def test_skip_test_env_var(self, orchestrator, temp_db):
        """Test ABP_SKIP_TEST environment variable."""
        test_dir = temp_db.parent / "test_files"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")

        create_result = orchestrator.create_job(
            name="Test Job",
            user_intent="Process file",
            enumerator_type="file",
            enumerator_config={"base_directory": str(test_dir), "pattern": "*.txt"},
        )
        job_id = create_result["job_id"]

        with patch.dict("os.environ", {"ABP_SKIP_TEST": "1"}):
            with patch("agentic_batch_processor.core.job_executor.JobExecutor") as MockExecutor:
                mock_instance = Mock()
                mock_instance.start_detached.return_value = 99999
                MockExecutor.return_value = mock_instance

                result = orchestrator.start_job(job_id)

        # Should skip test and start immediately
        assert result["success"] is True
        assert result["status"] == "started"
