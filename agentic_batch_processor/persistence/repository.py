"""SQLite repository for agentic batch processing state.

Provides persistent storage for:
- Jobs and their configuration
- Work units and their status (including conversation history)
- Worker processes and their state
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..config import (
    DEFAULT_STORAGE_DIR,
    DEFAULT_DB_FILENAME,
    DEFAULT_DB_TIMEOUT,
    DEFAULT_JOB_LIST_LIMIT,
    DEFAULT_UNIT_LIST_LIMIT,
    DEFAULT_LOG_LIST_LIMIT,
    PREVIEW_TEXT_LIMIT,
    PREVIEW_INPUT_LIMIT,
)
from ..core.models import Job, WorkUnit, WorkerProcess, JobStatus, WorkUnitStatus, WorkerStatus


class Repository:
    """SQLite-based persistence layer for batch processing."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize repository.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.agentic-batch/batch.db
        """
        if db_path is None:
            db_path = Path.home() / DEFAULT_STORAGE_DIR / DEFAULT_DB_FILENAME

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Get database connection with proper configuration."""
        conn = sqlite3.connect(str(self.db_path), timeout=DEFAULT_DB_TIMEOUT)
        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database schema."""
        with self._get_connection() as conn:

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    worker_prompt_template TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    total_units INTEGER NOT NULL,
                    completed_units INTEGER DEFAULT 0,
                    failed_units INTEGER DEFAULT 0,
                    max_workers INTEGER DEFAULT 4,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    test_unit_id TEXT,
                    test_passed INTEGER DEFAULT 0,
                    output_strategy TEXT DEFAULT 'individual',
                    metadata TEXT
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_units (
                    unit_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    assigned_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    worker_id TEXT,
                    result TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    execution_time_seconds REAL,
                    output_files TEXT,
                    rendered_prompt TEXT,
                    conversation TEXT,
                    session_id TEXT,
                    cost_usd REAL,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    job_id TEXT,
                    current_unit_id TEXT,
                    process_id INTEGER,
                    started_at TEXT NOT NULL,
                    last_heartbeat TEXT,
                    units_completed INTEGER DEFAULT 0,
                    units_failed INTEGER DEFAULT 0,
                    total_execution_time REAL DEFAULT 0.0
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    worker_id TEXT,
                    unit_id TEXT,
                    extra TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
                )
            """
            )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_work_units_job_id ON work_units(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_work_units_status ON work_units(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_work_units_worker_id ON work_units(worker_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workers_job_id ON workers(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_job_id ON logs(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)")

            self._migrate_schema(conn)

    def _migrate_schema(self, conn):
        """Add new columns to existing databases if they don't exist."""

        cursor = conn.execute("PRAGMA table_info(work_units)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        new_columns = [
            ("rendered_prompt", "TEXT"),
            ("conversation", "TEXT"),
            ("session_id", "TEXT"),
            ("cost_usd", "REAL"),
            ("process_id", "INTEGER"),
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                conn.execute(f"ALTER TABLE work_units ADD COLUMN {col_name} {col_type}")

        cursor = conn.execute("PRAGMA table_info(jobs)")
        existing_job_columns = {row["name"] for row in cursor.fetchall()}

        new_job_columns = [
            ("post_processing_prompt", "TEXT"),
            ("post_processing_unit_id", "TEXT"),
            ("bypass_failures", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_type in new_job_columns:
            if col_name not in existing_job_columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")

    def create_job(self, job: Job) -> bool:
        """Create a new job."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        job_id, name, description, status, worker_prompt_template,
                        unit_type, total_units, completed_units, failed_units,
                        max_workers, created_at, started_at, completed_at,
                        test_unit_id, test_passed, output_strategy,
                        metadata, post_processing_prompt, post_processing_unit_id,
                        bypass_failures
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        job.job_id,
                        job.name,
                        job.description,
                        job.status.value,
                        job.worker_prompt_template,
                        job.unit_type,
                        job.total_units,
                        job.completed_units,
                        job.failed_units,
                        job.max_workers,
                        job.created_at.isoformat(),
                        job.started_at.isoformat() if job.started_at else None,
                        job.completed_at.isoformat() if job.completed_at else None,
                        job.test_unit_id,
                        int(job.test_passed),
                        job.output_strategy,
                        json.dumps(job.metadata),
                        job.post_processing_prompt,
                        job.post_processing_unit_id,
                        int(job.bypass_failures),
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def update_job(self, job: Job) -> bool:
        """Update an existing job."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE jobs SET
                        status = ?, completed_units = ?, failed_units = ?,
                        started_at = ?, completed_at = ?, test_unit_id = ?,
                        test_passed = ?, metadata = ?,
                        post_processing_prompt = ?, post_processing_unit_id = ?,
                        bypass_failures = ?
                    WHERE job_id = ?
                """,
                    (
                        job.status.value,
                        job.completed_units,
                        job.failed_units,
                        job.started_at.isoformat() if job.started_at else None,
                        job.completed_at.isoformat() if job.completed_at else None,
                        job.test_unit_id,
                        int(job.test_passed),
                        json.dumps(job.metadata),
                        job.post_processing_prompt,
                        job.post_processing_unit_id,
                        int(job.bypass_failures),
                        job.job_id,
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def list_jobs(self, limit: int = DEFAULT_JOB_LIST_LIMIT, status: Optional[str] = None) -> List[Job]:
        """List recent jobs, optionally filtered by status."""
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (limit,),
                ).fetchall()
            return [self._row_to_job(row) for row in rows]

    def create_work_unit(self, unit: WorkUnit) -> bool:
        """Create a new work unit."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO work_units (
                        unit_id, job_id, unit_type, status, payload,
                        created_at, assigned_at, started_at, completed_at,
                        worker_id, result, error, retry_count, max_retries,
                        execution_time_seconds, output_files,
                        rendered_prompt, conversation, session_id, cost_usd
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        unit.unit_id,
                        unit.job_id,
                        unit.unit_type,
                        unit.status.value,
                        json.dumps(unit.payload),
                        unit.created_at.isoformat(),
                        unit.assigned_at.isoformat() if unit.assigned_at else None,
                        unit.started_at.isoformat() if unit.started_at else None,
                        unit.completed_at.isoformat() if unit.completed_at else None,
                        unit.worker_id,
                        json.dumps(unit.result) if unit.result else None,
                        unit.error,
                        unit.retry_count,
                        unit.max_retries,
                        unit.execution_time_seconds,
                        json.dumps(unit.output_files),
                        unit.rendered_prompt,
                        json.dumps(unit.conversation) if unit.conversation else None,
                        unit.session_id,
                        unit.cost_usd,
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def get_work_unit(self, unit_id: str) -> Optional[WorkUnit]:
        """Get a work unit by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM work_units WHERE unit_id = ?", (unit_id,)).fetchone()
            if not row:
                return None
            return self._row_to_work_unit(row)

    def update_work_unit(self, unit: WorkUnit) -> bool:
        """Update an existing work unit."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE work_units SET
                        status = ?, assigned_at = ?, started_at = ?, completed_at = ?,
                        worker_id = ?, result = ?, error = ?, retry_count = ?,
                        execution_time_seconds = ?, output_files = ?,
                        rendered_prompt = ?, conversation = ?, session_id = ?, cost_usd = ?,
                        process_id = ?
                    WHERE unit_id = ?
                """,
                    (
                        unit.status.value,
                        unit.assigned_at.isoformat() if unit.assigned_at else None,
                        unit.started_at.isoformat() if unit.started_at else None,
                        unit.completed_at.isoformat() if unit.completed_at else None,
                        unit.worker_id,
                        json.dumps(unit.result) if unit.result else None,
                        unit.error,
                        unit.retry_count,
                        unit.execution_time_seconds,
                        json.dumps(unit.output_files),
                        unit.rendered_prompt,
                        json.dumps(unit.conversation) if unit.conversation else None,
                        unit.session_id,
                        unit.cost_usd,
                        unit.process_id,
                        unit.unit_id,
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def get_pending_units(self, job_id: str, limit: int = 10) -> List[WorkUnit]:
        """Get pending work units for a job."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM work_units
                WHERE job_id = ? AND status = ?
                ORDER BY created_at
                LIMIT ?
            """,
                (job_id, WorkUnitStatus.PENDING.value, limit),
            ).fetchall()
            return [self._row_to_work_unit(row) for row in rows]

    def get_units_for_job(
        self, job_id: str, status: Optional[str] = None, limit: int = DEFAULT_UNIT_LIST_LIMIT, offset: int = 0
    ) -> List[WorkUnit]:
        """Get work units for a job with pagination."""
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM work_units
                    WHERE job_id = ? AND status = ?
                    ORDER BY created_at
                    LIMIT ? OFFSET ?
                """,
                    (job_id, status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM work_units
                    WHERE job_id = ?
                    ORDER BY created_at
                    LIMIT ? OFFSET ?
                """,
                    (job_id, limit, offset),
                ).fetchall()
            return [self._row_to_work_unit(row) for row in rows]

    def count_units_by_status(self, job_id: str) -> Dict[str, int]:
        """Get count of work units by status for a job."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM work_units
                WHERE job_id = ?
                GROUP BY status
            """,
                (job_id,),
            ).fetchall()
            return {row["status"]: row["count"] for row in rows}

    def create_worker(self, worker: WorkerProcess) -> bool:
        """Create a new worker."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO workers (
                        worker_id, status, job_id, current_unit_id,
                        process_id, started_at, last_heartbeat,
                        units_completed, units_failed, total_execution_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        worker.worker_id,
                        worker.status.value,
                        worker.job_id,
                        worker.current_unit_id,
                        worker.process_id,
                        worker.started_at.isoformat(),
                        worker.last_heartbeat.isoformat() if worker.last_heartbeat else None,
                        worker.units_completed,
                        worker.units_failed,
                        worker.total_execution_time,
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def update_worker(self, worker: WorkerProcess) -> bool:
        """Update an existing worker."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE workers SET
                        status = ?, job_id = ?, current_unit_id = ?,
                        last_heartbeat = ?, units_completed = ?,
                        units_failed = ?, total_execution_time = ?
                    WHERE worker_id = ?
                """,
                    (
                        worker.status.value,
                        worker.job_id,
                        worker.current_unit_id,
                        worker.last_heartbeat.isoformat() if worker.last_heartbeat else None,
                        worker.units_completed,
                        worker.units_failed,
                        worker.total_execution_time,
                        worker.worker_id,
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def get_active_workers(self, job_id: str) -> List[WorkerProcess]:
        """Get all active workers for a job."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workers
                WHERE job_id = ? AND status IN (?, ?)
            """,
                (job_id, WorkerStatus.IDLE.value, WorkerStatus.BUSY.value),
            ).fetchall()
            return [self._row_to_worker(row) for row in rows]

    def get_busy_workers(self, job_id: str) -> List[WorkerProcess]:
        """Get workers currently processing units."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workers
                WHERE job_id = ? AND status = ?
            """,
                (job_id, WorkerStatus.BUSY.value),
            ).fetchall()
            return [self._row_to_worker(row) for row in rows]

    def cleanup_stale_workers(self, job_id: str) -> int:
        """Mark all busy/idle workers as terminated for a job.

        Called when job manager starts to clean up stale workers from
        previous crashed runs.

        Args:
            job_id: Job ID to clean up workers for

        Returns:
            Number of workers cleaned up
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE workers
                SET status = ?
                WHERE job_id = ? AND status IN (?, ?)
            """,
                (WorkerStatus.TERMINATED.value, job_id, WorkerStatus.BUSY.value, WorkerStatus.IDLE.value),
            )
            conn.commit()
            return cursor.rowcount

    def reset_stuck_units(self, job_id: str) -> int:
        """Reset units that are stuck in ASSIGNED or PROCESSING state.

        Called when job manager starts to reset units from previous
        crashed runs back to PENDING.

        Args:
            job_id: Job ID to reset units for

        Returns:
            Number of units reset
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE work_units
                SET status = ?, worker_id = NULL, assigned_at = NULL, started_at = NULL
                WHERE job_id = ? AND status IN (?, ?)
            """,
                (WorkUnitStatus.PENDING.value, job_id, WorkUnitStatus.ASSIGNED.value, WorkUnitStatus.PROCESSING.value),
            )
            conn.commit()
            return cursor.rowcount

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert database row to Job object."""
        post_processing_prompt = row["post_processing_prompt"] if "post_processing_prompt" in row.keys() else None
        post_processing_unit_id = row["post_processing_unit_id"] if "post_processing_unit_id" in row.keys() else None
        bypass_failures = bool(row["bypass_failures"]) if "bypass_failures" in row.keys() else False

        return Job(
            job_id=row["job_id"],
            name=row["name"],
            description=row["description"],
            status=JobStatus(row["status"]),
            worker_prompt_template=row["worker_prompt_template"],
            unit_type=row["unit_type"],
            total_units=row["total_units"],
            completed_units=row["completed_units"],
            failed_units=row["failed_units"],
            max_workers=row["max_workers"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            test_unit_id=row["test_unit_id"],
            test_passed=bool(row["test_passed"]),
            output_strategy=row["output_strategy"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            post_processing_prompt=post_processing_prompt,
            post_processing_unit_id=post_processing_unit_id,
            bypass_failures=bypass_failures,
        )

    def _row_to_work_unit(self, row: sqlite3.Row) -> WorkUnit:
        """Convert database row to WorkUnit object."""

        rendered_prompt = row["rendered_prompt"] if "rendered_prompt" in row.keys() else None
        conversation = (
            json.loads(row["conversation"]) if ("conversation" in row.keys() and row["conversation"]) else None
        )
        session_id = row["session_id"] if "session_id" in row.keys() else None
        cost_usd = row["cost_usd"] if "cost_usd" in row.keys() else None
        process_id = row["process_id"] if "process_id" in row.keys() else None

        return WorkUnit(
            unit_id=row["unit_id"],
            job_id=row["job_id"],
            unit_type=row["unit_type"],
            status=WorkUnitStatus(row["status"]),
            payload=json.loads(row["payload"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            assigned_at=datetime.fromisoformat(row["assigned_at"]) if row["assigned_at"] else None,
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            worker_id=row["worker_id"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            execution_time_seconds=row["execution_time_seconds"],
            output_files=json.loads(row["output_files"]) if row["output_files"] else [],
            rendered_prompt=rendered_prompt,
            conversation=conversation,
            session_id=session_id,
            cost_usd=cost_usd,
            process_id=process_id,
        )

    def _row_to_worker(self, row: sqlite3.Row) -> WorkerProcess:
        """Convert database row to WorkerProcess object."""
        return WorkerProcess(
            worker_id=row["worker_id"],
            status=WorkerStatus(row["status"]),
            job_id=row["job_id"],
            current_unit_id=row["current_unit_id"],
            process_id=row["process_id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            last_heartbeat=datetime.fromisoformat(row["last_heartbeat"]) if row["last_heartbeat"] else None,
            units_completed=row["units_completed"],
            units_failed=row["units_failed"],
            total_execution_time=row["total_execution_time"],
        )

    def add_log(
        self,
        job_id: str,
        source: str,
        level: str,
        message: str,
        worker_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Add a log entry.

        Args:
            job_id: Job this log belongs to
            source: Log source (e.g., "manager", "worker", "pool")
            level: Log level (e.g., "info", "warning", "error", "debug")
            message: Log message
            worker_id: Optional worker ID
            unit_id: Optional work unit ID
            extra: Optional extra data as dict

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO logs (job_id, source, level, message, timestamp, worker_id, unit_id, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        job_id,
                        source,
                        level,
                        message,
                        datetime.now().isoformat(),
                        worker_id,
                        unit_id,
                        json.dumps(extra) if extra else None,
                    ),
                )
            return True
        except sqlite3.Error:
            return False

    def get_logs(
        self,
        job_id: str,
        source: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = DEFAULT_LOG_LIST_LIMIT,
        offset: int = 0,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get logs for a job.

        Args:
            job_id: Job ID
            source: Optional filter by source
            level: Optional filter by level
            limit: Maximum logs to return
            offset: Pagination offset
            since: Optional ISO timestamp to get logs after

        Returns:
            List of log entries as dicts
        """
        with self._get_connection() as conn:
            query = "SELECT * FROM logs WHERE job_id = ?"
            params = [job_id]

            if source:
                query += " AND source = ?"
                params.append(source)

            if level:
                query += " AND level = ?"
                params.append(level)

            if since:
                query += " AND timestamp > ?"
                params.append(since)

            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()

            return [
                {
                    "id": row["id"],
                    "job_id": row["job_id"],
                    "source": row["source"],
                    "level": row["level"],
                    "message": row["message"],
                    "timestamp": row["timestamp"],
                    "worker_id": row["worker_id"],
                    "unit_id": row["unit_id"],
                    "extra": json.loads(row["extra"]) if row["extra"] else None,
                }
                for row in rows
            ]

    def get_log_count(self, job_id: str) -> int:
        """Get total log count for a job."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM logs WHERE job_id = ?", (job_id,)).fetchone()
            return row["count"] if row else 0

    def append_conversation_event(self, unit_id: str, event: Dict[str, Any]) -> bool:
        """Append a conversation event to a work unit in real-time.

        This enables streaming conversation updates as the worker processes,
        rather than waiting until completion to save the full conversation.

        Args:
            unit_id: Work unit ID
            event: Conversation event to append

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:

                row = conn.execute("SELECT conversation FROM work_units WHERE unit_id = ?", (unit_id,)).fetchone()

                if row is None:
                    return False

                current = json.loads(row["conversation"]) if row["conversation"] else []
                current.append(event)

                conn.execute("UPDATE work_units SET conversation = ? WHERE unit_id = ?", (json.dumps(current), unit_id))
            return True
        except sqlite3.Error:
            return False

    def set_work_unit_session_id(self, unit_id: str, session_id: str) -> bool:
        """Set the session ID for a work unit when streaming starts.

        Args:
            unit_id: Work unit ID
            session_id: Claude CLI session ID

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE work_units SET session_id = ? WHERE unit_id = ?", (session_id, unit_id))
            return True
        except sqlite3.Error:
            return False

    def set_work_unit_process_id(self, unit_id: str, process_id: Optional[int]) -> bool:
        """Set the process ID for a work unit (subprocess PID).

        Args:
            unit_id: Work unit ID
            process_id: PID of the subprocess executing this unit, or None to clear

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE work_units SET process_id = ? WHERE unit_id = ?", (process_id, unit_id))
            return True
        except sqlite3.Error:
            return False

    def get_job_total_cost(self, job_id: str) -> Optional[float]:
        """Get total cost for all work units in a job.

        Args:
            job_id: Job ID to query

        Returns:
            Total cost in USD, or None if no costs recorded
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT SUM(cost_usd) as total FROM work_units WHERE job_id = ? AND cost_usd IS NOT NULL",
                (job_id,),
            ).fetchone()
            return row["total"] if row and row["total"] else None

    def _extract_latest_event(self, conversation_json: Optional[str]) -> Optional[Dict[str, Any]]:
        """Extract the latest meaningful event from a conversation JSON string.

        Args:
            conversation_json: JSON string of conversation events

        Returns:
            Dict with event type and content preview, or None
        """
        if not conversation_json:
            return None

        try:
            conversation = json.loads(conversation_json)
        except json.JSONDecodeError:
            return None

        if not conversation:
            return None

        for event in reversed(conversation):
            if event.get("type") != "assistant":
                continue

            content = event.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue

            for block in reversed(content):
                if block.get("type") == "text" and block.get("text"):
                    return {"type": "text", "content": block["text"][:PREVIEW_TEXT_LIMIT]}
                elif block.get("type") == "tool_use":
                    return {
                        "type": "tool_use",
                        "tool": block.get("name", "unknown"),
                        "input_preview": str(block.get("input", {}))[:PREVIEW_INPUT_LIMIT],
                    }

        return None

    def get_active_units_with_latest_conversation(self, job_id: str) -> List[Dict[str, Any]]:
        """Get active work units with their latest conversation snippet.

        Returns processing/assigned units with just the most recent conversation
        event for live activity display.

        Args:
            job_id: Job ID to query

        Returns:
            List of dicts with unit_id, payload, status, process_id, and latest_event
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT unit_id, payload, status, process_id, conversation
                FROM work_units
                WHERE job_id = ? AND status IN ('processing', 'assigned')
                ORDER BY started_at DESC
                """,
                (job_id,),
            ).fetchall()

            results = []
            for row in rows:
                latest_event = self._extract_latest_event(row["conversation"])
                results.append(
                    {
                        "unit_id": row["unit_id"],
                        "payload": json.loads(row["payload"]) if row["payload"] else {},
                        "status": row["status"],
                        "process_id": row["process_id"],
                        "latest_event": latest_event,
                    }
                )

            return results
