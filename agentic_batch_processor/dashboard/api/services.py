"""Business logic services for the dashboard API.

Separates data access and transformation from HTTP routing.
"""

from typing import List, Optional

from ...persistence.repository import Repository
from ...core.models import WorkUnitStatus
from .schemas import (
    JobSummary,
    JobResponse,
    JobDetailResponse,
    JobListResponse,
    WorkUnitSummary,
    WorkUnitResponse,
    UnitListResponse,
    WorkerResponse,
    UnitStats,
    AggregateStats,
)


class JobService:
    """Service for job-related operations."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def list_jobs(self, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> JobListResponse:
        """List jobs with pagination.

        Args:
            status: Optional status filter
            limit: Maximum jobs to return
            offset: Pagination offset

        Returns:
            Paginated job list
        """

        jobs = self.repository.list_jobs(limit=limit + offset, status=status)
        jobs = jobs[offset : offset + limit]

        job_summaries = []
        for job in jobs:
            active_workers = self.repository.get_active_workers(job.job_id)
            job_summaries.append(self._to_job_summary(job, len(active_workers)))

        all_jobs = self.repository.list_jobs(limit=10000, status=status)

        return JobListResponse(jobs=job_summaries, total=len(all_jobs), limit=limit, offset=offset)

    def get_job_detail(self, job_id: str) -> Optional[JobDetailResponse]:
        """Get detailed job information.

        Args:
            job_id: Job identifier

        Returns:
            Job detail or None if not found
        """
        job = self.repository.get_job(job_id)
        if not job:
            return None

        workers = self.repository.get_busy_workers(job_id)
        worker_responses = [self._to_worker_response(worker, job.name) for worker in workers]

        recent_units = self._get_recent_units(job_id)

        unit_stats = self._get_unit_stats(job_id)

        total_cost = self.repository.get_job_total_cost(job_id)
        job_response = JobResponse(
            job_id=job.job_id,
            name=job.name,
            description=job.description,
            status=job.status.value,
            worker_prompt_template=job.worker_prompt_template,
            unit_type=job.unit_type,
            total_units=job.total_units,
            completed_units=job.completed_units,
            failed_units=job.failed_units,
            max_workers=job.max_workers,
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            metadata=job.metadata,
            total_cost_usd=total_cost,
            test_unit_id=job.test_unit_id,
        )

        return JobDetailResponse(
            job=job_response, workers=worker_responses, recent_units=recent_units, unit_stats=unit_stats
        )

    def _to_job_summary(self, job, active_workers_count: int) -> JobSummary:
        """Convert job to summary."""
        total_cost = self.repository.get_job_total_cost(job.job_id)
        return JobSummary(
            job_id=job.job_id,
            name=job.name,
            status=job.status.value,
            total_units=job.total_units,
            completed_units=job.completed_units,
            failed_units=job.failed_units,
            progress_percentage=job.progress_percentage(),
            created_at=job.created_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            active_workers=active_workers_count,
            total_cost_usd=total_cost,
        )

    def _to_worker_response(self, worker, job_name: str) -> WorkerResponse:
        """Convert worker to response."""
        current_unit_payload = None
        if worker.current_unit_id:
            unit = self.repository.get_work_unit(worker.current_unit_id)
            if unit:
                current_unit_payload = unit.payload

        return WorkerResponse(
            worker_id=worker.worker_id,
            job_id=worker.job_id,
            job_name=job_name,
            status=worker.status.value,
            current_unit_id=worker.current_unit_id,
            current_unit_payload=current_unit_payload,
            units_completed=worker.units_completed,
            units_failed=worker.units_failed,
            started_at=worker.started_at.isoformat(),
            last_heartbeat=worker.last_heartbeat.isoformat() if worker.last_heartbeat else None,
        )

    def _get_recent_units(self, job_id: str, limit: int = 10) -> List[WorkUnitSummary]:
        """Get recently completed/failed/processing units."""

        processing = self.repository.get_units_for_job(job_id, status=WorkUnitStatus.PROCESSING.value, limit=10)
        completed = self.repository.get_units_for_job(job_id, status=WorkUnitStatus.COMPLETED.value, limit=limit)
        failed = self.repository.get_units_for_job(job_id, status=WorkUnitStatus.FAILED.value, limit=5)

        recent_units = []
        for unit in processing + completed + failed:
            recent_units.append(
                WorkUnitSummary(
                    unit_id=unit.unit_id,
                    status=unit.status.value,
                    payload=unit.payload,
                    worker_id=unit.worker_id,
                    started_at=unit.started_at.isoformat() if unit.started_at else None,
                    completed_at=unit.completed_at.isoformat() if unit.completed_at else None,
                    execution_time_seconds=unit.execution_time_seconds,
                    retry_count=unit.retry_count,
                    error=unit.error,
                )
            )

        recent_units.sort(key=lambda u: u.completed_at or u.started_at or "", reverse=True)
        return recent_units[:limit]

    def _get_unit_stats(self, job_id: str) -> UnitStats:
        """Get unit status counts."""
        status_counts = self.repository.count_units_by_status(job_id)
        return UnitStats(
            pending=status_counts.get(WorkUnitStatus.PENDING.value, 0),
            assigned=status_counts.get(WorkUnitStatus.ASSIGNED.value, 0),
            processing=status_counts.get(WorkUnitStatus.PROCESSING.value, 0),
            completed=status_counts.get(WorkUnitStatus.COMPLETED.value, 0),
            failed=status_counts.get(WorkUnitStatus.FAILED.value, 0),
        )


class WorkUnitService:
    """Service for work unit operations."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def list_units(
        self, job_id: str, status: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> Optional[UnitListResponse]:
        """List work units for a job.

        Args:
            job_id: Job identifier
            status: Optional status filter
            limit: Maximum units to return
            offset: Pagination offset

        Returns:
            Unit list or None if job not found
        """
        job = self.repository.get_job(job_id)
        if not job:
            return None

        units = self.repository.get_units_for_job(job_id, status=status, limit=limit, offset=offset)

        unit_summaries = [self._to_unit_summary(unit) for unit in units]

        status_counts = self.repository.count_units_by_status(job_id)
        if status:
            total = status_counts.get(status, 0)
        else:
            total = sum(status_counts.values())

        # Always fetch and include post-processing unit if it exists
        post_processing_unit = None
        if job.post_processing_unit_id:
            pp_unit = self.repository.get_work_unit(job.post_processing_unit_id)
            if pp_unit:
                post_processing_unit = self._to_unit_summary(pp_unit)

        return UnitListResponse(
            units=unit_summaries,
            total=total,
            limit=limit,
            offset=offset,
            post_processing_unit=post_processing_unit,
        )

    def get_unit_detail(self, job_id: str, unit_id: str) -> Optional[WorkUnitResponse]:
        """Get detailed work unit with conversation.

        Args:
            job_id: Job identifier
            unit_id: Unit identifier

        Returns:
            Unit detail or None if not found
        """
        unit = self.repository.get_work_unit(unit_id)
        if not unit or unit.job_id != job_id:
            return None

        return WorkUnitResponse(
            unit_id=unit.unit_id,
            job_id=unit.job_id,
            status=unit.status.value,
            payload=unit.payload,
            rendered_prompt=unit.rendered_prompt,
            worker_id=unit.worker_id,
            started_at=unit.started_at.isoformat() if unit.started_at else None,
            completed_at=unit.completed_at.isoformat() if unit.completed_at else None,
            execution_time_seconds=unit.execution_time_seconds,
            retry_count=unit.retry_count,
            error=unit.error,
            result=unit.result,
            conversation=unit.conversation,
            session_id=unit.session_id,
            cost_usd=unit.cost_usd,
        )

    def _to_unit_summary(self, unit) -> WorkUnitSummary:
        """Convert unit to summary."""
        return WorkUnitSummary(
            unit_id=unit.unit_id,
            status=unit.status.value,
            payload=unit.payload,
            worker_id=unit.worker_id,
            started_at=unit.started_at.isoformat() if unit.started_at else None,
            completed_at=unit.completed_at.isoformat() if unit.completed_at else None,
            execution_time_seconds=unit.execution_time_seconds,
            retry_count=unit.retry_count,
            error=unit.error,
        )


class WorkerService:
    """Service for worker operations."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def get_all_active_workers(self) -> List[WorkerResponse]:
        """Get all active workers across running jobs.

        Returns:
            List of active workers
        """
        jobs = self.repository.list_jobs(limit=100, status="running")

        all_workers = []
        for job in jobs:
            workers = self.repository.get_active_workers(job.job_id)
            for worker in workers:
                current_unit_payload = None
                if worker.current_unit_id:
                    unit = self.repository.get_work_unit(worker.current_unit_id)
                    if unit:
                        current_unit_payload = unit.payload

                all_workers.append(
                    WorkerResponse(
                        worker_id=worker.worker_id,
                        job_id=worker.job_id,
                        job_name=job.name,
                        status=worker.status.value,
                        current_unit_id=worker.current_unit_id,
                        current_unit_payload=current_unit_payload,
                        units_completed=worker.units_completed,
                        units_failed=worker.units_failed,
                        started_at=worker.started_at.isoformat(),
                        last_heartbeat=worker.last_heartbeat.isoformat() if worker.last_heartbeat else None,
                    )
                )

        return all_workers


class StatsService:
    """Service for aggregate statistics."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def get_aggregate_stats(self) -> AggregateStats:
        """Get aggregate statistics across all jobs.

        Returns:
            Aggregate statistics
        """
        all_jobs = self.repository.list_jobs(limit=10000)

        total_jobs = len(all_jobs)
        active_jobs = sum(1 for j in all_jobs if j.status.value == "running")

        total_processed = sum(j.completed_units for j in all_jobs)
        total_failed = sum(j.failed_units for j in all_jobs)

        success_rate = 0.0
        if total_processed + total_failed > 0:
            success_rate = (total_processed / (total_processed + total_failed)) * 100

        active_workers = 0
        for job in all_jobs:
            if job.status.value == "running":
                workers = self.repository.get_active_workers(job.job_id)
                active_workers += len(workers)

        avg_exec_time = self._calculate_avg_execution_time(all_jobs[:10])

        return AggregateStats(
            total_jobs=total_jobs,
            active_jobs=active_jobs,
            total_units_processed=total_processed,
            total_units_failed=total_failed,
            success_rate=round(success_rate, 1),
            active_workers=active_workers,
            avg_unit_execution_time=round(avg_exec_time, 1) if avg_exec_time else None,
        )

    def _calculate_avg_execution_time(self, jobs) -> Optional[float]:
        """Calculate average execution time from job samples."""
        exec_times = []
        for job in jobs:
            units = self.repository.get_units_for_job(job.job_id, status=WorkUnitStatus.COMPLETED.value, limit=50)
            for unit in units:
                if unit.execution_time_seconds:
                    exec_times.append(unit.execution_time_seconds)

        if exec_times:
            return sum(exec_times) / len(exec_times)
        return None
