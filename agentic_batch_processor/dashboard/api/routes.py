"""REST API routes for the dashboard.

Thin routing layer that delegates to service classes.
"""

from typing import Callable, Dict, Any, Optional

from ...config import DEFAULT_JOB_LIST_LIMIT, DEFAULT_UNIT_LIST_LIMIT, DEFAULT_LOG_LIST_LIMIT
from ...persistence.repository import Repository
from .services import JobService, WorkUnitService, WorkerService, StatsService
from .schemas import ErrorResponse


def create_api_routes(repository: Repository) -> Dict[str, Callable]:
    """Create API route handlers.

    Args:
        repository: Repository instance for database access

    Returns:
        Dictionary mapping route names to handler functions
    """

    job_service = JobService(repository)
    unit_service = WorkUnitService(repository)
    worker_service = WorkerService(repository)
    stats_service = StatsService(repository)

    def get_jobs(status: Optional[str] = None, limit: int = DEFAULT_JOB_LIST_LIMIT, offset: int = 0) -> Dict[str, Any]:
        """GET /api/jobs - List all jobs."""
        try:
            result = job_service.list_jobs(status=status, limit=limit, offset=offset)
            return result.to_dict()
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_job(job_id: str) -> Dict[str, Any]:
        """GET /api/jobs/{job_id} - Get job detail."""
        try:
            result = job_service.get_job_detail(job_id)
            if not result:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()
            return result.to_dict()
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_job_units(
        job_id: str, status: Optional[str] = None, limit: int = DEFAULT_UNIT_LIST_LIMIT, offset: int = 0
    ) -> Dict[str, Any]:
        """GET /api/jobs/{job_id}/units - Get work units for a job."""
        try:
            result = unit_service.list_units(job_id=job_id, status=status, limit=limit, offset=offset)
            if not result:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()
            return result.to_dict()
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_unit(job_id: str, unit_id: str) -> Dict[str, Any]:
        """GET /api/jobs/{job_id}/units/{unit_id} - Get unit detail with conversation."""
        try:
            result = unit_service.get_unit_detail(job_id, unit_id)
            if not result:
                return ErrorResponse(code="UNIT_NOT_FOUND", message=f"Work unit not found: {unit_id}").to_dict()
            return {"unit": result.to_dict()}
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_workers() -> Dict[str, Any]:
        """GET /api/workers - Get all active workers."""
        try:
            workers = worker_service.get_all_active_workers()
            return {"workers": [w.to_dict() for w in workers]}
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_stats() -> Dict[str, Any]:
        """GET /api/stats - Get aggregate statistics."""
        try:
            result = stats_service.get_aggregate_stats()
            return result.to_dict()
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_job_logs(
        job_id: str,
        source: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = DEFAULT_LOG_LIST_LIMIT,
        offset: int = 0,
        since: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /api/jobs/{job_id}/logs - Get logs for a job."""
        try:

            job = repository.get_job(job_id)
            if not job:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()

            logs = repository.get_logs(
                job_id=job_id, source=source, level=level, limit=limit, offset=offset, since=since
            )
            total = repository.get_log_count(job_id)

            return {"logs": logs, "total": total, "limit": limit, "offset": offset}
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_job_live_activity(job_id: str) -> Dict[str, Any]:
        """GET /api/jobs/{job_id}/live - Get live activity for active units.

        Returns the latest conversation snippet for each active (processing/assigned) unit.
        Designed for fast polling to show real-time progress.
        """
        try:
            job = repository.get_job(job_id)
            if not job:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()

            active_units = repository.get_active_units_with_latest_conversation(job_id)
            return {
                "job_id": job_id,
                "job_status": job.status.value,
                "active_units": active_units,
            }
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def get_job_executor_status(job_id: str) -> Dict[str, Any]:
        """GET /api/jobs/{job_id}/executor - Get job executor status."""
        try:
            from ...core.job_executor import JobExecutor

            job = repository.get_job(job_id)
            if not job:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()

            status = JobExecutor.get_executor_status(repository, job_id)
            return {
                "job_id": job_id,
                "job_name": job.name,
                "executor": status,
                "job_status": job.status.value,
                "metadata": job.metadata,
            }
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def bypass_failures(job_id: str) -> Dict[str, Any]:
        """POST /api/jobs/{job_id}/bypass - Enable bypass_failures and trigger post-processing.

        This endpoint sets the bypass_failures flag on the job and triggers
        post-processing to run despite failed units.
        """
        try:
            from ...core.job_executor import JobExecutor

            job = repository.get_job(job_id)
            if not job:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()

            if not job.post_processing_prompt:
                return ErrorResponse(
                    code="NO_POST_PROCESSING", message="This job has no post-processing step configured"
                ).to_dict()

            all_units_done = (job.completed_units + job.failed_units) == job.total_units
            if not all_units_done:
                return ErrorResponse(
                    code="UNITS_STILL_PROCESSING", message="Cannot bypass until all units have finished processing"
                ).to_dict()

            if job.failed_units == 0:
                return ErrorResponse(
                    code="NO_FAILURES", message="No failures to bypass - all units succeeded"
                ).to_dict()

            if job.bypass_failures:
                return ErrorResponse(
                    code="ALREADY_BYPASSED", message="Bypass has already been enabled for this job"
                ).to_dict()

            job.bypass_failures = True
            repository.update_job(job)

            return {
                "success": True,
                "job_id": job_id,
                "message": f"Bypass enabled. {job.failed_units} failed units will be ignored. Restart the job to run post-processing.",
                "failed_units": job.failed_units,
                "completed_units": job.completed_units,
            }
        except Exception as e:
            return ErrorResponse(code="DB_ERROR", message=f"Database error: {str(e)}").to_dict()

    def kill_job(job_id: str) -> Dict[str, Any]:
        """POST /api/jobs/{job_id}/kill - Kill the job executor process.

        Forcefully terminates the job executor process and all its workers.
        """
        try:
            from ...core.job_executor import JobExecutor

            result = JobExecutor.kill_executor(repository, job_id)
            if not result.get("success"):
                return ErrorResponse(code="KILL_FAILED", message=result.get("error", "Failed to kill job")).to_dict()

            return result
        except Exception as e:
            return ErrorResponse(code="SERVER_ERROR", message=f"Error killing job: {str(e)}").to_dict()

    def restart_job(job_id: str) -> Dict[str, Any]:
        """POST /api/jobs/{job_id}/restart - Restart a killed/failed job.

        Resets stuck units and restarts the job executor process.
        """
        try:
            from ...core.job_executor import JobExecutor
            from ...workers.claude_cli_worker import ClaudeCliWorkerWithFiles

            job = repository.get_job(job_id)
            if not job:
                return ErrorResponse(code="JOB_NOT_FOUND", message=f"Job not found: {job_id}").to_dict()

            status = JobExecutor.get_executor_status(repository, job_id)
            if status.get("status") == "running":
                return ErrorResponse(code="ALREADY_RUNNING", message="Job executor is already running").to_dict()

            stuck_count = repository.reset_stuck_units(job_id)

            pending_units = repository.get_pending_units(job_id, limit=1)
            if not pending_units:
                return ErrorResponse(
                    code="NO_PENDING_UNITS",
                    message="No pending units to process. All units are either completed or failed.",
                ).to_dict()

            worker = ClaudeCliWorkerWithFiles()
            pid = JobExecutor.resume_job(repository, job_id, worker)

            if pid:
                return {
                    "success": True,
                    "job_id": job_id,
                    "message": f"Job restarted successfully",
                    "executor_pid": pid,
                    "stuck_units_reset": stuck_count,
                }
            else:
                return ErrorResponse(code="RESTART_FAILED", message="Failed to restart job executor").to_dict()
        except Exception as e:
            return ErrorResponse(code="SERVER_ERROR", message=f"Error restarting job: {str(e)}").to_dict()

    def kill_unit(job_id: str, unit_id: str) -> Dict[str, Any]:
        """POST /api/jobs/{job_id}/units/{unit_id}/kill - Kill a work unit's process.

        Forcefully terminates the subprocess executing the work unit.
        """
        try:
            from ...core.job_executor import JobExecutor

            result = JobExecutor.kill_work_unit(repository, job_id, unit_id)
            if not result.get("success"):
                return ErrorResponse(
                    code="KILL_FAILED", message=result.get("error", "Failed to kill work unit")
                ).to_dict()

            return result
        except Exception as e:
            return ErrorResponse(code="SERVER_ERROR", message=f"Error killing work unit: {str(e)}").to_dict()

    def restart_unit(job_id: str, unit_id: str) -> Dict[str, Any]:
        """POST /api/jobs/{job_id}/units/{unit_id}/restart - Restart a failed work unit.

        Resets the work unit to pending state so it can be picked up again.
        """
        try:
            from ...core.job_executor import JobExecutor

            result = JobExecutor.restart_work_unit(repository, job_id, unit_id)
            if not result.get("success"):
                return ErrorResponse(
                    code="RESTART_FAILED", message=result.get("error", "Failed to restart work unit")
                ).to_dict()

            return result
        except Exception as e:
            return ErrorResponse(code="SERVER_ERROR", message=f"Error restarting work unit: {str(e)}").to_dict()

    return {
        "get_jobs": get_jobs,
        "get_job": get_job,
        "get_job_units": get_job_units,
        "get_unit": get_unit,
        "get_workers": get_workers,
        "get_stats": get_stats,
        "get_job_logs": get_job_logs,
        "get_job_live_activity": get_job_live_activity,
        "get_job_executor_status": get_job_executor_status,
        "bypass_failures": bypass_failures,
        "kill_job": kill_job,
        "restart_job": restart_job,
        "kill_unit": kill_unit,
        "restart_unit": restart_unit,
    }
