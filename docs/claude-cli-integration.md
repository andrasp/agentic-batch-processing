# Claude CLI Integration

This document covers how the Agentic Batch Processor integrates with the Claude CLI for executing work units.

## Overview

Each work unit is executed by spawning a separate `claude` CLI process. This provides:
- Process isolation between work units
- Full tool access for each worker
- Session management and resume capability
- Cost tracking per unit

## Command Construction

### Base Command
```bash
claude --print "<prompt>" --output-format stream-json --verbose
```

### With File Access
```bash
claude --print "<prompt>" --output-format stream-json --verbose \
  --dangerously-skip-permissions \
  --add-dir /path/to/files
```

## Critical: stdin Handling

**IMPORTANT**: When spawning Claude CLI from a background process, you MUST set `stdin=subprocess.DEVNULL`.

```python
process = subprocess.Popen(
    cmd,
    stdin=subprocess.DEVNULL,  # CRITICAL
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=True
)
```

### Why This Matters

When running from a detached process (like one spawned via `multiprocessing.Process`):
1. There is no controlling terminal
2. stdin is in an undefined state
3. The Claude CLI checks stdin during initialization
4. Without `stdin=subprocess.DEVNULL`, the process hangs indefinitely

### Symptoms of Missing stdin=DEVNULL
- Process spawns but makes no API calls
- No network connections visible (`lsof -p <PID> -i` shows nothing)
- Process stuck in `kevent` wait (visible via `sample <PID>`)
- Work units stay in "processing" state with no conversation data

## Output Format

Using `--output-format stream-json` produces JSONL (one JSON object per line):

### Init Event
```json
{"type":"system","subtype":"init","session_id":"...", "tools":[...], "model":"..."}
```

### User Message
```json
{"type":"user","message":{"content":[...]}}
```

### Assistant Message
```json
{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}
```

### Tool Use (in assistant message content)
```json
{"type":"tool_use","id":"...","name":"Read","input":{"file_path":"..."}}
```

### Tool Result (in user message content)
```json
{"type":"tool_result","tool_use_id":"...","content":[{"type":"text","text":"..."}]}
```

### Final Result
```json
{
  "type":"result",
  "subtype":"success",
  "is_error":false,
  "result":"...",
  "total_cost_usd":0.123,
  "num_turns":5
}
```

## Process Management

### Process Group Isolation
```python
start_new_session=True  # Creates new process group
```

This ensures:
- Workers don't receive signals meant for parent
- Clean termination via `os.killpg()`

### Timeout Handling
```python
try:
    # Read output...
    process.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGKILL)
```

### Clean Shutdown
The worker pool sends SIGTERM for graceful shutdown, falling back to SIGKILL if needed.

## Permissions

### --dangerously-skip-permissions
Required when using `--add-dir` in non-interactive mode because:
- `--add-dir` normally prompts for permission confirmation
- `--print` mode has no way to respond to prompts
- Without this flag, the process hangs waiting for user input

**Security Note**: Only use with trusted file paths. The worker validates file existence before granting access.

## Cost Tracking

Each execution returns cost information:
```python
result.metadata = {
    "total_cost_usd": 0.123,
    "num_turns": 5,
    "duration_ms": 15000,
    "duration_api_ms": 14500,
    "session_id": "abc-123"
}
```

Cost is tracked per-unit in the database for aggregate reporting.

## Session Resume

The session_id from each execution can be used to resume conversations:
```bash
claude --resume <session_id>
```

Currently not implemented in the batch processor but session_ids are stored for future use.

## Environment Variables

The subprocess inherits the parent's environment, which includes:
- `ANTHROPIC_API_KEY` (if using API key auth)
- OAuth tokens (if using Claude Desktop auth)
- PATH for finding the `claude` binary

No special environment handling is needed - the Claude CLI uses the same auth as the parent process.

## Model Selection

The worker can specify a model override:
```python
worker = ClaudeCliWorker(model="claude-sonnet-4-20250514")
```

This adds `--model <model>` to the command.

## Max Turns

To limit agentic turns:
```python
worker = ClaudeCliWorker(max_turns=10)
```

This adds `--max-turns 10` to the command.
