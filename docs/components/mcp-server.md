# MCP Server

The MCP (Model Context Protocol) server enables Claude Desktop and other MCP clients to orchestrate batch processing jobs through natural language. It exposes tools for creating, starting, and monitoring jobs, as well as accessing the [dashboard](dashboard.md).

## Design Philosophy

The server follows these principles:

1. **Unified Interface**: All batch processing capabilities through one MCP server
2. **Conversational Workflow**: Natural language requests become tool calls
3. **Human-in-the-Loop**: Dynamic code requires explicit user approval
4. **Self-Managing**: Dashboard server starts automatically when needed

## Protocol Implementation

The server implements the MCP JSON-RPC protocol over stdio:

- Reads newline-delimited JSON from stdin
- Writes JSON responses to stdout
- Handles both requests (with `id`) and notifications (without `id`)
- Returns `None` for notifications to avoid sending unnecessary responses

## Capabilities

The server advertises two capabilities:

- **tools**: Function-like operations the LLM can invoke
- **resources**: Read-only data the LLM can access

## Tools

### Dashboard Tools

| Tool | Description |
|------|-------------|
| `dashboard_open` | Opens dashboard in browser, optionally to specific job |
| `dashboard_status` | Checks if dashboard server is running |
| `dashboard_url` | Gets dashboard URL without opening browser |
| `dashboard_stop` | Stops the dashboard server (runs as detached process) |

### Job Management Tools

| Tool | Description |
|------|-------------|
| `list_jobs` | Lists jobs with optional status filter |
| `get_job` | Gets detailed job information |
| `create_job` | Creates job with any enumerator type |
| `start_job` | Starts a created job (with test phase) |
| `get_job_status` | Gets current progress and status |
| `list_enumerators` | Lists available data source types |

### Tool Schemas

Each tool defines an `inputSchema` following JSON Schema format. This allows MCP clients to validate parameters and provide intelligent auto-completion.

## Resources

The server exposes two resources:

| URI | Description |
|-----|-------------|
| `abp://status` | System status (job counts, dashboard state) |
| `abp://jobs` | List of batch processing jobs |

Resources are read-only and return JSON content.

## Creating Jobs

The `create_job` tool accepts:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `name` | Yes | Human-readable job name |
| `user_intent` | Yes | What the LLM should do with each item (becomes worker prompt) |
| `enumerator_type` | Yes | Data source type (file, sql, csv, json, dynamic) |
| `enumerator_config` | Yes | Configuration for the enumerator |
| `post_processing_prompt` | No | Synthesis prompt for [scatter-gather-synthesize pattern](../patterns.md#scatter-gather-synthesize-pattern) |
| `post_processing_name` | No | Human-readable name for post-processing task |
| `post_processing_output_directory` | No | Directory for post-processing output files |

### Enumerator Types

Use `list_enumerators` to discover available types and their schemas:

- **file**: Glob pattern file matching
- **sql**: SQLite query results
- **csv**: CSV file rows
- **json**: JSON array items
- **dynamic**: Custom Python code

### Dynamic Enumerator Approval Flow

When using the dynamic enumerator with LLM-generated code:

1. LLM calls `create_job` with `enumerator_type: "dynamic"`
2. Server returns `pending_approval: true` with the code
3. LLM presents code to user for review
4. User approves or rejects
5. If approved, LLM re-calls with `approved: true` in config

This ensures users review code before execution.

## Starting Jobs

Jobs are created in `CREATED` status. Call `start_job` to begin processing.

The `start_job` tool supports a test phase:

1. First call runs a test on the first work unit
2. Returns test results for user review
3. Call again with `approve=true` to process remaining units
4. Or call with `approve=false` to reject and reset

Use `skip_test=true` to bypass testing and start immediately.

Once approved, the [Job Manager](job-manager.md) spawns as a detached process and continues running even if the MCP server disconnects.

## Dashboard Integration

The server manages a dashboard HTTP server internally:

- Starts automatically when any dashboard tool is called
- Runs in a background thread
- Stops when the MCP server exits
- Opens browser using platform-appropriate commands

Browser opening uses:
- macOS: `open`
- Linux: `xdg-open`
- Windows: `start`

## Request Handling

The `handle_request` method routes incoming requests:

| Method | Handler |
|--------|---------|
| `initialize` | Returns protocol version and capabilities |
| `tools/list` | Returns available tools with schemas |
| `tools/call` | Dispatches to tool implementation |
| `resources/list` | Returns available resources |
| `resources/read` | Returns resource content |

Notifications (messages without `id`) are acknowledged silently without response.

## Error Handling

Tool calls return structured errors:

- Success: `{"content": [...], "isError": false}`
- Failure: `{"content": [...], "isError": true}`

The content contains JSON-formatted results or error messages.

JSON-RPC errors use standard codes:
- `-32601`: Unknown method
- `-32603`: Internal error

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ABP_DASHBOARD_PORT` | Dashboard HTTP port | 3847 |

## Running the Server

Standalone (for testing):
```bash
python -m agentic_batch_processor.mcp_server
```

Via uv (recommended for MCP config):
```bash
uv run --directory /path/to/repo python -m agentic_batch_processor.mcp_server
```

## Claude Desktop Integration

Add to MCP configuration:

```json
{
  "mcpServers": {
    "agentic-batch-processor": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/repo", "python", "-m", "agentic_batch_processor.mcp_server"],
      "cwd": "/path/to/repo"
    }
  }
}
```

## Internal Components

The server creates and manages:

- **Repository**: Database access for job and unit data
- **Orchestrator**: Job creation and management logic
- **ClaudeCliWorkerWithFiles**: Default worker for file-based tasks
- **DashboardServer**: HTTP server for web interface

## Lifecycle

1. Server starts and initializes components
2. Waits for JSON-RPC requests on stdin
3. Routes requests to appropriate handlers
4. Returns responses on stdout
5. On stdin EOF or interrupt, cleans up dashboard server

## Example Workflow

A typical session might look like:

1. User: "Create a batch job to summarize all Python files in /code"
2. LLM calls `create_job` with file enumerator config
3. Server returns job details with `job_id`
4. LLM calls `dashboard_open` to monitor progress
5. LLM calls `start_job` with the job ID
6. Test phase runs on first file, results returned
7. LLM presents results, user approves
8. LLM calls `start_job` with `approve=true`
9. Browser shows real-time progress in dashboard
