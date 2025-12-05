"""Worker pool management for agentic batch processing.

Manages a pool of LLM worker processes:
- Spawns workers up to max_workers limit
- Assigns work units to available workers
- Monitors worker health and completion
- Handles worker failures and retries
- Captures full conversation history for debugging
- Logs worker activity for debugging
"""

import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Dict, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, Future

from .models import WorkUnit, WorkerProcess, WorkerStatus, WorkUnitStatus
from ..config import DEFAULT_MAX_WORKERS, DEFAULT_WORKER_TIMEOUT
from ..workers.base import BaseWorker, WorkerResult
from ..persistence.repository import Repository


class WorkerPool:
    """Manages a pool of LLM worker processes."""

    def __init__(
        self,
        job_id: str,
        worker_implementation: BaseWorker,
        repository: Repository,
        max_workers: int = DEFAULT_MAX_WORKERS,
        on_unit_complete: Optional[Callable[[WorkUnit, WorkerResult], None]] = None,
        on_unit_failed: Optional[Callable[[WorkUnit, WorkerResult], None]] = None,
    ):
        """Initialize worker pool.

        Args:
            job_id: ID of the job this pool is working on
            worker_implementation: Worker instance to use for execution
            repository: Repository for persistence
            max_workers: Maximum concurrent workers
            on_unit_complete: Callback when unit completes successfully
            on_unit_failed: Callback when unit fails
        """
        self.job_id = job_id
        self.worker_implementation = worker_implementation
        self.repository = repository
        self.max_workers = max_workers
        self.on_unit_complete = on_unit_complete
        self.on_unit_failed = on_unit_failed

        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        self.active_workers: Dict[str, WorkerProcess] = {}
        self.active_futures: Dict[str, Future] = {}

        self.lock = threading.Lock()

        self.running = False

    def start(self):
        """Start the worker pool."""
        self.running = True

    def stop(self):
        """Stop the worker pool and wait for workers to finish."""
        self.running = False
        self.executor.shutdown(wait=True)

        with self.lock:
            for worker in self.active_workers.values():
                worker.status = WorkerStatus.TERMINATED
                self.repository.update_worker(worker)

    def submit_work_unit(self, work_unit: WorkUnit, prompt_template: str) -> bool:
        """Submit a work unit for processing.

        Args:
            work_unit: Work unit to process
            prompt_template: Prompt template for the worker

        Returns:
            True if submitted successfully, False if pool is full
        """
        with self.lock:
            if len(self.active_workers) >= self.max_workers:
                return False

            worker = WorkerProcess(
                worker_id=str(uuid.uuid4()),
                status=WorkerStatus.BUSY,
                job_id=self.job_id,
                current_unit_id=work_unit.unit_id,
                started_at=datetime.now(),
            )

            work_unit.status = WorkUnitStatus.ASSIGNED
            work_unit.worker_id = worker.worker_id
            work_unit.assigned_at = datetime.now()

            self.repository.create_worker(worker)
            self.repository.update_work_unit(work_unit)

            future = self.executor.submit(self._execute_work_unit, worker, work_unit, prompt_template)

            self.active_workers[worker.worker_id] = worker
            self.active_futures[worker.worker_id] = future

            return True

    def wait_for_available_slot(self, timeout: Optional[float] = None) -> bool:
        """Wait until a worker slot becomes available.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if slot became available, False if timed out
        """
        start_time = time.time()

        while True:
            with self.lock:
                if len(self.active_workers) < self.max_workers:
                    return True

            if timeout and (time.time() - start_time) > timeout:
                return False

            time.sleep(0.1)

    def get_active_worker_count(self) -> int:
        """Get number of currently active workers."""
        with self.lock:
            return len(self.active_workers)

    def _log(self, level: str, message: str, worker_id: str = None, unit_id: str = None, extra: Dict[str, Any] = None):
        """Log a message to the database."""
        self.repository.add_log(
            job_id=self.job_id,
            source="worker",
            level=level,
            message=message,
            worker_id=worker_id,
            unit_id=unit_id,
            extra=extra,
        )

    def _execute_work_unit(self, worker: WorkerProcess, work_unit: WorkUnit, prompt_template: str):
        """Execute a work unit (runs in worker thread).

        Args:
            worker: WorkerProcess executing this unit
            work_unit: Work unit to process
            prompt_template: Prompt template
        """
        self._log(
            "info",
            f"Worker {worker.worker_id[:8]}... starting execution of unit {work_unit.unit_id[:8]}...",
            worker_id=worker.worker_id,
            unit_id=work_unit.unit_id,
            extra={"payload_keys": list(work_unit.payload.keys()) if work_unit.payload else []},
        )

        try:

            work_unit.status = WorkUnitStatus.PROCESSING
            work_unit.started_at = datetime.now()
            self.repository.update_work_unit(work_unit)

            self._log("debug", f"Spawning claude CLI process...", worker_id=worker.worker_id, unit_id=work_unit.unit_id)

            def on_stream_event(event_type: str, event: dict):
                if event_type == "system" and event.get("subtype") == "init":

                    session_id = event.get("session_id")
                    if session_id:
                        self.repository.set_work_unit_session_id(work_unit.unit_id, session_id)
                elif event_type in ("user", "assistant", "tool_use", "tool_result"):

                    self.repository.append_conversation_event(work_unit.unit_id, event)

            def on_process_start(pid: int):
                self.repository.set_work_unit_process_id(work_unit.unit_id, pid)
                work_unit.process_id = pid

            result = self.worker_implementation.execute(
                prompt=prompt_template,
                work_unit_payload=work_unit.payload,
                timeout=DEFAULT_WORKER_TIMEOUT,
                on_stream_event=on_stream_event,
                on_process_start=on_process_start,
            )

            work_unit.completed_at = datetime.now()
            work_unit.execution_time_seconds = result.execution_time
            work_unit.output_files = result.output_files or []
            work_unit.process_id = None  # Clear PID now that process is done

            work_unit.rendered_prompt = result.rendered_prompt
            work_unit.conversation = result.conversation
            if result.metadata:
                work_unit.session_id = result.metadata.get("session_id")
                work_unit.cost_usd = result.metadata.get("total_cost_usd")

            if result.success:
                work_unit.status = WorkUnitStatus.COMPLETED
                work_unit.result = result.to_dict()

                worker.units_completed += 1
                worker.total_execution_time += result.execution_time or 0.0

                self._log(
                    "info",
                    f"Worker {worker.worker_id[:8]}... completed unit {work_unit.unit_id[:8]}... in {result.execution_time:.1f}s",
                    worker_id=worker.worker_id,
                    unit_id=work_unit.unit_id,
                    extra={
                        "execution_time": result.execution_time,
                        "cost_usd": result.metadata.get("total_cost_usd") if result.metadata else None,
                        "num_turns": result.metadata.get("num_turns") if result.metadata else None,
                    },
                )

                if self.on_unit_complete:
                    self.on_unit_complete(work_unit, result)
            else:
                work_unit.status = WorkUnitStatus.FAILED
                work_unit.error = result.error
                work_unit.result = result.to_dict()

                worker.units_failed += 1

                self._log(
                    "error",
                    f"Worker {worker.worker_id[:8]}... failed on unit {work_unit.unit_id[:8]}...: {result.error}",
                    worker_id=worker.worker_id,
                    unit_id=work_unit.unit_id,
                    extra={"error": result.error},
                )

                if self.on_unit_failed:
                    self.on_unit_failed(work_unit, result)

            self.repository.update_work_unit(work_unit)

        except Exception as e:
            error_trace = traceback.format_exc()

            work_unit.status = WorkUnitStatus.FAILED
            work_unit.error = f"Unexpected error: {str(e)}"
            work_unit.completed_at = datetime.now()
            self.repository.update_work_unit(work_unit)

            worker.units_failed += 1

            self._log(
                "error",
                f"Worker {worker.worker_id[:8]}... crashed on unit {work_unit.unit_id[:8]}...: {str(e)}",
                worker_id=worker.worker_id,
                unit_id=work_unit.unit_id,
                extra={"error": str(e), "traceback": error_trace},
            )

            if self.on_unit_failed:
                result = WorkerResult(success=False, error=str(e))
                self.on_unit_failed(work_unit, result)

        finally:

            worker.status = WorkerStatus.IDLE
            worker.current_unit_id = None
            worker.last_heartbeat = datetime.now()
            self.repository.update_worker(worker)

            with self.lock:
                self.active_workers.pop(worker.worker_id, None)
                self.active_futures.pop(worker.worker_id, None)

    def wait_for_completion(self, check_interval: float = 1.0):
        """Wait for all active workers to complete.

        Args:
            check_interval: How often to check in seconds
        """
        while True:
            with self.lock:
                if len(self.active_workers) == 0:
                    break
            time.sleep(check_interval)
