"""Core data models for agentic batch processing.

Defines the fundamental abstractions:
- WorkUnit: Generic unit of work (file, URL, record, etc.)
- Job: Collection of work units with shared processing logic
- WorkerStatus: Status tracking for worker processes
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List

from ..config import DEFAULT_MAX_WORKERS, DEFAULT_MAX_RETRIES


class WorkUnitStatus(Enum):
    """Status of a work unit."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(Enum):
    """Status of a job."""

    CREATED = "created"
    TESTING = "testing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkerStatus(Enum):
    """Status of a worker process."""

    IDLE = "idle"
    BUSY = "busy"
    FAILED = "failed"
    TERMINATED = "terminated"


@dataclass
class WorkUnit:
    """A single unit of work to be processed by a worker agent.

    Generic abstraction that can represent:
    - A file to process
    - A URL to fetch/analyze
    - A database record to update
    - An API call to make
    - Any discrete task
    """

    unit_id: str
    job_id: str
    unit_type: str
    status: WorkUnitStatus
    payload: Dict[str, Any]

    created_at: datetime
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    worker_id: Optional[str] = None

    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES

    execution_time_seconds: Optional[float] = None
    output_files: List[str] = field(default_factory=list)

    rendered_prompt: Optional[str] = None
    conversation: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None
    process_id: Optional[int] = None  # PID of the subprocess executing this unit

    def can_retry(self) -> bool:
        """Check if this unit can be retried."""
        return self.retry_count < self.max_retries

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "unit_id": self.unit_id,
            "job_id": self.job_id,
            "unit_type": self.unit_type,
            "status": self.status.value,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "worker_id": self.worker_id,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "execution_time_seconds": self.execution_time_seconds,
            "output_files": self.output_files,
            "rendered_prompt": self.rendered_prompt,
            "conversation": self.conversation,
            "session_id": self.session_id,
            "cost_usd": self.cost_usd,
            "process_id": self.process_id,
        }


@dataclass
class Job:
    """A job represents a collection of work units to be processed.

    Contains:
    - User's high-level intent
    - Per-item prompt template for workers
    - Configuration (parallelism, retries, etc.)
    - Progress tracking
    - Optional post-processing prompt for scatter-gather-synthesize pattern
    """

    job_id: str
    name: str
    description: str
    status: JobStatus
    worker_prompt_template: str
    unit_type: str
    total_units: int
    created_at: datetime

    completed_units: int = 0
    failed_units: int = 0
    max_workers: int = DEFAULT_MAX_WORKERS
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    test_unit_id: Optional[str] = None
    test_passed: bool = False
    output_strategy: str = "individual"
    metadata: Dict[str, Any] = field(default_factory=dict)

    post_processing_prompt: Optional[str] = None
    post_processing_unit_id: Optional[str] = None

    bypass_failures: bool = False

    def progress_percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_units == 0:
            return 0.0
        return (self.completed_units / self.total_units) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "job_id": self.job_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "worker_prompt_template": self.worker_prompt_template,
            "unit_type": self.unit_type,
            "total_units": self.total_units,
            "completed_units": self.completed_units,
            "failed_units": self.failed_units,
            "max_workers": self.max_workers,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "test_unit_id": self.test_unit_id,
            "test_passed": self.test_passed,
            "output_strategy": self.output_strategy,
            "metadata": self.metadata,
            "post_processing_prompt": self.post_processing_prompt,
            "post_processing_unit_id": self.post_processing_unit_id,
            "bypass_failures": self.bypass_failures,
        }


@dataclass
class WorkerProcess:
    """Represents the state of a worker process (LLM agent)."""

    worker_id: str
    status: WorkerStatus
    job_id: Optional[str]
    current_unit_id: Optional[str]

    process_id: Optional[int] = None

    started_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: Optional[datetime] = None

    units_completed: int = 0
    units_failed: int = 0
    total_execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "worker_id": self.worker_id,
            "status": self.status.value,
            "job_id": self.job_id,
            "current_unit_id": self.current_unit_id,
            "process_id": self.process_id,
            "started_at": self.started_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "units_completed": self.units_completed,
            "units_failed": self.units_failed,
            "total_execution_time": self.total_execution_time,
        }
