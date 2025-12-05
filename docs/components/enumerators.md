# Enumerators

Enumerators discover and list items to be processed. They convert high-level specifications (a directory path, database query, or custom logic) into concrete work units with payloads that workers can process.

## Design Philosophy

A key insight of the Agentic Batch Processor is that **enumeration happens server-side**. The LLM describes how to enumerate (configuration or code), but the actual listing happens on the server without sending thousands of items through the conversation.

This enables processing arbitrarily large datasets without token overhead. An LLM can say "process all 50,000 images in this directory" without listing them.

## Base Interface

All enumerators implement the `BaseEnumerator` interface:

| Method | Description |
|--------|-------------|
| `__init__(config)` | Initialize with configuration dictionary |
| `enumerate()` | Return EnumeratorResult with all items |
| `validate_config()` | Return error message if invalid, None if valid |
| `get_config_schema()` | Return JSON schema for configuration |
| `get_sample_item()` | Return one item for testing |

The `EnumeratorResult` dataclass contains:
- `success`: Whether enumeration succeeded
- `items`: List of payload dictionaries
- `total_count`: Number of items
- `error`: Error message if failed
- `metadata`: Additional information (column names, file counts, etc.)

## Registry System

Enumerators use a decorator-based registration system. New enumerators are registered with:

```python
@register_enumerator
class MyEnumerator(BaseEnumerator):
    enumerator_type = "my_type"
    description = "Human-readable description"
    ...
```

The registry provides factory functions:
- `create_enumerator(type, config)`: Instantiate an enumerator by type
- `get_enumerator_schema(type)`: Get configuration schema
- `get_all_enumerator_schemas()`: Get all schemas (for MCP tool discovery)
- `list_enumerator_types()`: List available types

## Built-in Enumerators

### File Enumerator

Enumerates files from the filesystem using glob patterns.

**Configuration:**
- `base_directory` (required): Root directory to search
- `pattern`: Glob pattern (default: `**/*`)
- `exclude_patterns`: Patterns to exclude
- `include_hidden`: Include dotfiles (default: false)
- `limit`: Maximum items for testing

**Payload fields:**
- `file_path`: Absolute path
- `relative_path`: Path relative to base directory
- `file_name`: Filename with extension
- `file_extension`: Extension (lowercase)
- `file_size`: Size in bytes

**Metadata:**
- `file_counts_by_extension`: Count per extension

### SQL Enumerator

Enumerates rows from SQL database queries. Currently supports SQLite.

**Configuration:**
- `connection_string` (required): Database path (e.g., `sqlite:///path/to/db.sqlite`)
- `query` (required): SELECT query to execute
- `id_column`: Column to use as identifier
- `params`: Query parameters (for parameterized queries)
- `limit`: Maximum rows

**Safety:**
- Only SELECT queries allowed
- Blocks DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE

**Payload fields:**
- All columns from query result
- `_row_index`: Row position
- `_id`: Value from id_column (if specified)

**Metadata:**
- `columns`: List of column names
- `row_count`: Number of rows

### CSV Enumerator

Enumerates rows from CSV files.

**Configuration:**
- `file_path` (required): Path to CSV file
- `id_column`: Column to use as identifier
- `delimiter`: Field separator (default: `,`)
- `has_header`: Whether first row is header (default: true)
- `encoding`: File encoding (default: `utf-8`)
- `columns`: Column names if no header
- `limit`: Maximum rows

**Payload fields:**
- All columns from CSV
- `_row_index`: Row position (0-based, excluding header)
- `_id`: Value from id_column (if specified)

**Metadata:**
- `columns`: List of column names
- `row_count`: Number of rows

### JSON Enumerator

Enumerates items from JSON files.

**Configuration:**
- `file_path` (required): Path to JSON file
- `items_path`: Dot-separated path to array (e.g., `response.items`)
- `id_field`: Field to use as identifier
- `encoding`: File encoding (default: `utf-8`)
- `limit`: Maximum items

**Payload fields:**
- All fields from JSON object
- `_index`: Position in array
- `_id`: Value from id_field (if specified)

Primitive values in arrays are wrapped as `{"value": ...}`.

**Metadata:**
- `items_path`: Path used (or "(root)")
- `item_count`: Number of items

### Dynamic Enumerator

Executes arbitrary Python code to enumerate items. This is the escape hatch for any data source not covered by built-in enumerators.

**Configuration:**
- `code` (required): Python code defining `enumerate_items(context) -> list[dict]`
- `context`: Dictionary passed to the function
- `approved` (required for execution): Whether code has been approved
- `limit`: Maximum items

**Security Model:**

LLM-generated code requires explicit user approval before execution. The flow:

1. LLM generates enumeration code
2. Server returns `PendingApprovalError` with the code
3. MCP server presents code to user for review
4. User approves (or rejects)
5. LLM re-calls with `approved: true`

This ensures users see and approve any code before it runs.

**Capabilities:**

The code has full Python access:
- Network requests (APIs, web scraping)
- Database connections (any database)
- Cloud SDKs (boto3 for AWS, etc.)
- File I/O
- Any installed Python library

**Example (DynamoDB):**

```python
def enumerate_items(context):
    import boto3
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(context['table_name'])

    items = []
    response = table.scan()
    for item in response['Items']:
        items.append({'id': item['id'], 'data': item})

    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        for item in response['Items']:
            items.append({'id': item['id'], 'data': item})

    return items
```

## Payload Design

Each item's payload dictionary becomes the work unit's data. Workers receive this payload and use it to complete their task.

Good payloads:
- Contain all information needed to process the item
- Include identifiers for tracking and debugging
- Avoid duplicating large data (reference by path/ID instead)

The `_index`, `_row_index`, and `_id` fields are conventions for tracking item position and identity across the system.

## Testing with Limits

All enumerators support a `limit` parameter for testing. This allows:
- Verifying configuration is correct
- Previewing what items will be processed
- Running test executions on a subset

The `get_sample_item()` method uses `limit=1` internally to return a single item for inspection.

## Error Handling

Enumerators return `EnumeratorResult(success=False, error=message)` on failure rather than raising exceptions. This allows the orchestrator to provide meaningful error messages to the user.

Common errors:
- File/directory not found
- Database connection failed
- Invalid query syntax
- Malformed data
- Code approval pending (dynamic enumerator)

## Extending with Custom Enumerators

To add a new enumerator:

1. Create a class extending `BaseEnumerator`
2. Set `enumerator_type` and `description` class attributes
3. Implement all abstract methods
4. Decorate with `@register_enumerator`
5. Import the module so registration runs

The enumerator will automatically appear in MCP tool schemas and be available via `create_enumerator()`.
