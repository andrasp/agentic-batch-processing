"""CSV-based enumerator.

Enumerates items from CSV files, with each row becoming a work item.
"""

import csv
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseEnumerator, EnumeratorResult
from .registry import register_enumerator


@register_enumerator
class CsvEnumerator(BaseEnumerator):
    """Enumerate items from CSV files.

    Configuration:
        file_path: Path to CSV file
        id_column: Column name to use as item identifier (optional)
        delimiter: CSV delimiter (default: ",")
        has_header: Whether file has header row (default: True)
        encoding: File encoding (default: "utf-8")
        columns: List of column names if no header (required if has_header=False)

    Each enumerated item has payload with columns from CSV:
        {
            "column1": "value1",
            "column2": "value2",
            ...
            "_row_index": 0  # Row index in CSV (0-based, excluding header)
        }
    """

    enumerator_type = "csv"
    description = "Enumerate items from CSV files"

    def __init__(self, config: Dict[str, Any]):
        """Initialize CSV enumerator.

        Args:
            config: Configuration with file_path
        """
        self.file_path = Path(config.get("file_path", ""))
        self.id_column = config.get("id_column")
        self.delimiter = config.get("delimiter", ",")
        self.has_header = config.get("has_header", True)
        self.encoding = config.get("encoding", "utf-8")
        self.columns = config.get("columns", [])
        self.limit = config.get("limit")

    def validate_config(self) -> Optional[str]:
        """Validate configuration."""
        if not self.file_path:
            return "file_path is required"

        if not self.file_path.exists():
            return f"CSV file not found: {self.file_path}"

        if not self.file_path.is_file():
            return f"Path is not a file: {self.file_path}"

        if not self.has_header and not self.columns:
            return "columns required when has_header is False"

        return None

    def enumerate(self) -> EnumeratorResult:
        """Read CSV and enumerate rows."""
        error = self.validate_config()
        if error:
            return EnumeratorResult(success=False, error=error)

        try:
            items = []

            with open(self.file_path, "r", encoding=self.encoding, newline="") as f:
                if self.has_header:
                    reader = csv.DictReader(f, delimiter=self.delimiter)
                    columns = reader.fieldnames or []
                else:
                    reader = csv.reader(f, delimiter=self.delimiter)
                    columns = self.columns

                for idx, row in enumerate(reader):

                    if isinstance(row, list):
                        if len(row) != len(columns):
                            continue
                        item = dict(zip(columns, row))
                    else:
                        item = dict(row)

                    item["_row_index"] = idx

                    if self.id_column and self.id_column in item:
                        item["_id"] = item[self.id_column]

                    items.append(item)

                    if self.limit and len(items) >= self.limit:
                        break

            return EnumeratorResult(
                success=True,
                items=items,
                metadata={"file_path": str(self.file_path), "columns": list(columns), "row_count": len(items)},
            )

        except csv.Error as e:
            return EnumeratorResult(success=False, error=f"CSV parsing error: {str(e)}")
        except Exception as e:
            return EnumeratorResult(success=False, error=f"CSV enumeration failed: {str(e)}")

    def get_sample_item(self) -> Optional[Dict[str, Any]]:
        """Get first row for testing."""
        original_limit = self.limit
        self.limit = 1

        result = self.enumerate()

        self.limit = original_limit

        if result.success and result.items:
            return result.items[0]
        return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get JSON schema for CSV enumerator configuration."""
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to CSV file"},
                "id_column": {"type": "string", "description": "Column name to use as item identifier"},
                "delimiter": {"type": "string", "description": "CSV delimiter character", "default": ","},
                "has_header": {"type": "boolean", "description": "Whether file has header row", "default": True},
                "encoding": {"type": "string", "description": "File encoding", "default": "utf-8"},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column names if no header row",
                },
                "limit": {"type": "integer", "description": "Maximum number of rows to return", "minimum": 1},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        }
