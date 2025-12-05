"""Enumerator registry for dynamic enumerator creation.

Provides factory functions to create enumerators by type name,
enabling MCP clients to specify enumerator type as a string.
"""

from typing import Any, Dict, Optional, Type

from .base import BaseEnumerator


_ENUMERATOR_REGISTRY: Dict[str, Type[BaseEnumerator]] = {}


def register_enumerator(enumerator_class: Type[BaseEnumerator]) -> Type[BaseEnumerator]:
    """Register an enumerator class.

    Can be used as a decorator:
        @register_enumerator
        class MyEnumerator(BaseEnumerator):
            enumerator_type = "my_type"
            ...

    Args:
        enumerator_class: Enumerator class to register

    Returns:
        The same class (for decorator use)
    """
    _ENUMERATOR_REGISTRY[enumerator_class.enumerator_type] = enumerator_class
    return enumerator_class


def create_enumerator(enumerator_type: str, config: Dict[str, Any]) -> BaseEnumerator:
    """Create an enumerator instance by type.

    Args:
        enumerator_type: Type identifier (e.g., "file", "sql", "csv")
        config: Configuration dictionary for the enumerator

    Returns:
        Configured enumerator instance

    Raises:
        ValueError: If enumerator type is not registered
    """
    if enumerator_type not in _ENUMERATOR_REGISTRY:
        available = ", ".join(_ENUMERATOR_REGISTRY.keys())
        raise ValueError(f"Unknown enumerator type: '{enumerator_type}'. " f"Available types: {available}")

    enumerator_class = _ENUMERATOR_REGISTRY[enumerator_type]
    return enumerator_class(config)


def get_enumerator_schema(enumerator_type: str) -> Optional[Dict[str, Any]]:
    """Get configuration schema for an enumerator type.

    Args:
        enumerator_type: Type identifier

    Returns:
        JSON schema for configuration, or None if type not found
    """
    if enumerator_type not in _ENUMERATOR_REGISTRY:
        return None

    return _ENUMERATOR_REGISTRY[enumerator_type].get_config_schema()


def get_all_enumerator_schemas() -> Dict[str, Dict[str, Any]]:
    """Get schemas for all registered enumerators.

    Returns:
        Dict mapping enumerator type to its config schema
    """
    return {
        enum_type: {
            "type": enum_type,
            "description": enum_class.description,
            "config_schema": enum_class.get_config_schema(),
        }
        for enum_type, enum_class in _ENUMERATOR_REGISTRY.items()
    }


def list_enumerator_types() -> list:
    """List all registered enumerator types.

    Returns:
        List of type identifiers
    """
    return list(_ENUMERATOR_REGISTRY.keys())
