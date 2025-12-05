"""Item enumerators for batch processing.

Enumerators are responsible for generating the list of work items to process.
Each enumerator takes configuration parameters and returns a list of item payloads.

Built-in enumerators:
- FileEnumerator: Enumerate files using glob patterns
- SqlEnumerator: Query items from SQL databases
- CsvEnumerator: Read items from CSV files
- JsonEnumerator: Read items from JSON files/arrays
- DynamicEnumerator: Execute LLM-generated Python code to enumerate items

Usage:
    from agentic_batch_processor.enumerators import create_enumerator

    # File-based enumeration
    enumerator = create_enumerator("file", {
        "base_directory": "/path/to/files",
        "pattern": "**/*.jpg"
    })
    items = enumerator.enumerate()

    # SQL-based enumeration
    enumerator = create_enumerator("sql", {
        "connection_string": "sqlite:///data.db",
        "query": "SELECT id, name, data FROM items WHERE status = 'pending'"
    })
    items = enumerator.enumerate()

    # Dynamic enumeration (LLM-generated code)
    enumerator = create_enumerator("dynamic", {
        "code": '''
def enumerate_items(context):
    import json
    # Parse pre-fetched API response from context
    data = json.loads(context["api_response"])
    return [{"item_id": item["id"], "name": item["name"]} for item in data["items"]]
''',
        "context": {"api_response": '{"items": [{"id": 1, "name": "foo"}]}'}
    })
    result = enumerator.enumerate()
"""

from .base import BaseEnumerator, EnumeratorResult
from .registry import (
    create_enumerator,
    register_enumerator,
    get_enumerator_schema,
    get_all_enumerator_schemas,
)
from .file_enumerator import FileEnumerator
from .sql_enumerator import SqlEnumerator
from .csv_enumerator import CsvEnumerator
from .json_enumerator import JsonEnumerator
from .dynamic_enumerator import DynamicEnumerator, PendingApprovalError

__all__ = [
    "BaseEnumerator",
    "EnumeratorResult",
    "create_enumerator",
    "register_enumerator",
    "get_enumerator_schema",
    "get_all_enumerator_schemas",
    "FileEnumerator",
    "SqlEnumerator",
    "CsvEnumerator",
    "JsonEnumerator",
    "DynamicEnumerator",
    "PendingApprovalError",
]
