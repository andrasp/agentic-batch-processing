# Worker Pool

The Worker Pool manages parallel execution of work units across multiple LLM worker processes. It provides a thread-based executor that respects concurrency limits while capturing full execution details for each unit.

## Architecture

The pool uses Python's `ThreadPoolExecutor` to manage a configurable number of concurrent workers. Each work unit submission spawns a thread that:

1. Creates a Worker record in the database
2. Marks the work unit as ASSIGNED
3. Transitions to PROCESSING when execution begins
4. Captures all execution results, including full conversation history
5. Updates the work unit and worker records
6. Invokes completion or failure callbacks

Thread safety is ensured via a threading lock that protects access to worker tracking data structures.

## Initialization

The pool requires:

- **job_id**: Which job this pool processes
- **worker_implementation**: A BaseWorker subclass (e.g., ClaudeCliWorker)
- **repository**: For persisting state changes
- **max_workers**: Concurrency limit (default 4)
- **on_unit_complete**: Optional callback for successful completions
- **on_unit_failed**: Optional callback for failures

## Submitting Work Units

The `submit_work_unit()` method:

1. Checks if the pool has capacity (returns False if full)
2. Creates a Worker record with BUSY status
3. Updates the work unit to ASSIGNED status with worker assignment
4. Persists both records
5. Submits the execution function to the thread pool
6. Tracks the future and worker in internal dictionaries

Callers should use `wait_for_available_slot()` before submitting if they want to block until capacity is available.

## Execution Flow

When a work unit executes (in a worker thread):

1. **Status Update**: Work unit transitions to PROCESSING with start timestamp
2. **Worker Execution**: Calls `worker_implementation.execute()` with prompt and payload
3. **Result Capture**: Extracts all result fields including:
   - Execution time
   - Output files
   - Rendered prompt
   - Full conversation history
   - Session ID
   - Cost (USD)
4. **Status Finalization**: Work unit becomes COMPLETED or FAILED
5. **Callback Invocation**: Triggers completion or failure callback
6. **Cleanup**: Worker status reset, removed from active tracking

## Conversation Capture

A key feature of the worker pool is capturing the complete LLM conversation for each work unit. This includes:

- The actual prompt sent (after template substitution)
- All messages exchanged with the LLM
- Any tool calls and results
- The session ID for potential resume

This data is stored on the work unit and persisted to the database, enabling:

- Debugging failed executions
- Auditing agent behavior
- Understanding how the agent solved each task
- Cost analysis per unit

## Error Handling

Two types of errors are handled:

**Worker-reported failures**: When `result.success` is False, the unit is marked FAILED with the error message, and the failure callback is invoked.

**Unexpected exceptions**: Any exception in the execution thread is caught, the unit is marked FAILED with the exception message, and cleanup proceeds normally.

In both cases, the worker record is updated and removed from active tracking.

## Concurrency Control

The pool enforces its max_workers limit through:

1. **Capacity Check**: `submit_work_unit()` returns False if at capacity
2. **Blocking Wait**: `wait_for_available_slot()` blocks until a slot opens
3. **Active Tracking**: Internal dictionary tracks which workers are busy

The orchestrator typically uses this pattern:

```
for unit in pending_units:
    pool.wait_for_available_slot()
    pool.submit_work_unit(unit, prompt)
```

This ensures the pool never exceeds its concurrency limit while keeping all workers busy.

## Lifecycle

1. **start()**: Sets the running flag (currently minimal)
2. **submit_work_unit()**: Add units for processing
3. **wait_for_completion()**: Block until all active workers finish
4. **stop()**: Shutdown the executor and mark workers as TERMINATED

The stop() method uses `shutdown(wait=True)` to ensure all running work completes before termination.

## Thread Safety

The pool uses a single lock to protect:

- Active worker dictionary
- Active futures dictionary
- Capacity checks

The lock is held briefly during submissions and cleanups to minimize contention.

## Timeouts

Work unit execution has a 10-minute timeout by default. This is passed to the worker implementation and applies to the entire execution, not individual LLM calls.

Long-running tasks that exceed this timeout will fail, triggering the normal failure handling and retry logic.

## Callbacks

The pool supports two callbacks:

**on_unit_complete(work_unit, result)**: Called after a unit successfully completes. The work_unit has all result data populated. The orchestrator uses this to update job statistics.

**on_unit_failed(work_unit, result)**: Called after a unit fails. The orchestrator uses this to handle retries or mark permanent failures.

Both callbacks run in the worker thread, so they should be relatively quick to avoid blocking other work.
