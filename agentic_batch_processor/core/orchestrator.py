"""Main orchestrator for agentic batch processing.

Coordinates the entire workflow:
1. Job creation from user intent (with flexible enumerators)
2. Work unit creation from enumerated items
3. Test execution with user approval
4. Job execution via JobExecutor
5. Progress tracking and completion

The Orchestrator is the central coordination layer. It owns all business logic
for job lifecycle management, while the MCP Server acts as a thin API wrapper.
"""

import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from .models import Job, WorkUnit, JobStatus, WorkUnitStatus
from .prompt_synthesizer import PromptSynthesizer
from ..config import DEFAULT_MAX_WORKERS, DEFAULT_MAX_RETRIES, DEFAULT_SKIP_TEST, DEFAULT_WORKER_TIMEOUT
from ..persistence.repository import Repository
from ..workers.base import BaseWorker
from ..enumerators import create_enumerator
from ..enumerators.base import EnumeratorResult


class Orchestrator:
    """Main orchestrator for agentic batch processing."""

    def __init__(
        self,
        repository: Repository,
        worker_implementation: BaseWorker,
        prompt_synthesizer: Optional[PromptSynthesizer] = None,
    ):
        """Initialize orchestrator.

        Args:
            repository: Repository for persistence
            worker_implementation: Worker to use for execution
            prompt_synthesizer: Optional custom synthesizer
        """
        self.repository = repository
        self.worker_implementation = worker_implementation
        self.prompt_synthesizer = prompt_synthesizer or PromptSynthesizer()

    def _extract_payload_description(self, result: EnumeratorResult) -> Optional[Dict[str, str]]:
        """Extract field descriptions from enumeration result."""
        if result.metadata.get("columns"):
            return {col: f"from column '{col}'" for col in result.metadata["columns"]}

        if result.items:
            sample = result.items[0]
            fields = {}
            for key in sample.keys():
                if key.startswith("_"):
                    continue
                fields[key] = "payload field"
            return fields if fields else None

        return None

    def create_job(
        self,
        name: str,
        user_intent: str,
        enumerator_type: str,
        enumerator_config: Dict[str, Any],
        max_workers: int = DEFAULT_MAX_WORKERS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        post_processing_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new batch processing job with any enumerator.

        This is the generic job creation method that supports any data source
        through the enumerator abstraction.

        Args:
            name: Human-readable job name
            user_intent: User's description of what to do with each item
            enumerator_type: Type of enumerator ("file", "sql", "csv", "json", "dynamic")
            enumerator_config: Configuration for the enumerator
            max_workers: Maximum concurrent workers
            max_retries: Maximum retries per work unit on failure
            post_processing_prompt: Optional prompt for synthesis step (scatter-gather-synthesize pattern).
                If provided, this prompt will be executed after all work units complete successfully.
                The synthesizer receives context about the job and can generate reports,
                visualizations, exports, etc. from the aggregated data.
            metadata: Optional metadata dict (e.g., post_processing_output_directory)

        Returns:
            Dict with job info and item counts
        """

        try:
            enumerator = create_enumerator(enumerator_type, enumerator_config)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        validation_error = enumerator.validate_config()
        if validation_error:
            return {"success": False, "error": f"Invalid enumerator config: {validation_error}"}

        result = enumerator.enumerate()
        if not result.success:
            return {"success": False, "error": f"Enumeration failed: {result.error}"}

        if not result.items:
            return {"success": False, "error": "No items found to process"}

        if enumerator_type == "file":
            worker_prompt = self.prompt_synthesizer.synthesize_file_processing_prompt(user_intent=user_intent)
        else:
            # Extract field descriptions from metadata or sample item
            payload_description = self._extract_payload_description(result)
            worker_prompt = self.prompt_synthesizer.synthesize_generic_prompt(
                user_intent=user_intent,
                unit_type=enumerator_type,
                payload_description=payload_description,
            )

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            name=name,
            description=user_intent,
            status=JobStatus.CREATED,
            worker_prompt_template=worker_prompt,
            unit_type=enumerator_type,
            total_units=len(result.items),
            max_workers=max_workers,
            created_at=datetime.now(),
            post_processing_prompt=post_processing_prompt,
            metadata=metadata or {},
        )

        if not self.repository.create_job(job):
            return {"success": False, "error": "Failed to save job to database"}

        for item in result.items:
            unit = WorkUnit(
                unit_id=str(uuid.uuid4()),
                job_id=job_id,
                unit_type=enumerator_type,
                status=WorkUnitStatus.PENDING,
                payload=item,
                created_at=datetime.now(),
                max_retries=max_retries,
            )
            self.repository.create_work_unit(unit)

        return {
            "success": True,
            "job_id": job_id,
            "total_items": len(result.items),
            "enumerator_type": enumerator_type,
            "metadata": result.metadata,
            "worker_prompt": worker_prompt,
            "has_post_processing": post_processing_prompt is not None,
            "message": f"Created job '{name}' with {len(result.items)} items to process"
            + (" (with post-processing step)" if post_processing_prompt else ""),
        }

    def start_job(self, job_id: str, approve: Optional[bool] = None, skip_test: bool = False) -> Dict[str, Any]:
        """Start a job with optional test phase.

        On first call for a CREATED job, runs a test on the first work unit and
        returns results for review. Call again with approve=True to process
        remaining units, or approve=False to reject and reset.

        Args:
            job_id: The job ID to start
            approve: After test phase - True to approve and start, False to reject and reset
            skip_test: Skip the test phase and start immediately (default: False)

        Returns:
            Dict with status, test results, or error
        """
        from .job_executor import JobExecutor

        job = self.repository.get_job(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        global_skip = os.environ.get("ABP_SKIP_TEST", "").lower() in ("1", "true")

        if job.status == JobStatus.CREATED:
            if skip_test or global_skip or DEFAULT_SKIP_TEST:
                return self._start_job_executor(job)
            else:
                return self._run_test_phase(job)

        elif job.status == JobStatus.TESTING:
            if approve is True:
                return self._start_job_executor(job)
            elif approve is False:
                job.status = JobStatus.CREATED
                job.test_passed = False
                self.repository.update_job(job)
                return {
                    "success": True,
                    "status": "reset",
                    "job_id": job.job_id,
                    "message": "Job reset to CREATED. Modify the prompt and try again.",
                }
            else:
                return self._get_test_results(job)

        elif job.status == JobStatus.RUNNING:
            status = JobExecutor.get_executor_status(self.repository, job_id)
            if status["status"] == "running":
                return {
                    "success": True,
                    "status": "running",
                    "message": f"Job {job_id} is already running",
                    "pid": status.get("pid"),
                }
            return self._start_job_executor(job)

        else:
            return {"error": f"Cannot start job in {job.status.value} status"}

    def _run_test_phase(self, job: Job) -> Dict[str, Any]:
        """Execute test on first work unit.

        Args:
            job: The Job object

        Returns:
            Dict with test results including conversation
        """
        units = self.repository.get_pending_units(job.job_id, limit=1)
        if not units:
            return {"error": "No pending units to test"}

        test_unit = units[0]

        job.status = JobStatus.TESTING
        job.test_unit_id = test_unit.unit_id
        self.repository.update_job(job)

        test_unit.status = WorkUnitStatus.PROCESSING
        test_unit.started_at = datetime.now()
        self.repository.update_work_unit(test_unit)

        def on_stream_event(event_type: str, event: Dict[str, Any]):
            """Save streaming events to DB for live dashboard updates."""
            if event_type == "system" and event.get("subtype") == "init":
                session_id = event.get("session_id")
                if session_id:
                    self.repository.set_work_unit_session_id(test_unit.unit_id, session_id)
            elif event_type in ("user", "assistant", "tool_use", "tool_result"):
                self.repository.append_conversation_event(test_unit.unit_id, event)

        def on_process_start(pid: int):
            """Track process ID for kill functionality."""
            self.repository.set_work_unit_process_id(test_unit.unit_id, pid)

        result = self.worker_implementation.execute(
            prompt=job.worker_prompt_template,
            work_unit_payload=test_unit.payload,
            timeout=DEFAULT_WORKER_TIMEOUT,
            on_stream_event=on_stream_event,
            on_process_start=on_process_start,
        )

        test_unit.status = WorkUnitStatus.COMPLETED if result.success else WorkUnitStatus.FAILED
        test_unit.completed_at = datetime.now()
        test_unit.result = {"output": result.output}
        test_unit.error = result.error
        test_unit.conversation = result.conversation
        test_unit.execution_time_seconds = result.execution_time
        test_unit.cost_usd = result.metadata.get("total_cost_usd") if result.metadata else None
        self.repository.update_work_unit(test_unit)

        job.test_passed = result.success
        if result.success:
            job.completed_units = 1  # Test unit is now done
        self.repository.update_job(job)

        return {
            "status": "testing",
            "test_passed": result.success,
            "job_id": job.job_id,
            "test_unit_id": test_unit.unit_id,
            "test_unit_payload": test_unit.payload,
            "output": result.output,
            "error": result.error,
            "execution_time": result.execution_time,
            "cost_usd": test_unit.cost_usd,
            "remaining_units": job.total_units - 1,
            "awaiting_user_approval": True,
            "message": (
                "TEST COMPLETE - USER APPROVAL REQUIRED. "
                "Review the output above and ask the user if they want to proceed. "
                "DO NOT auto-approve. Wait for explicit user confirmation. "
                "Call start_job with approve=true only after user says yes, "
                "or approve=false if user wants to reject and modify the prompt."
                if result.success
                else "Test failed. Review the error above. "
                "View full conversation in the dashboard. "
                "Call start_job with approve=false to reset, then modify the prompt and try again."
            ),
        }

    def _start_job_executor(self, job: Job) -> Dict[str, Any]:
        """Start the JobExecutor for remaining units.

        Args:
            job: The Job object

        Returns:
            Dict with start status
        """
        from .job_executor import JobExecutor

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now()
        self.repository.update_job(job)

        executor = JobExecutor(
            job_id=job.job_id,
            repository=self.repository,
            worker_implementation=self.worker_implementation,
        )
        pid = executor.start_detached()

        remaining = job.total_units - job.completed_units
        return {
            "success": True,
            "status": "started",
            "job_id": job.job_id,
            "pid": pid,
            "remaining_units": remaining,
            "message": f"Job started. Processing {remaining} remaining units.",
        }

    def _get_test_results(self, job: Job) -> Dict[str, Any]:
        """Return existing test results for a job in TESTING state.

        Args:
            job: The Job object

        Returns:
            Dict with test results
        """
        if not job.test_unit_id:
            return {"error": "No test unit found"}

        test_unit = self.repository.get_work_unit(job.test_unit_id)
        if not test_unit:
            return {"error": "Test unit not found"}

        return {
            "status": "testing",
            "test_passed": job.test_passed,
            "job_id": job.job_id,
            "test_unit_id": test_unit.unit_id,
            "test_unit_payload": test_unit.payload,
            "output": test_unit.result.get("output") if test_unit.result else None,
            "error": test_unit.error,
            "execution_time": test_unit.execution_time_seconds,
            "cost_usd": test_unit.cost_usd,
            "remaining_units": job.total_units - job.completed_units,
            "awaiting_user_approval": True,
            "message": "USER APPROVAL REQUIRED. Ask the user if they want to proceed. Call start_job with approve=true only after user confirms, or approve=false to reject.",
        }

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get current job status and progress.

        Args:
            job_id: Job ID

        Returns:
            Dict with job status, progress, and executor info
        """
        import sqlite3
        from .job_executor import JobExecutor

        try:
            job = self.repository.get_job(job_id)
            if not job:
                return {"error": f"Job not found: {job_id}"}

            executor_status = JobExecutor.get_executor_status(self.repository, job_id)
            status_counts = self.repository.count_units_by_status(job_id)

            return {
                "job_id": job_id,
                "status": job.status.value,
                "executor_status": executor_status["status"],
                "progress": {
                    "total": job.total_units,
                    "completed": job.completed_units,
                    "failed": job.failed_units,
                    "percentage": round(job.progress_percentage(), 1),
                },
                "unit_stats": status_counts,
                "executor_pid": executor_status.get("pid"),
            }
        except sqlite3.OperationalError as e:
            return {"error": f"Database busy or locked: {str(e)}"}
        except Exception as e:
            return {"error": str(e)}
