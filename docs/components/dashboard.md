# Dashboard

The dashboard provides a web-based interface for monitoring batch processing jobs. It displays real-time progress, worker activity, and allows inspection of individual work unit conversations.

## Architecture

The dashboard consists of three layers:

1. **HTTP Server**: Python's built-in `http.server` with REST API endpoints
2. **Services**: Business logic for data aggregation and transformation
3. **Frontend SPA**: Preact application with hash-based routing

## HTTP Server

The server uses Python's standard library to avoid external dependencies. It handles two types of requests:

### Static Files

Files from the `static/` directory are served directly. For non-existent paths, the server falls back to `index.html` to support client-side routing.

### REST API

All `/api/*` routes are handled by the routing layer and return JSON responses. CORS headers allow access from any origin.

## API Endpoints

### GET Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/jobs` | List jobs with optional status filter |
| `GET /api/jobs/{job_id}` | Get job details with workers and recent units |
| `GET /api/jobs/{job_id}/units` | List work units with pagination |
| `GET /api/jobs/{job_id}/units/{unit_id}` | Get unit detail with conversation |
| `GET /api/workers` | Get all active workers across jobs |
| `GET /api/stats` | Get aggregate statistics |

### POST Endpoints (Job Control)

| Endpoint | Description |
|----------|-------------|
| `POST /api/jobs/{job_id}/bypass` | Enable bypass failures for post-processing |
| `POST /api/jobs/{job_id}/kill` | Kill the job manager process |
| `POST /api/jobs/{job_id}/restart` | Restart a stopped/failed job |
| `POST /api/jobs/{job_id}/units/{unit_id}/kill` | Kill a specific work unit process |
| `POST /api/jobs/{job_id}/units/{unit_id}/restart` | Restart a failed work unit |

### Query Parameters

- `status`: Filter by status (running, completed, failed)
- `limit`: Maximum items to return
- `offset`: Pagination offset

### Error Responses

Errors return a JSON object with `error.code` and `error.message`:

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `JOB_NOT_FOUND` | 404 | Job ID doesn't exist |
| `UNIT_NOT_FOUND` | 404 | Unit ID doesn't exist |
| `DB_ERROR` | 500 | Database operation failed |
| `SERVER_ERROR` | 500 | Unexpected exception |

## Services Layer

Four service classes handle business logic:

### JobService

Aggregates job data with worker counts and progress calculations. The `list_jobs` method enriches each job with active worker count. The `get_job_detail` method provides comprehensive job information including workers, recent units, and status breakdowns.

### WorkUnitService

Handles unit listing and detail retrieval. The detail view includes the full conversation history captured during execution.

### WorkerService

Aggregates active workers across all running jobs. Includes the current unit payload for each worker to show what they're processing.

### StatsService

Calculates aggregate statistics across all jobs:
- Total and active job counts
- Total processed and failed units
- Success rate percentage
- Active worker count
- Average execution time (sampled from recent jobs)

## Response Schemas

The `schemas.py` file defines dataclasses for all API responses. Each schema has a `to_dict()` method for JSON serialization.

Key schemas:
- `JobSummary`: Compact job info for list views
- `JobResponse`: Full job details
- `JobDetailResponse`: Job with workers and units
- `WorkUnitSummary`: Compact unit info
- `WorkUnitResponse`: Full unit with conversation
- `WorkerResponse`: Worker state and progress
- `AggregateStats`: System-wide statistics

## Frontend Application

The SPA is built with Preact (3KB alternative to React) using htm for JSX-like templating without a build step.

### Technology Stack

- **Preact**: Lightweight React-compatible library
- **htm**: Tagged template literals for JSX syntax
- **CSS**: Custom dark theme stylesheet
- **ES Modules**: Native browser module loading

### Routing

Hash-based routing (`/#/path`) enables navigation without server configuration. The `useHashRouter` hook manages route state and navigation.

Supported routes:
- `/`: Dashboard home with stats and recent jobs
- `/jobs`: Full job list with filtering
- `/job/{id}`: Job detail view
- `/job/{id}/units`: Work unit browser
- `/job/{id}/unit/{id}`: Unit detail with conversation

### Views

**Dashboard Home**: Shows aggregate statistics (total jobs, active jobs, success rate, workers) and a list of recent jobs with progress bars.

**Job List**: Filterable list of all jobs with status badges and progress indicators.

**Job Detail**: Comprehensive view showing:
- Progress statistics (pending, workers, completed, failed)
- Overall progress bar
- Active worker cards with current task
- Worker prompt template
- Recent activity feed

**Unit List**: Paginated list of work units for a job with status filtering.

**Unit Detail**: Shows:
- Unit status and metadata
- Error message if failed
- Rendered prompt sent to LLM
- Full conversation history with tool calls

### Components

Reusable UI components:
- `Header`: Navigation bar with links
- `Loading`: Spinner with message
- `Badge`: Status indicator with color coding
- `ProgressBar`: Visual progress indicator
- `StatCard`: Metric display box

## DashboardServer Class

A wrapper class provides lifecycle management for embedding in other applications:

| Method | Description |
|--------|-------------|
| `start()` | Start server in background thread |
| `stop()` | Stop the server |
| `is_running()` | Check server status |
| `get_url(job_id)` | Get URL, optionally for specific job |

The class also supports context manager protocol (`with DashboardServer() as server`).

## Standalone Mode

The dashboard can run independently:

```bash
python -m agentic_batch_processor.dashboard --port 3847 --db /path/to/db
```

This starts the HTTP server and prints the URL. Useful for monitoring jobs after the MCP server has disconnected.

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `ABP_DASHBOARD_PORT` | HTTP server port | 3847 |
| `ABP_DB_PATH` | SQLite database path | `~/.agentic-batch/batch.db` |

## Visual Design

The dashboard uses a dark theme optimized for developer environments:

- Dark background with high-contrast text
- Color-coded status badges (green=completed, red=failed, yellow=processing)
- Progress bars with status-appropriate fill colors
- Monospace fonts for code and prompts
- Card-based layout for information grouping

## Conversation Display

The unit detail view renders the full agent conversation:

- Messages grouped by type (user, assistant, tool_use, tool_result)
- Tool calls show tool name and input parameters
- JSON input formatted with indentation
- Timestamps when available

This is invaluable for debugging failed units — you can see exactly what the agent tried and where it went wrong.
