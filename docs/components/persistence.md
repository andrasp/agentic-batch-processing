# Persistence

The persistence layer provides durable storage for all batch processing state using SQLite. It enables crash recovery, job resumption, progress tracking, and historical analysis of completed jobs.

## Design Philosophy

The repository follows several key principles:

1. **Single Source of Truth**: All state lives in the database, not in memory
2. **Crash Recovery**: Jobs can resume from any interruption point
3. **Concurrent Access**: WAL mode enables multiple readers with one writer
4. **Schema Evolution**: Automatic migrations for backward compatibility

## Database Location

By default, the database is stored at `~/.agentic-batch/batch.db`. The directory is created automatically if it doesn't exist.

## Schema

### Jobs Table

Stores job definitions and aggregate progress:

| Column | Type | Description |
|--------|------|-------------|
| `job_id` | TEXT | Primary key, UUID |
| `name` | TEXT | Human-readable job name |
| `description` | TEXT | Detailed description |
| `status` | TEXT | Current status (pending, running, completed, failed, paused) |
| `worker_prompt_template` | TEXT | Prompt template with placeholders |
| `unit_type` | TEXT | Type of work units |
| `total_units` | INTEGER | Total items to process |
| `completed_units` | INTEGER | Successfully completed count |
| `failed_units` | INTEGER | Failed after max retries count |
| `max_workers` | INTEGER | Parallel worker limit |
| `created_at` | TEXT | ISO timestamp |
| `started_at` | TEXT | When processing began |
| `completed_at` | TEXT | When processing finished |
| `test_unit_id` | TEXT | ID of test unit if used |
| `test_passed` | INTEGER | Boolean: test succeeded |
| `output_strategy` | TEXT | How to collect outputs |
| `metadata` | TEXT | JSON blob for extensibility |

### Work Units Table

Stores individual items and their processing state:

| Column | Type | Description |
|--------|------|-------------|
| `unit_id` | TEXT | Primary key, UUID |
| `job_id` | TEXT | Foreign key to jobs |
| `unit_type` | TEXT | Type identifier |
| `status` | TEXT | Current status |
| `payload` | TEXT | JSON: input data for processing |
| `created_at` | TEXT | ISO timestamp |
| `assigned_at` | TEXT | When assigned to worker |
| `started_at` | TEXT | When execution began |
| `completed_at` | TEXT | When execution finished |
| `worker_id` | TEXT | Which worker processed it |
| `result` | TEXT | JSON: output data |
| `error` | TEXT | Error message if failed |
| `retry_count` | INTEGER | Current retry attempt |
| `max_retries` | INTEGER | Maximum retry attempts |
| `execution_time_seconds` | REAL | Processing duration |
| `output_files` | TEXT | JSON: list of created files |
| `rendered_prompt` | TEXT | Actual prompt sent to LLM |
| `conversation` | TEXT | JSON: full conversation history |
| `session_id` | TEXT | Claude session ID |
| `cost_usd` | REAL | API cost for this unit |

### Workers Table

Tracks worker processes and their statistics:

| Column | Type | Description |
|--------|------|-------------|
| `worker_id` | TEXT | Primary key, UUID |
| `status` | TEXT | Current status (idle, busy, stopped) |
| `job_id` | TEXT | Currently assigned job |
| `current_unit_id` | TEXT | Currently processing unit |
| `process_id` | INTEGER | OS process ID |
| `started_at` | TEXT | When worker started |
| `last_heartbeat` | TEXT | Last activity timestamp |
| `units_completed` | INTEGER | Total completed by this worker |
| `units_failed` | INTEGER | Total failed by this worker |
| `total_execution_time` | REAL | Cumulative processing time |

## Connection Management

The repository uses a context manager pattern for database connections:

- Each operation gets a fresh connection
- Connections auto-commit on success
- Connections rollback on exception
- Connections close in the finally block

This ensures no connection leaks and proper transaction handling.

## Concurrency Configuration

SQLite is configured for optimal concurrent access:

- **WAL Mode**: Write-Ahead Logging allows concurrent readers
- **30-second Timeout**: Prevents immediate failures under contention
- **NORMAL Synchronous**: Balance between safety and performance

WAL mode is particularly important because the Job Manager, dashboard, and MCP server may all access the database simultaneously.

## Indices

Performance-critical queries are accelerated by indices:

- `idx_work_units_job_id`: Fast lookup of units by job
- `idx_work_units_status`: Fast filtering by status
- `idx_work_units_worker_id`: Fast lookup by worker assignment
- `idx_workers_job_id`: Fast lookup of workers by job

## Schema Migration

The repository automatically migrates older databases when new columns are added. The migration process:

1. Queries `PRAGMA table_info` to get existing columns
2. Compares against expected columns
3. Adds missing columns with `ALTER TABLE`

This allows schema evolution without manual database updates.

## JSON Serialization

Complex data is stored as JSON strings:

- `payload`: Work unit input data
- `result`: Work unit output data
- `output_files`: List of created file paths
- `conversation`: Full LLM conversation history
- `metadata`: Extensible job metadata

The repository handles JSON encoding on write and decoding on read.

## Query Patterns

### Fetching Pending Work

The `get_pending_units` method retrieves work units ready for processing:
- Filters by job ID and PENDING status
- Orders by creation time (FIFO)
- Limits results to batch size

### Counting by Status

`count_units_by_status` uses `GROUP BY` to efficiently aggregate unit counts without loading all records.

### Pagination

`get_units_for_job` supports pagination with LIMIT and OFFSET for dashboard browsing of large jobs.

## Row Conversion

Helper methods convert database rows to dataclass objects:

- `_row_to_job`: Converts row to Job with status enum parsing
- `_row_to_work_unit`: Converts row with JSON parsing and optional column handling
- `_row_to_worker`: Converts row to Worker

Optional column handling in `_row_to_work_unit` ensures compatibility with databases created before conversation capture was added.

## Error Handling

Database operations return boolean success indicators rather than raising exceptions. This allows callers to handle failures gracefully without try/except blocks everywhere.

When operations fail (usually due to constraint violations or connection issues), the repository returns `False` and the transaction is rolled back.

## Use Cases

The persistence layer enables several critical features:

1. **Job Resumption**: Query pending units after crash
2. **Progress Tracking**: Count completed/failed units
3. **Dashboard Display**: Paginated browsing of jobs and units
4. **Debugging**: Full conversation history for failed units
5. **Cost Analysis**: Aggregate API costs across units
6. **Worker Monitoring**: Track active workers and their assignments

## Database as Communication Channel

Because all components share the SQLite database, it serves as an implicit communication channel:

- Job Manager writes progress, dashboard reads it
- Orchestrator creates jobs, dashboard displays them
- Workers update unit status, Job Manager tracks completion

This decoupling allows components to run in separate processes and survive restarts independently.
