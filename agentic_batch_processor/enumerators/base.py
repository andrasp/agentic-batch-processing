"""Base enumerator interface.

All enumerators must implement the BaseEnumerator interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EnumeratorResult:
    """Result from enumerator execution.

    Attributes:
        success: Whether enumeration succeeded
        items: List of item payloads (each is a Dict)
        total_count: Total number of items enumerated
        error: Error message if enumeration failed
        metadata: Additional metadata about the enumeration
    """

    success: bool
    items: List[Dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.success and self.total_count == 0:
            self.total_count = len(self.items)


class BaseEnumerator(ABC):
    """Abstract base class for item enumerators.

    Enumerators are responsible for:
    1. Accepting configuration from the MCP client (Claude)
    2. Enumerating items server-side (no data sent through conversation)
    3. Returning a list of item payloads for work unit creation

    Each item payload is a Dict that will be passed to workers.
    The payload structure depends on the enumerator type and should
    contain all information needed by the worker to process that item.
    """

    enumerator_type: str = "base"

    description: str = "Base enumerator"

    @abstractmethod
    def __init__(self, config: Dict[str, Any]):
        """Initialize enumerator with configuration.

        Args:
            config: Configuration dictionary from MCP client.
                   Structure depends on enumerator type.
        """
        pass

    @abstractmethod
    def enumerate(self) -> EnumeratorResult:
        """Enumerate all items.

        Returns:
            EnumeratorResult with list of item payloads
        """
        pass

    @abstractmethod
    def validate_config(self) -> Optional[str]:
        """Validate the configuration.

        Returns:
            Error message if invalid, None if valid
        """
        pass

    @classmethod
    @abstractmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get JSON schema for configuration.

        Used to document the expected configuration structure
        in MCP tool definitions.

        Returns:
            JSON schema dictionary
        """
        pass

    def get_sample_item(self) -> Optional[Dict[str, Any]]:
        """Get a sample item for testing without full enumeration.

        Useful for test runs - enumerate just one item to verify
        the configuration is correct.

        Returns:
            Single item payload, or None if not supported
        """
        result = self.enumerate()
        if result.success and result.items:
            return result.items[0]
        return None
