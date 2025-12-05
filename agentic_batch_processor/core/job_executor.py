"""Job Executor Process for resilient job execution.

The Job Executor runs as a detached background process that:
- Survives parent process termination
- Can be restarted to resume processing
- Manages worker pool lifecycle
- Writes progress to SQLite for monitoring
- Logs all activity for debugging
"""

import os
import signal
import time
import traceback
import uuid
from datetime import datetime
from multiprocessing import Process
from pathlib import Path
from typing import Optional, Dict, Any

from .models import Job, JobStatus, WorkUnit, WorkUnitStatus
from .worker_pool import WorkerPool
from ..persistence.repository import Repository
from ..workers.base import BaseWorker


class JobLogger:
    """Simple logger that writes to the database."""

    def __init__(self, repository: Repository, job_id: str, source: str = "executor"):
        self.repository = repository
        self.job_id = job_id
        self.source = source

    def _log(self, level: str, message: str, **kwargs):
        self.repository.add_log(job_id=self.job_id, source=self.source, level=level, message=message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("error", message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._log("debug", message, **kwargs)


class JobExecutor:
    """Executes jobs as a detached background process."""

    def __init__(self, job_id: str, repository: Repository, worker_implementation: BaseWorker):
        """Initialize job executor.

        Args:
            job_id: ID of the job to execute
            repository: Repository for persistence
            worker_implementation: Worker to use for execution
        """
        self.job_id = job_id
        self.repository = repository
        self.worker_implementation = worker_implementation
        self._process: Optional[Process] = None
        self._should_stop = False

    def start_detached(self) -> int:
        """Start job processing as a detached background process.

        Returns:
            PID of the spawned process
        """

        self._process = Process(
            target=self._run_job_loop, args=(self.job_id, str(self.repository.db_path)), daemon=False
        )
        self._process.start()

        job = self.repository.get_job(self.job_id)
        if job:
            job.metadata["executor_pid"] = self._process.pid
            job.metadata["executor_started_at"] = datetime.now().isoformat()
            self.repository.update_job(job)

        return self._process.pid

    def _run_job_loop(self, job_id: str, db_path: str):
        """Main job processing loop (runs in child process).

        Args:
            job_id: Job ID to process
            db_path: Path to SQLite database
        """

        repository = Repository(Path(db_path))
        logger = JobLogger(repository, job_id, source="executor")

        logger.info(f"Job executor process started (PID: {os.getpid()})")

        def signal_handler(signum, frame):
            self._should_stop = True
            logger.info(f"Received signal {signum}, initiating graceful shutdown")

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:
            job = repository.get_job(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in database")
                return

            logger.info(f"Starting job '{job.name}' with {job.total_units} units, max_workers={job.max_workers}")

            stale_workers = repository.cleanup_stale_workers(job_id)
            stuck_units = repository.reset_stuck_units(job_id)
            if stale_workers > 0 or stuck_units > 0:
                logger.info(
                    f"Cleaned up {stale_workers} stale workers and reset {stuck_units} stuck units from previous run"
                )

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now()
            repository.update_job(job)

            pool = WorkerPool(
                job_id=job_id,
                worker_implementation=self.worker_implementation,
                repository=repository,
                max_workers=job.max_workers,
                on_unit_complete=lambda unit, result: self._on_unit_complete(repository, job_id, unit, result, logger),
                on_unit_failed=lambda unit, result: self._on_unit_failed(repository, job_id, unit, result, logger),
            )

            pool.start()
            logger.info(f"Worker pool started with {job.max_workers} max workers")

            units_submitted = 0

            try:

                while not self._should_stop:

                    pending_units = repository.get_pending_units(job_id, limit=job.max_workers)

                    if not pending_units:

                        active_count = pool.get_active_worker_count()
                        if active_count == 0:
                            logger.info("No more pending units and no active workers - processing complete")
                            break
                        time.sleep(1.0)
                        continue

                    for unit in pending_units:
                        if self._should_stop:
                            break

                        while not pool.wait_for_available_slot(timeout=1.0):
                            if self._should_stop:
                                break

                        if self._should_stop:
                            break

                        pool.submit_work_unit(unit, job.worker_prompt_template)
                        units_submitted += 1
                        logger.debug(
                            f"Submitted unit {unit.unit_id[:8]}... ({units_submitted} total)", unit_id=unit.unit_id
                        )

                logger.info("Waiting for remaining workers to complete...")
                pool.wait_for_completion()

                job = repository.get_job(job_id)
                if job:
                    all_units_done = (job.completed_units + job.failed_units) == job.total_units
                    all_succeeded = job.completed_units == job.total_units

                    should_run_post_processing = job.post_processing_prompt and (
                        all_succeeded or (job.bypass_failures and all_units_done)
                    )

                    if should_run_post_processing:
                        if job.bypass_failures and not all_succeeded:
                            logger.info(
                                f"Bypass failures enabled. Running post-processing despite {job.failed_units} failed units."
                            )
                        else:
                            logger.info(
                                f"All {job.total_units} units completed successfully. Starting post-processing..."
                            )
                        self._run_post_processing(repository, job, pool, logger)

            finally:
                pool.stop()
                logger.info("Worker pool stopped")

            job = repository.get_job(job_id)
            if job:
                post_unit = (
                    repository.get_work_unit(job.post_processing_unit_id) if job.post_processing_unit_id else None
                )
                job.status = self._determine_final_status(job, post_unit, logger)
                job.completed_at = datetime.now()
                job.metadata["executor_completed_at"] = datetime.now().isoformat()
                repository.update_job(job)

        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"Job executor crashed: {str(e)}", extra={"traceback": error_trace})

            job = repository.get_job(job_id)
            if job:
                job.status = JobStatus.FAILED
                job.metadata["executor_error"] = str(e)
                job.metadata["executor_error_traceback"] = error_trace
                job.metadata["executor_error_at"] = datetime.now().isoformat()
                repository.update_job(job)

    def _determine_final_status(self, job: Job, post_unit: Optional[WorkUnit], logger: JobLogger) -> JobStatus:
        """Determine the final status of a job after processing completes.

        Args:
            job: The job to evaluate
            post_unit: The post-processing work unit, if any
            logger: Logger instance

        Returns:
            The appropriate final JobStatus
        """
        all_units_done = (job.completed_units + job.failed_units) == job.total_units
        all_succeeded = job.completed_units == job.total_units

        post_processing_failed = post_unit and post_unit.status == WorkUnitStatus.FAILED
        post_processing_succeeded = post_unit and post_unit.status == WorkUnitStatus.COMPLETED

        if post_processing_failed:
            logger.warning("Job failed: post-processing step failed")
            return JobStatus.FAILED

        if all_succeeded and (not job.post_processing_prompt or post_processing_succeeded):
            logger.info(f"Job completed successfully: {job.completed_units}/{job.total_units} units")
            return JobStatus.COMPLETED

        if job.bypass_failures and post_processing_succeeded:
            logger.info(
                f"Job completed with bypassed failures: {job.completed_units} succeeded, {job.failed_units} bypassed"
            )
            return JobStatus.COMPLETED

        if job.failed_units > 0 and all_units_done:
            logger.warning(f"Job finished with failures: {job.completed_units} completed, {job.failed_units} failed")
            return JobStatus.FAILED

        logger.info(f"Job paused: {job.completed_units} completed, {job.failed_units} failed, remaining pending")
        return JobStatus.PAUSED

    def _on_unit_complete(self, repository: Repository, job_id: str, unit, result, logger: JobLogger):
        """Callback when a unit completes successfully."""
        job = repository.get_job(job_id)
        if job:
            is_post_processing = unit.unit_id == job.post_processing_unit_id
            if not is_post_processing:
                job.completed_units += 1
                repository.update_job(job)
            logger.info(
                f"Unit completed: {unit.unit_id[:8]}... ({job.completed_units}/{job.total_units})",
                unit_id=unit.unit_id,
                worker_id=unit.worker_id,
                extra={
                    "execution_time": result.execution_time,
                    "cost_usd": result.metadata.get("total_cost_usd") if result.metadata else None,
                },
            )

    def _on_unit_failed(self, repository: Repository, job_id: str, unit, result, logger: JobLogger):
        """Callback when a unit fails."""
        error_msg = result.error or "Unknown error"
        job = repository.get_job(job_id)
        is_post_processing = job and unit.unit_id == job.post_processing_unit_id

        if unit.can_retry():
            unit.status = WorkUnitStatus.PENDING
            unit.retry_count += 1
            unit.worker_id = None
            unit.assigned_at = None
            unit.started_at = None
            repository.update_work_unit(unit)
            logger.warning(
                f"Unit failed, will retry ({unit.retry_count}/{unit.max_retries}): {unit.unit_id[:8]}... - {error_msg}",
                unit_id=unit.unit_id,
                worker_id=unit.worker_id,
            )
        else:
            if job and not is_post_processing:
                job.failed_units += 1
                repository.update_job(job)
            logger.error(
                f"Unit failed permanently after {unit.max_retries} retries: {unit.unit_id[:8]}... - {error_msg}",
                unit_id=unit.unit_id,
                worker_id=unit.worker_id,
                extra={"error": error_msg},
            )

    def _run_post_processing(self, repository: Repository, job: Job, pool: WorkerPool, logger: JobLogger):
        """Run the synthesis step for scatter-gather-synthesize pattern.

        Creates a special work unit for post-processing and executes it.

        Args:
            repository: Repository for persistence
            job: The job with post_processing_prompt
            pool: Worker pool to use for execution
            logger: Logger instance
        """
        job.status = JobStatus.POST_PROCESSING
        repository.update_job(job)

        post_unit_id = str(uuid.uuid4())
        payload = {
            "type": "post_processing",
            "total_units_processed": job.total_units,
            "completed_units": job.completed_units,
            "job_name": job.name,
            "job_description": job.description,
        }
        if job.metadata.get("post_processing_name"):
            payload["name"] = job.metadata["post_processing_name"]
        if job.metadata.get("post_processing_working_directory"):
            payload["working_directory"] = job.metadata["post_processing_working_directory"]
        if job.metadata.get("post_processing_output_directory"):
            payload["output_directory"] = job.metadata["post_processing_output_directory"]

        post_unit = WorkUnit(
            unit_id=post_unit_id,
            job_id=job.job_id,
            unit_type="post_processing",
            status=WorkUnitStatus.PENDING,
            payload=payload,
            created_at=datetime.now(),
            max_retries=job.metadata.get("max_retries", 3),
        )

        repository.create_work_unit(post_unit)

        job.post_processing_unit_id = post_unit_id
        repository.update_job(job)

        logger.info(
            f"Created post-processing unit {post_unit_id[:8]}...",
            unit_id=post_unit_id,
        )

        pool.start()

        pool.submit_work_unit(post_unit, job.post_processing_prompt)

        logger.info("Waiting for post-processing to complete...")
        pool.wait_for_completion()

        post_unit = repository.get_work_unit(post_unit_id)
        if post_unit and post_unit.status == WorkUnitStatus.COMPLETED:
            logger.info("Post-processing completed successfully")
        elif post_unit and post_unit.status == WorkUnitStatus.FAILED:
            logger.error(f"Post-processing failed: {post_unit.error}")
        else:
            logger.warning(f"Post-processing ended with status: {post_unit.status.value if post_unit else 'unknown'}")

    @staticmethod
    def get_executor_status(repository: Repository, job_id: str) -> Dict[str, Any]:
        """Get the status of the job executor process.

        Args:
            repository: Repository to query
            job_id: Job ID to check

        Returns:
            Dict with executor status information
        """
        job = repository.get_job(job_id)
        if not job:
            return {"status": "not_found"}

        pid = job.metadata.get("executor_pid")
        if not pid:
            return {"status": "not_started", "job_status": job.status.value}

        try:
            os.kill(pid, 0)
            is_running = True
        except ProcessLookupError:
            is_running = False
        except PermissionError:

            is_running = True

        return {
            "status": "running" if is_running else "stopped",
            "pid": pid,
            "job_status": job.status.value,
            "started_at": job.metadata.get("executor_started_at"),
            "completed_at": job.metadata.get("executor_completed_at"),
            "error": job.metadata.get("executor_error"),
            "progress": {
                "total": job.total_units,
                "completed": job.completed_units,
                "failed": job.failed_units,
                "percentage": job.progress_percentage(),
            },
        }

    @staticmethod
    def stop_executor(repository: Repository, job_id: str) -> bool:
        """Stop the job executor process gracefully.

        Args:
            repository: Repository to query
            job_id: Job ID to stop

        Returns:
            True if signal was sent, False if process not found
        """
        job = repository.get_job(job_id)
        if not job:
            return False

        pid = job.metadata.get("executor_pid")
        if not pid:
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return False

    @staticmethod
    def kill_executor(repository: Repository, job_id: str) -> Dict[str, Any]:
        """Kill the job executor process forcefully (SIGKILL).

        This is a hard kill that immediately terminates the executor process
        and all its child processes.

        Args:
            repository: Repository to query
            job_id: Job ID to kill

        Returns:
            Dict with result information
        """
        job = repository.get_job(job_id)
        if not job:
            return {"success": False, "error": "Job not found"}

        pid = job.metadata.get("executor_pid")
        if not pid:
            return {"success": False, "error": "No executor process found"}

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            job.status = JobStatus.FAILED
            job.metadata["killed_at"] = datetime.now().isoformat()
            job.metadata["kill_reason"] = "User requested kill (process already dead)"
            repository.update_job(job)
            return {"success": True, "message": "Process was already dead, job marked as failed"}
        except PermissionError:
            return {"success": False, "error": "Permission denied to check process"}

        try:
            # Try to kill entire process group (includes child processes)
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Fallback to killing just the process
                os.kill(pid, signal.SIGKILL)

            job.status = JobStatus.FAILED
            job.metadata["killed_at"] = datetime.now().isoformat()
            job.metadata["kill_reason"] = "User requested kill"
            repository.update_job(job)

            repository.reset_stuck_units(job_id)

            return {"success": True, "message": "Job executor killed", "pid": pid}
        except ProcessLookupError:
            return {"success": False, "error": "Process not found"}
        except PermissionError:
            return {"success": False, "error": "Permission denied to kill process"}

    @staticmethod
    def kill_work_unit(repository: Repository, job_id: str, unit_id: str) -> Dict[str, Any]:
        """Kill a specific work unit's subprocess.

        Args:
            repository: Repository to query
            job_id: Job ID the unit belongs to
            unit_id: Work unit ID to kill

        Returns:
            Dict with result information
        """
        unit = repository.get_work_unit(unit_id)
        if not unit:
            return {"success": False, "error": "Work unit not found"}

        if unit.job_id != job_id:
            return {"success": False, "error": "Work unit does not belong to this job"}

        pid = unit.process_id
        if not pid:
            return {"success": False, "error": "No process found for this unit (may not be running)"}

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            unit.status = WorkUnitStatus.FAILED
            unit.error = "Process killed by user (process already dead)"
            unit.process_id = None
            repository.update_work_unit(unit)
            return {"success": True, "message": "Process was already dead, unit marked as failed"}
        except PermissionError:
            return {"success": False, "error": "Permission denied to check process"}

        try:
            # Try to kill entire process group (includes child processes like claude CLI spawns)
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Fallback to killing just the process
                os.kill(pid, signal.SIGKILL)

            unit.process_id = None
            repository.update_work_unit(unit)

            return {"success": True, "message": "Work unit process killed", "pid": pid}
        except ProcessLookupError:
            return {"success": False, "error": "Process not found"}
        except PermissionError:
            return {"success": False, "error": "Permission denied to kill process"}

    @staticmethod
    def restart_work_unit(repository: Repository, job_id: str, unit_id: str) -> Dict[str, Any]:
        """Restart a failed or killed work unit by resetting it to pending.

        Note: This only resets the unit status. The job manager must be running
        to actually pick up and process the unit again.

        Args:
            repository: Repository to query
            job_id: Job ID the unit belongs to
            unit_id: Work unit ID to restart

        Returns:
            Dict with result information
        """
        unit = repository.get_work_unit(unit_id)
        if not unit:
            return {"success": False, "error": "Work unit not found"}

        if unit.job_id != job_id:
            return {"success": False, "error": "Work unit does not belong to this job"}

        if unit.status != WorkUnitStatus.FAILED:
            return {
                "success": False,
                "error": f"Cannot restart unit with status '{unit.status.value}'. Only failed units can be restarted.",
            }

        if unit.process_id:
            try:
                os.killpg(unit.process_id, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(unit.process_id, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        job = repository.get_job(job_id)
        if job:
            job.failed_units = max(0, job.failed_units - 1)
            repository.update_job(job)

        # Reset unit to pending
        unit.status = WorkUnitStatus.PENDING
        unit.error = None
        unit.result = None
        unit.worker_id = None
        unit.assigned_at = None
        unit.started_at = None
        unit.completed_at = None
        unit.execution_time_seconds = None
        unit.process_id = None
        unit.conversation = None
        unit.rendered_prompt = None
        unit.session_id = None
        unit.cost_usd = None
        # Note: We don't reset retry_count to allow tracking total attempts
        repository.update_work_unit(unit)

        return {"success": True, "message": "Work unit reset to pending", "unit_id": unit_id}

    @staticmethod
    def resume_job(repository: Repository, job_id: str, worker_implementation: BaseWorker) -> Optional[int]:
        """Resume a paused or failed job.

        Args:
            repository: Repository to use
            job_id: Job ID to resume
            worker_implementation: Worker to use

        Returns:
            PID of new manager process, or None if job can't be resumed
        """
        job = repository.get_job(job_id)
        if not job:
            return None

        pending_units = repository.get_pending_units(job_id, limit=1)
        if not pending_units:
            return None

        status = JobExecutor.get_executor_status(repository, job_id)
        if status["status"] == "running":
            return status.get("pid")

        executor = JobExecutor(job_id, repository, worker_implementation)
        return executor.start_detached()
