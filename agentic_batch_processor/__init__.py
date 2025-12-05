"""Agentic Batch Processor

Framework for parallel LLM agent-based batch processing with persistent state,
automatic retries, and fault tolerance.

Key Components:
- Orchestrator: Main coordination logic
- WorkerPool: Manages parallel LLM workers
- Repository: SQLite persistence
- Workers: LLM implementations (Claude CLI, etc.)
- PromptSynthesizer: Generates per-item prompts
- JobExecutor: Detached process for resilient job execution
- Dashboard: Web-based monitoring dashboard
- MCP Server: Model Context Protocol server for Claude integration

"""

from .core.orchestrator import Orchestrator
from .core.models import Job, WorkUnit, WorkerProcess, JobStatus, WorkUnitStatus, WorkerStatus
from .core.prompt_synthesizer import PromptSynthesizer
from .core.worker_pool import WorkerPool
from .persistence.repository import Repository
from .workers.base import BaseWorker, WorkerResult
from .workers.claude_cli_worker import ClaudeCliWorker, ClaudeCliWorkerWithFiles

__version__ = "0.1.0"

__all__ = [
    "Orchestrator",
    "Job",
    "WorkUnit",
    "WorkerProcess",
    "JobStatus",
    "WorkUnitStatus",
    "WorkerStatus",
    "PromptSynthesizer",
    "WorkerPool",
    "Repository",
    "BaseWorker",
    "WorkerResult",
    "ClaudeCliWorker",
    "ClaudeCliWorkerWithFiles",
    "create_orchestrator",
]


def create_orchestrator(
    worker: BaseWorker, db_path: str = None, prompt_synthesizer: PromptSynthesizer = None
) -> Orchestrator:
    """Create an orchestrator instance.

    Args:
        worker: Worker implementation to use
        db_path: Optional path to SQLite database
        prompt_synthesizer: Optional custom prompt synthesizer

    Returns:
        Configured Orchestrator instance
    """
    from pathlib import Path

    repository = Repository(Path(db_path) if db_path else None)

    return Orchestrator(repository=repository, worker_implementation=worker, prompt_synthesizer=prompt_synthesizer)
