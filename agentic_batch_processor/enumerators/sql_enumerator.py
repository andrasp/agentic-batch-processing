"""SQL-based enumerator for database queries.

Enumerates items from SQL databases. Currently supports SQLite with
extensibility for other databases.
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseEnumerator, EnumeratorResult
from .registry import register_enumerator


@register_enumerator
class SqlEnumerator(BaseEnumerator):
    """Enumerate items from SQL database queries.

    Configuration:
        connection_string: Database connection string
            - SQLite: "sqlite:///path/to/db.sqlite" or just "/path/to/db.sqlite"
        query: SQL SELECT query to execute
        id_column: Column name to use as item identifier (optional)
        params: Query parameters (optional, for parameterized queries)

    Each enumerated item has payload with columns from query result:
        {
            "column1": value1,
            "column2": value2,
            ...
            "_row_index": 0  # Row index in result set
        }

    Note: The query should return all data needed by workers.
    Workers will receive the row data as-is (not re-query the database).
    """

    enumerator_type = "sql"
    description = "Enumerate items from SQL database queries"

    def __init__(self, config: Dict[str, Any]):
        """Initialize SQL enumerator.

        Args:
            config: Configuration with connection_string and query
        """
        self.connection_string = config.get("connection_string", "")
        self.query = config.get("query", "")
        self.id_column = config.get("id_column")
        self.params = config.get("params", [])
        self.limit = config.get("limit")

    def validate_config(self) -> Optional[str]:
        """Validate configuration."""
        if not self.connection_string:
            return "connection_string is required"

        if not self.query:
            return "query is required"

        query_upper = self.query.strip().upper()
        if not query_upper.startswith("SELECT"):
            return "Only SELECT queries are allowed"

        dangerous = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
        for keyword in dangerous:
            if keyword in query_upper:
                return f"Query contains forbidden keyword: {keyword}"

        return None

    def _get_sqlite_path(self) -> str:
        """Extract SQLite database path from connection string."""
        conn = self.connection_string

        if conn.startswith("sqlite:///"):
            return conn[10:]

        if conn.startswith("sqlite://"):
            return conn[9:]

        return conn

    def enumerate(self) -> EnumeratorResult:
        """Execute query and enumerate results."""

        error = self.validate_config()
        if error:
            return EnumeratorResult(success=False, error=error)

        try:
            db_path = self._get_sqlite_path()

            if not Path(db_path).exists():
                return EnumeratorResult(success=False, error=f"Database file not found: {db_path}")

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            try:
                cursor = conn.cursor()

                query = self.query
                if self.limit:

                    if "LIMIT" not in query.upper():
                        query = f"{query} LIMIT {self.limit}"

                if self.params:
                    cursor.execute(query, self.params)
                else:
                    cursor.execute(query)

                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

                items = []
                for idx, row in enumerate(rows):
                    item = dict(zip(columns, row))
                    item["_row_index"] = idx

                    if self.id_column and self.id_column in item:
                        item["_id"] = item[self.id_column]

                    items.append(item)

                return EnumeratorResult(
                    success=True,
                    items=items,
                    metadata={"database": db_path, "query": self.query, "columns": columns, "row_count": len(items)},
                )

            finally:
                conn.close()

        except sqlite3.Error as e:
            return EnumeratorResult(success=False, error=f"SQL error: {str(e)}")
        except Exception as e:
            return EnumeratorResult(success=False, error=f"SQL enumeration failed: {str(e)}")

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
        """Get JSON schema for SQL enumerator configuration."""
        return {
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string. For SQLite: 'sqlite:///path/to/db.sqlite' or just the path",
                },
                "query": {"type": "string", "description": "SQL SELECT query to execute. Only SELECT is allowed."},
                "id_column": {
                    "type": "string",
                    "description": "Column name to use as item identifier (added as _id field)",
                },
                "params": {
                    "type": "array",
                    "items": {},
                    "description": "Query parameters for parameterized queries",
                    "default": [],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return (for testing)",
                    "minimum": 1,
                },
            },
            "required": ["connection_string", "query"],
            "additionalProperties": False,
        }
