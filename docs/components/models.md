# Data Models

The models module defines the core data structures that represent the state of batch processing. These dataclasses provide a type-safe foundation for jobs, work units, and workers.

## WorkUnit

A WorkUnit represents a single item to be processed by an LLM agent. The abstraction is intentionally generic — a work unit can be a file, database record, URL, API call, or any discrete task.

### Key Fields

**Identity and Association**
- `unit_id`: Unique identifier (UUID)
- `job_id`: Parent job this unit belongs to
- `unit_type`: What kind of item (file, url, record, etc.)

**Payload**
- `payload`: Dictionary containing type-specific data. For files, this includes `file_path`, `file_name`, `file_extension`, etc. The payload structure varies by enumerator type.

**Status and Tracking**
- `status`: Current state (PENDING, ASSIGNED, PROCESSING, COMPLETED, FAILED)
- `created_at`, `assigned_at`, `started_at`, `completed_at`: Timestamps for lifecycle tracking
- `worker_id`: Which worker is processing this unit

**Results**
- `result`: Dictionary of outputs from successful processing
- `error`: Error message if processing failed
- `execution_time_seconds`: How long processing took

**Retry Logic**
- `retry_count`: How many times this unit has been retried
- `max_retries`: Maximum retry attempts (default 3)
- `can_retry()`: Helper method to check if retries remain

**Observability**
- `rendered_prompt`: The actual prompt sent to the LLM (after template substitution)
- `conversation`: Full conversation history with the LLM
- `session_id`: Claude session ID for potential resume
- `cost_usd`: API cost tracking for billing/budgeting

The conversation capture is critical for debugging — when a unit fails or produces unexpected output, you can review exactly what the agent saw and did.

## Job

A Job groups related work units with shared configuration and tracks overall progress.

### Key Fields

**Identity**
- `job_id`: Unique identifier (UUID)
- `name`: Human-readable name
- `description`: User's original intent/request

**Configuration**
- `worker_prompt_template`: The prompt given to workers, with placeholders for per-unit data
- `unit_type`: What kind of work units this job contains
- `max_workers`: Maximum parallel workers (default 4)

**Progress**
- `total_units`: How many units in this job
- `completed_units`: Successfully processed count
- `failed_units`: Failed after max retries count
- `progress_percentage()`: Helper returning completion as 0-100

**Lifecycle**
- `status`: Current job state
- `created_at`, `started_at`, `completed_at`: Timestamps

**Testing**
- `test_unit_id`: Which unit was used for testing
- `test_passed`: Whether the test execution succeeded

**Output**
- `output_strategy`: How to handle outputs (individual, aggregate, none)

**Metadata**
- `metadata`: Flexible dictionary for additional data. Used to store `executor_pid` when running as a background process.

## JobStatus

Jobs transition through these states:

| Status | Description |
|--------|-------------|
| CREATED | Job and work units exist, not yet started |
| TESTING | Running test execution on single unit |
| READY | Test passed, awaiting full batch start |
| RUNNING | Actively processing work units |
| PAUSED | Temporarily stopped, can resume |
| COMPLETED | All units processed successfully |
| FAILED | Some units failed after max retries |

The TESTING → READY flow supports the "test before batch" workflow where users approve results on one item before committing to the full batch.

## WorkUnitStatus

Work units transition through these states:

| Status | Description |
|--------|-------------|
| PENDING | Waiting to be assigned to a worker |
| ASSIGNED | Worker claimed this unit |
| PROCESSING | Worker is actively executing |
| COMPLETED | Successfully finished |
| FAILED | Failed (may be retried if attempts remain) |

The ASSIGNED → PROCESSING distinction allows detecting worker failures — if a unit is ASSIGNED but the worker dies, the orchestrator can reassign it.

## Worker

Represents an active worker process in the pool.

### Key Fields

**Identity**
- `worker_id`: Unique identifier
- `job_id`: Which job this worker is processing
- `current_unit_id`: Which unit is currently being processed

**Process Info**
- `process_id`: OS process ID
- `status`: IDLE, BUSY, FAILED, or TERMINATED

**Health**
- `started_at`: When the worker started
- `last_heartbeat`: Last activity timestamp for stale worker detection

**Statistics**
- `units_completed`: Successful executions count
- `units_failed`: Failed execution count
- `total_execution_time`: Cumulative time spent processing

## Serialization

All models implement `to_dict()` for JSON serialization. This is used by:
- The persistence layer when storing to SQLite
- The dashboard API when returning data
- The MCP server when responding to tool calls

Datetime fields are converted to ISO format strings. Enums are converted to their string values.

## Design Philosophy

These models follow several principles:

1. **Immutability-friendly**: Dataclasses with clear fields, avoiding complex nested mutations
2. **Serializable**: All fields can be JSON-serialized via `to_dict()`
3. **Observable**: Rich tracking fields enable debugging and monitoring
4. **Retryable**: Built-in retry logic for resilience
5. **Flexible**: Generic payload dictionary adapts to any data source
