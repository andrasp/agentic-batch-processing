# Workers

Workers are the execution layer that spawns LLM processes to handle individual work units. Each worker takes a prompt and work unit payload, executes the task, and returns results including the full conversation history.

## Design Philosophy

Workers are designed around several principles:

1. **Full Autonomy**: Workers have complete tool access and work independently
2. **Complete Capture**: Every LLM interaction is recorded for debugging
3. **Pluggable**: Different worker implementations for different LLMs
4. **Stateless**: Each execution is independent (state lives in the database)

## WorkerResult

All workers return a `WorkerResult` containing:

| Field | Description |
|-------|-------------|
| `success` | Whether execution completed successfully |
| `output` | Final output text from the worker |
| `error` | Error message if failed |
| `execution_time` | Total time in seconds |
| `output_files` | Files created/modified |
| `metadata` | Session ID, cost, turns, etc. |
| `conversation` | Full conversation history |
| `rendered_prompt` | Actual prompt sent (after substitution) |

The conversation history is particularly valuable — it shows exactly what the agent saw, what tools it called, and how it reasoned through the task.

## Base Interface

All workers implement `BaseWorker`:

| Method | Description |
|--------|-------------|
| `execute(prompt, payload, timeout)` | Run a work unit |
| `is_available()` | Check if this worker type works on the system |
| `get_name()` | Return the worker type name |

The `execute()` method is where all the work happens. It receives:
- A prompt template with placeholders
- The work unit payload (data for substitution)
- An optional timeout

## Claude CLI Worker

The primary worker implementation uses the Claude CLI (`claude` command).

### Execution Flow

1. **Prompt Rendering**: Substitutes payload values into the template
2. **Command Building**: Constructs the CLI command with options
3. **Process Spawning**: Runs claude with streaming JSON output
4. **Output Parsing**: Reads JSONL stream line by line
5. **Result Assembly**: Extracts conversation, metadata, and outcome

### CLI Options Used

- `--print <prompt>`: Non-interactive mode with prompt
- `--output-format stream-json`: JSONL output for parsing
- `--verbose`: Include tool results in output
- `--model <model>`: Optional model override
- `--max-turns <n>`: Optional turn limit

### Streaming JSON Format

The CLI outputs JSONL (one JSON object per line) with event types:

- `system` (subtype: `init`): Contains session_id
- `user`: User message
- `assistant`: Claude response
- `tool_use`: Tool invocation
- `tool_result`: Tool output
- `result`: Final result with metadata

The worker parses these events to build the complete conversation history.

### Metadata Captured

The final `result` event includes:
- `session_id`: For potential resume
- `num_turns`: Number of agentic turns
- `total_cost_usd`: API cost
- `duration_ms`: Total duration
- `duration_api_ms`: Time spent in API calls
- `is_error`: Whether execution failed

### Template Rendering

Prompts can include placeholders like `{file_path}` that are filled from the work unit payload:

```python
context = {
    "payload": payload,  # For {payload.key} access
    **payload  # For direct {key} access
}
rendered = template.format(**context)
```

If a placeholder key is missing, the worker appends an error message rather than crashing.

## Claude CLI Worker with Files

`ClaudeCliWorkerWithFiles` extends the base worker to attach files to the conversation.

### File Handling

It looks for files in the payload:
- `file_path`: Single file to attach
- `file_paths`: List of files to attach

Each file is added with `--file <path>`, making the file content available to Claude for reading or analysis.

### Use Cases

This variant is essential for:
- **Vision tasks**: Analyzing images
- **Document processing**: Reading PDFs, markdown, etc.
- **Code review**: Understanding source files
- **File modification**: When Claude needs to see file contents

## Configuration

Workers accept configuration at construction:

| Option | Description | Default |
|--------|-------------|---------|
| `cli_path` | Path to claude executable | `"claude"` |
| `max_turns` | Maximum agentic turns | None (unlimited) |
| `model` | Model override | None (use default) |

## Error Handling

Workers handle several failure modes:

1. **Timeout**: Process killed, returns timeout error
2. **No Result**: CLI produced no `result` event
3. **CLI Error**: `is_error: true` in result
4. **Exception**: Catches all exceptions with stack trace

In all cases, the worker returns a `WorkerResult` with `success=False` and the error details.

## Working Directory

The worker can execute in a specific directory:

```python
work_unit_payload.get("working_directory")
```

If present, the subprocess runs in that directory, which affects relative path resolution.

## Future Worker Types

The worker abstraction enables adding new LLM providers:

- **OpenAI Worker**: Use GPT models via API
- **Local Model Worker**: Run local LLMs via ollama or llama.cpp
- **API Worker**: Direct HTTP calls to model APIs
- **Mock Worker**: For testing without real LLM calls

Each would implement the same `BaseWorker` interface, making them interchangeable in the orchestrator.

## Performance Considerations

Each work unit spawns a new process. This has tradeoffs:

**Pros:**
- Complete isolation between units
- Fresh context for each task
- No state leakage

**Cons:**
- Process spawn overhead
- No session reuse

For very small tasks (< 1 second), the spawn overhead may be significant. For typical agentic tasks (30+ seconds), it's negligible.

## Availability Check

`is_available()` uses `shutil.which()` to check if the CLI exists in PATH. This allows graceful degradation if a worker type isn't installed.
