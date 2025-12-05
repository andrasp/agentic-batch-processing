"""JSON-based enumerator.

Enumerates items from JSON files, supporting both arrays and objects.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseEnumerator, EnumeratorResult
from .registry import register_enumerator


@register_enumerator
class JsonEnumerator(BaseEnumerator):
    """Enumerate items from JSON files.

    Configuration:
        file_path: Path to JSON file
        items_path: JSONPath-like expression to locate items array (optional)
            - Empty string or not set: root must be array
            - "data": items are in {"data": [...]}
            - "response.items": items are in {"response": {"items": [...]}}
        id_field: Field name to use as item identifier (optional)

    Each enumerated item has the payload from the JSON object plus:
        {
            ...original_fields,
            "_index": 0  # Index in the array
        }
    """

    enumerator_type = "json"
    description = "Enumerate items from JSON files"

    def __init__(self, config: Dict[str, Any]):
        """Initialize JSON enumerator.

        Args:
            config: Configuration with file_path
        """
        self.file_path = Path(config.get("file_path", ""))
        self.items_path = config.get("items_path", "")
        self.id_field = config.get("id_field")
        self.encoding = config.get("encoding", "utf-8")
        self.limit = config.get("limit")

    def validate_config(self) -> Optional[str]:
        """Validate configuration."""
        if not self.file_path:
            return "file_path is required"

        if not self.file_path.exists():
            return f"JSON file not found: {self.file_path}"

        if not self.file_path.is_file():
            return f"Path is not a file: {self.file_path}"

        return None

    def _get_items_at_path(self, data: Any, path: str) -> Any:
        """Navigate to items at the specified path.

        Args:
            data: Parsed JSON data
            path: Dot-separated path (e.g., "response.items")

        Returns:
            Data at the path

        Raises:
            KeyError: If path doesn't exist
            TypeError: If intermediate value is not a dict
        """
        if not path:
            return data

        current = data
        for key in path.split("."):
            if not isinstance(current, dict):
                raise TypeError(f"Cannot access '{key}' on non-object")
            if key not in current:
                raise KeyError(f"Key '{key}' not found")
            current = current[key]

        return current

    def enumerate(self) -> EnumeratorResult:
        """Read JSON and enumerate items."""
        error = self.validate_config()
        if error:
            return EnumeratorResult(success=False, error=error)

        try:
            with open(self.file_path, "r", encoding=self.encoding) as f:
                data = json.load(f)

            try:
                items_data = self._get_items_at_path(data, self.items_path)
            except (KeyError, TypeError) as e:
                return EnumeratorResult(
                    success=False, error=f"Failed to locate items at path '{self.items_path}': {str(e)}"
                )

            if not isinstance(items_data, list):
                return EnumeratorResult(success=False, error=f"Items at path '{self.items_path}' is not an array")

            items = []
            for idx, item_data in enumerate(items_data):

                if isinstance(item_data, dict):
                    item = dict(item_data)
                else:

                    item = {"value": item_data}

                item["_index"] = idx

                if self.id_field and self.id_field in item:
                    item["_id"] = item[self.id_field]

                items.append(item)

                if self.limit and len(items) >= self.limit:
                    break

            return EnumeratorResult(
                success=True,
                items=items,
                metadata={
                    "file_path": str(self.file_path),
                    "items_path": self.items_path or "(root)",
                    "item_count": len(items),
                },
            )

        except json.JSONDecodeError as e:
            return EnumeratorResult(success=False, error=f"JSON parsing error: {str(e)}")
        except Exception as e:
            return EnumeratorResult(success=False, error=f"JSON enumeration failed: {str(e)}")

    def get_sample_item(self) -> Optional[Dict[str, Any]]:
        """Get first item for testing."""
        original_limit = self.limit
        self.limit = 1

        result = self.enumerate()

        self.limit = original_limit

        if result.success and result.items:
            return result.items[0]
        return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get JSON schema for JSON enumerator configuration."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to JSON file"},
                "items_path": {
                    "type": "string",
                    "description": "Dot-separated path to items array (e.g., 'data.items'). Empty for root array.",
                    "default": "",
                },
                "id_field": {"type": "string", "description": "Field name to use as item identifier"},
                "encoding": {"type": "string", "description": "File encoding", "default": "utf-8"},
                "limit": {"type": "integer", "description": "Maximum number of items to return", "minimum": 1},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        }
