"""Base worker interface for agentic batch processing.

Defines the abstract interface that all worker implementations must follow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List


@dataclass
class WorkerResult:
    """Result from a worker execution.

    Attributes:
        success: Whether the execution completed successfully
        output: Final output text from the worker
        error: Error message if execution failed
        execution_time: Total execution time in seconds
        output_files: List of files created/modified by the worker
        metadata: Additional metadata (session_id, cost, num_turns, etc.)
        conversation: Full conversation history including tool uses
        rendered_prompt: The actual prompt sent to the worker (after template rendering)
    """

    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    output_files: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    conversation: Optional[List[Dict[str, Any]]] = None
    rendered_prompt: Optional[str] = None

    def __post_init__(self):
        """Initialize default values."""
        if self.output_files is None:
            self.output_files = []
        if self.metadata is None:
            self.metadata = {}
        if self.conversation is None:
            self.conversation = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "execution_time": self.execution_time,
            "output_files": self.output_files,
            "metadata": self.metadata,
            "conversation": self.conversation,
            "rendered_prompt": self.rendered_prompt,
        }


class BaseWorker(ABC):
    """Abstract base class for LLM workers.

    Workers are responsible for:
    1. Spawning LLM processes
    2. Feeding them prompts and work unit data
    3. Monitoring execution
    4. Capturing results and full conversation history
    """

    @abstractmethod
    def execute(self, prompt: str, work_unit_payload: Dict[str, Any], timeout: Optional[float] = None) -> WorkerResult:
        """Execute a work unit with the given prompt.

        Args:
            prompt: The prompt template to give the LLM
            work_unit_payload: Data for this specific work unit
            timeout: Optional timeout in seconds

        Returns:
            WorkerResult with success/failure, output, and conversation history
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this worker type is available on the system."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get the name of this worker type."""
        pass
