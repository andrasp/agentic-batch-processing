"""Pydantic-style schemas for API responses.

Using dataclasses instead of Pydantic to avoid dependencies.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class JobSummary:
    """Summary of a job for list views."""

    job_id: str
    name: str
    status: str
    total_units: int
    completed_units: int
    failed_units: int
    progress_percentage: float
    created_at: str
    started_at: Optional[str]
    active_workers: int = 0
    total_cost_usd: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobResponse:
    """Detailed job response."""

    job_id: str
    name: str
    description: str
    status: str
    worker_prompt_template: str
    unit_type: str
    total_units: int
    completed_units: int
    failed_units: int
    max_workers: int
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    total_cost_usd: Optional[float] = None
    test_unit_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkUnitSummary:
    """Summary of a work unit."""

    unit_id: str
    status: str
    payload: Dict[str, Any]
    worker_id: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    execution_time_seconds: Optional[float]
    retry_count: int
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkUnitResponse:
    """Detailed work unit response with conversation."""

    unit_id: str
    job_id: str
    status: str
    payload: Dict[str, Any]
    rendered_prompt: Optional[str]
    worker_id: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    execution_time_seconds: Optional[float]
    retry_count: int
    error: Optional[str]
    result: Optional[Dict[str, Any]]
    conversation: Optional[List[Dict[str, Any]]]
    session_id: Optional[str]
    cost_usd: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerResponse:
    """Worker status response."""

    worker_id: str
    job_id: Optional[str]
    job_name: Optional[str]
    status: str
    current_unit_id: Optional[str]
    current_unit_payload: Optional[Dict[str, Any]]
    units_completed: int
    units_failed: int
    started_at: str
    last_heartbeat: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnitStats:
    """Work unit statistics by status."""

    pending: int = 0
    assigned: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AggregateStats:
    """Aggregate statistics across all jobs."""

    total_jobs: int
    active_jobs: int
    total_units_processed: int
    total_units_failed: int
    success_rate: float
    active_workers: int
    avg_unit_execution_time: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobDetailResponse:
    """Full job detail with workers and recent units."""

    job: JobResponse
    workers: List[WorkerResponse]
    recent_units: List[WorkUnitSummary]
    unit_stats: UnitStats

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job": self.job.to_dict(),
            "workers": [w.to_dict() for w in self.workers],
            "recent_units": [u.to_dict() for u in self.recent_units],
            "unit_stats": self.unit_stats.to_dict(),
        }


@dataclass
class JobListResponse:
    """Paginated job list response."""

    jobs: List[JobSummary]
    total: int
    limit: int
    offset: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jobs": [j.to_dict() for j in self.jobs],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass
class UnitListResponse:
    """Paginated work unit list response."""

    units: List[WorkUnitSummary]
    total: int
    limit: int
    offset: int
    post_processing_unit: Optional[WorkUnitSummary] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "units": [u.to_dict() for u in self.units],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "post_processing_unit": self.post_processing_unit.to_dict() if self.post_processing_unit else None,
        }


@dataclass
class ErrorResponse:
    """API error response."""

    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"error": asdict(self)}
