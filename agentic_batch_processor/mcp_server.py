"""Unified MCP Server for Agentic Batch Processor.

Thin API wrapper that delegates all business logic to the Orchestrator.

Provides tools for:
- Job orchestration (create, start, monitor jobs)
- Dashboard interaction (open browser, get URLs)
- Status monitoring

Usage:
    python -m agentic_batch_processor.mcp_server

Or configure in .claude/mcp.json:
    {
        "mcpServers": {
            "agentic-batch-processor": {
                "command": "python",
                "args": ["-m", "agentic_batch_processor.mcp_server"]
            }
        }
    }
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DEFAULT_MAX_WORKERS, DEFAULT_MAX_RETRIES, DEFAULT_DASHBOARD_PORT
from .persistence.repository import Repository
from .core.orchestrator import Orchestrator
from .workers.claude_cli_worker import ClaudeCliWorkerWithFiles
from .dashboard.http_server import DetachedDashboardServer
from .enumerators import get_all_enumerator_schemas, PendingApprovalError
from .mcp_tools import MCP_TOOLS


class AgenticBatchMCPServer:
    """Unified MCP server for the Agentic Batch Processor."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize MCP server.

        Args:
            db_path: Optional database path. Can also be set via ABP_STORAGE_PATH env var.
        """
        if db_path is None:
            env_storage = os.environ.get("ABP_STORAGE_PATH")
            if env_storage:
                db_path = Path(env_storage)

        self.db_path = db_path
        self.repository = Repository(db_path)

        self.dashboard_port = int(os.environ.get("ABP_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT))
        self.max_workers = int(os.environ.get("ABP_MAX_WORKERS", DEFAULT_MAX_WORKERS))
        self.max_retries = int(os.environ.get("ABP_MAX_RETRIES", DEFAULT_MAX_RETRIES))

        self.dashboard_server = DetachedDashboardServer(db_path=db_path, port=self.dashboard_port)

        self.orchestrator = Orchestrator(repository=self.repository, worker_implementation=ClaudeCliWorkerWithFiles())

    def _ensure_dashboard_running(self):
        """Ensure dashboard HTTP server is running (as detached process)."""
        self.dashboard_server.ensure_running()

    def _open_browser(self, url: str) -> bool:
        """Open URL in default browser."""
        try:
            system = platform.system().lower()
            if system == "darwin":
                subprocess.run(["open", url], check=True)
            elif system == "linux":
                subprocess.run(["xdg-open", url], check=True)
            elif system == "windows":
                subprocess.run(["start", url], shell=True, check=True)
            else:
                return False
            return True
        except Exception:
            return False

    def dashboard_open(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Open dashboard in browser."""
        self._ensure_dashboard_running()
        url = self.dashboard_server.get_url(job_id)
        success = self._open_browser(url)
        return {
            "success": success,
            "url": url,
            "message": f"Dashboard opened at {url}" if success else f"Please open {url} in your browser",
        }

    def dashboard_status(self) -> Dict[str, Any]:
        """Get dashboard server status."""
        return self.dashboard_server.get_status()

    def dashboard_url(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Get dashboard URL without opening browser."""
        self._ensure_dashboard_running()
        url = self.dashboard_server.get_url(job_id)
        return {"url": url, "job_id": job_id}

    def dashboard_stop(self) -> Dict[str, Any]:
        """Stop the dashboard server."""
        stopped = self.dashboard_server.stop()
        return {"stopped": stopped, "message": "Dashboard server stopped" if stopped else "Dashboard was not running"}

    def list_jobs(self, status: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """List jobs with optional status filter."""
        jobs = self.repository.list_jobs(limit=limit, status=status)
        return {
            "jobs": [
                {
                    "job_id": j.job_id,
                    "name": j.name,
                    "status": j.status.value,
                    "progress": f"{j.completed_units}/{j.total_units}",
                    "progress_percentage": round(j.progress_percentage(), 1),
                    "created_at": j.created_at.isoformat(),
                }
                for j in jobs
            ],
            "total": len(jobs),
        }

    def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get detailed job information."""
        job = self.repository.get_job(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        status_counts = self.repository.count_units_by_status(job_id)
        workers = self.repository.get_active_workers(job_id)

        return {
            "job_id": job.job_id,
            "name": job.name,
            "description": job.description,
            "status": job.status.value,
            "progress": {
                "total": job.total_units,
                "completed": job.completed_units,
                "failed": job.failed_units,
                "percentage": round(job.progress_percentage(), 1),
            },
            "unit_stats": status_counts,
            "active_workers": len(workers),
            "max_workers": job.max_workers,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
        }

    def create_job(
        self,
        name: str,
        user_intent: str,
        enumerator_type: str,
        enumerator_config: Dict[str, Any],
        post_processing_prompt: Optional[str] = None,
        post_processing_name: Optional[str] = None,
        post_processing_output_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new batch processing job with any enumerator type.

        For dynamic enumerators with LLM-generated code, if the code hasn't been
        approved yet, this returns a 'pending_approval' response with the code
        for user review. The LLM should present this code to the user and ask
        for approval before re-calling with approved=True in the config.

        For scatter-gather-synthesize jobs, provide a post_processing_prompt that
        will run after all work units complete. The synthesizer can generate reports,
        visualizations, exports, etc. from the aggregated data.

        If post_processing_output_directory is provided, the post-processing agent
        will have write access to that directory.
        """
        try:
            metadata = {}
            if post_processing_name:
                metadata["post_processing_name"] = post_processing_name
            if post_processing_output_directory:
                metadata["post_processing_output_directory"] = post_processing_output_directory

            result = self.orchestrator.create_job(
                name=name,
                user_intent=user_intent,
                enumerator_type=enumerator_type,
                enumerator_config=enumerator_config,
                max_workers=self.max_workers,
                max_retries=self.max_retries,
                post_processing_prompt=post_processing_prompt,
                metadata=metadata,
            )
            return result
        except PendingApprovalError as e:

            return {
                "pending_approval": True,
                "message": (
                    "The dynamic enumerator code requires your approval before execution. "
                    "Please review the code below and confirm it's safe to run on your system."
                ),
                "code": e.code,
                "instructions": (
                    "If approved, re-call create_job with the same parameters but add "
                    "'approved': true to the enumerator_config."
                ),
                "original_params": {
                    "name": name,
                    "user_intent": user_intent,
                    "enumerator_type": enumerator_type,
                    "enumerator_config": enumerator_config,
                    "post_processing_prompt": post_processing_prompt,
                    "post_processing_output_directory": post_processing_output_directory,
                },
            }
        except Exception as e:
            return {"error": str(e)}

    def list_enumerators(self) -> Dict[str, Any]:
        """List available enumerator types and their configuration schemas."""
        schemas = get_all_enumerator_schemas()
        return {"enumerators": schemas, "count": len(schemas)}

    def start_job(self, job_id: str, approve: Optional[bool] = None, skip_test: bool = False) -> Dict[str, Any]:
        """Start a job with optional test phase. Delegates to Orchestrator."""
        try:
            return self.orchestrator.start_job(job_id, approve=approve, skip_test=skip_test)
        except Exception as e:
            return {"error": str(e)}

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get current job status and progress. Delegates to Orchestrator."""
        return self.orchestrator.get_job_status(job_id)

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle MCP protocol request.

        Returns None for notifications (requests without an id).
        """
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        is_notification = request_id is None

        if is_notification:
            if method == "notifications/initialized":

                return None
            elif method and method.startswith("notifications/"):

                return None

        result = None
        error = None

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            elif method == "resources/list":
                result = self._handle_resources_list()
            elif method == "resources/read":
                result = self._handle_resources_read(params)
            else:
                error = {"code": -32601, "message": f"Unknown method: {method}"}
        except Exception as e:
            error = {"code": -32603, "message": str(e)}

        response = {"jsonrpc": "2.0", "id": request_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result

        return response

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "agentic-batch-processor", "version": "0.1.0"},
        }

    def _handle_tools_list(self) -> Dict[str, Any]:
        """Handle tools/list request."""
        return {"tools": MCP_TOOLS}

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        handlers = {
            "dashboard_open": lambda: self.dashboard_open(arguments.get("job_id")),
            "dashboard_status": lambda: self.dashboard_status(),
            "dashboard_url": lambda: self.dashboard_url(arguments.get("job_id")),
            "dashboard_stop": lambda: self.dashboard_stop(),
            "list_jobs": lambda: self.list_jobs(status=arguments.get("status"), limit=arguments.get("limit", 20)),
            "get_job": lambda: self.get_job(arguments.get("job_id")),
            "list_enumerators": lambda: self.list_enumerators(),
            "create_job": lambda: self.create_job(
                name=arguments.get("name"),
                user_intent=arguments.get("user_intent"),
                enumerator_type=arguments.get("enumerator_type"),
                enumerator_config=arguments.get("enumerator_config", {}),
                post_processing_prompt=arguments.get("post_processing_prompt"),
                post_processing_name=arguments.get("post_processing_name"),
                post_processing_output_directory=arguments.get("post_processing_output_directory"),
            ),
            "start_job": lambda: self.start_job(
                job_id=arguments.get("job_id"),
                approve=arguments.get("approve"),
                skip_test=arguments.get("skip_test", False),
            ),
            "get_job_status": lambda: self.get_job_status(arguments.get("job_id")),
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

        result = handler()
        is_error = "error" in result
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}], "isError": is_error}

    def _handle_resources_list(self) -> Dict[str, Any]:
        """Handle resources/list request."""
        return {
            "resources": [
                {
                    "uri": "abp://status",
                    "name": "System Status",
                    "description": "Current status of the Agentic Batch Processor",
                    "mimeType": "application/json",
                },
                {
                    "uri": "abp://jobs",
                    "name": "Active Jobs",
                    "description": "List of active batch processing jobs",
                    "mimeType": "application/json",
                },
            ]
        }

    def _handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")

        if uri == "abp://status":
            jobs = self.repository.list_jobs(limit=100)
            active_jobs = sum(1 for j in jobs if j.status.value == "running")
            dashboard_status = self.dashboard_server.get_status()
            content = {
                "total_jobs": len(jobs),
                "active_jobs": active_jobs,
                "dashboard_running": dashboard_status["running"],
                "dashboard_url": dashboard_status.get("url") or f"http://localhost:{self.dashboard_port}",
                "dashboard_pid": dashboard_status.get("pid"),
            }
        elif uri == "abp://jobs":
            content = self.list_jobs()
        else:
            content = {"error": f"Unknown resource: {uri}"}

        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(content, indent=2)}]}

    def run_stdio(self):
        """Run MCP server using stdio transport."""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)
                response = self.handle_request(request)

                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:

                sys.stderr.write(f"MCP server error: {e}\n")
                sys.stderr.flush()


def run_mcp_server(db_path: Optional[Path] = None):
    """Run the MCP server."""
    server = AgenticBatchMCPServer(db_path=db_path)
    server.run_stdio()


if __name__ == "__main__":
    run_mcp_server()
