# Troubleshooting Guide

## Critical Issues and Solutions

### Workers Stuck in "Processing" State (No Progress)

**Symptoms:**
- Dashboard shows units in "processing" state but no conversation appears
- Worker processes exist but have no network connections
- Logs stop at "Spawning claude CLI process..."

**Root Cause:**
The `subprocess.Popen` call was missing `stdin=subprocess.DEVNULL`. When spawned from a detached process (via `multiprocessing.Process`), there's no real stdin available. The Claude CLI checks stdin and blocks indefinitely when it's in an invalid state. See [Claude CLI Integration](claude-cli-integration.md) for details on proper subprocess handling.

**Solution:**
Always use `stdin=subprocess.DEVNULL` when spawning Claude CLI from background processes:

```python
process = subprocess.Popen(
    cmd,
    stdin=subprocess.DEVNULL,  # CRITICAL: Required for background execution
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=True
)
```

**Diagnosis Steps:**
1. Check if worker processes exist: `ps aux | grep claude`
2. Check network connections: `lsof -p <PID> -i` (should show HTTPS connections to Anthropic)
3. Sample the process to see what it's waiting on: `sample <PID> 1`

If workers have no network connections and are stuck in `kevent`, it's the stdin issue.

---

### Job Executor Not Found After Restart

**Symptoms:**
- Job shows status "running" but no progress
- `get_executor_status` returns `{"status": "not_found"}`

**Root Cause:**
The [job executor](components/job-manager.md) PID is stored in job metadata. If the process died, the PID becomes stale.

**Solution:**
Use the `resume_job` function to start a new job executor:

```python
from agentic_batch_processor.core.job_executor import JobExecutor

pid = JobExecutor.resume_job(repository, job_id, worker_implementation)
```

---

### MCP Tool Omitting User Requirements

**Symptoms:**
- User asks to "write results to SQLite" but worker prompt doesn't include this
- Output requirements get lost between user intent and worker prompt

**Root Cause:**
The MCP tool's `user_intent` parameter description wasn't explicit enough about including ALL requirements.

**Solution:**
The `user_intent` description now includes:
- CRITICAL prefix emphasizing importance
- Explicit list of what must be included (analysis, outputs, destinations, formatting)
- Warning that omitted requirements will be lost

When using the MCP tools, ensure you copy the COMPLETE user intent including output destinations.

---

### Dashboard Not Loading

**Symptoms:**
- `http://localhost:3847` returns connection refused
- Dashboard PID file exists but process is dead

**Solution:**
```bash
# Kill stale dashboard
cat ~/.agentic-batch/dashboard.pid 2>/dev/null && kill $(cat ~/.agentic-batch/dashboard.pid) 2>/dev/null

# Restart
python3 -c "
from agentic_batch_processor.dashboard.http_server import DetachedDashboardServer
from pathlib import Path

db_path = Path.home() / '.agentic-batch' / 'batch.db'
server = DetachedDashboardServer(db_path=db_path)
result = server.ensure_running()
print('Dashboard URL:', server.get_url())
"
```

---

### Work Units Stuck in "assigned" State

**Symptoms:**
- Units show "assigned" status indefinitely
- No worker is actively processing them

**Root Cause:**
Worker died between assignment and processing start.

**Solution:**
The job executor automatically cleans up stale assignments on startup:
```python
stale_workers = repository.cleanup_stale_workers(job_id)
stuck_units = repository.reset_stuck_units(job_id)
```

To manually fix:
```sql
UPDATE work_units
SET status = 'pending', worker_id = NULL, assigned_at = NULL
WHERE status = 'assigned' AND job_id = '<job_id>';
```

---

## Development Reset

For a complete reset during development:

```bash
python3 scripts/dev_reset.py
```

This will:
1. Kill all worker processes
2. Kill job executor processes
3. Kill dashboard process
4. Clear the database (jobs, units, workers, logs)

---

## Debugging Tips

### View Job Logs
```bash
sqlite3 ~/.agentic-batch/batch.db "SELECT timestamp, level, source, message FROM logs WHERE job_id='<job_id>' ORDER BY timestamp"
```

### Check Worker Status
```bash
sqlite3 ~/.agentic-batch/batch.db "SELECT worker_id, status, current_unit_id FROM workers WHERE job_id='<job_id>'"
```

### View Unit Conversation
```bash
sqlite3 ~/.agentic-batch/batch.db "SELECT conversation FROM work_units WHERE unit_id='<unit_id>'" | python3 -m json.tool
```

### Monitor Processes
```bash
# Job executor
ps aux | grep "multiprocessing.spawn"

# Claude workers
ps aux | grep "claude"

# Dashboard
cat ~/.agentic-batch/dashboard.pid && ps -p $(cat ~/.agentic-batch/dashboard.pid)
```
