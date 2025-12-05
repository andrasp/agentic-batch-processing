"""HTTP server for the dashboard.

Uses Python's built-in http.server module to avoid external dependencies.
Serves:
- Static files (SPA, JS, CSS)
- REST API endpoints
- WebSocket connections (via separate handler)

The dashboard can run as:
1. In-process thread (DashboardServer) - dies with parent
2. Detached process (DetachedDashboardServer) - survives parent exit

For MCP server use, prefer DetachedDashboardServer to survive restarts.
"""

import json
import os
import re
import signal
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from multiprocessing import Process
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

from ..config import (
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_STORAGE_DIR,
    DEFAULT_JOB_LIST_LIMIT,
    DEFAULT_UNIT_LIST_LIMIT,
    DEFAULT_LOG_LIST_LIMIT,
)
from ..persistence.repository import Repository
from .api.routes import create_api_routes


STATIC_DIR = Path(__file__).parent / "static"

PID_FILE_NAME = "dashboard.pid"


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    repository: Repository = None
    api_routes: Dict[str, Callable] = None

    def __init__(self, *args, **kwargs):

        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/api/"):
            self._handle_api_request(path, query)
            return

        self._handle_static_request(path)

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_post_api_request(path)
            return

        self._send_json_response(
            {"error": {"code": "METHOD_NOT_ALLOWED", "message": "POST not allowed for this endpoint"}}, status=405
        )

    def _handle_api_request(self, path: str, query: Dict[str, list]):
        """Handle API requests."""
        try:

            params = {k: v[0] if v else None for k, v in query.items()}

            for key in ["limit", "offset"]:
                if key in params and params[key]:
                    try:
                        params[key] = int(params[key])
                    except ValueError:
                        pass

            result = None

            if path == "/api/jobs":
                result = self.api_routes["get_jobs"](
                    status=params.get("status"),
                    limit=params.get("limit", DEFAULT_JOB_LIST_LIMIT),
                    offset=params.get("offset", 0),
                )

            elif match := re.match(r"^/api/jobs/([^/]+)$", path):
                job_id = match.group(1)
                result = self.api_routes["get_job"](job_id)

            elif match := re.match(r"^/api/jobs/([^/]+)/units$", path):
                job_id = match.group(1)
                result = self.api_routes["get_job_units"](
                    job_id,
                    status=params.get("status"),
                    limit=params.get("limit", DEFAULT_UNIT_LIST_LIMIT),
                    offset=params.get("offset", 0),
                )

            elif match := re.match(r"^/api/jobs/([^/]+)/units/([^/]+)$", path):
                job_id = match.group(1)
                unit_id = match.group(2)
                result = self.api_routes["get_unit"](job_id, unit_id)

            elif match := re.match(r"^/api/jobs/([^/]+)/logs$", path):
                job_id = match.group(1)
                result = self.api_routes["get_job_logs"](
                    job_id,
                    source=params.get("source"),
                    level=params.get("level"),
                    limit=int(params.get("limit", DEFAULT_LOG_LIST_LIMIT)),
                    offset=int(params.get("offset", 0)),
                    since=params.get("since"),
                )

            elif match := re.match(r"^/api/jobs/([^/]+)/live$", path):
                job_id = match.group(1)
                result = self.api_routes["get_job_live_activity"](job_id)

            elif match := re.match(r"^/api/jobs/([^/]+)/executor$", path):
                job_id = match.group(1)
                result = self.api_routes["get_job_executor_status"](job_id)

            elif path == "/api/workers":
                result = self.api_routes["get_workers"]()

            elif path == "/api/stats":
                result = self.api_routes["get_stats"]()

            else:
                result = {"error": {"code": "NOT_FOUND", "message": f"Unknown API endpoint: {path}"}}
                self._send_json_response(result, status=404)
                return

            status = 200
            if "error" in result:
                error_code = result["error"].get("code", "")
                if "NOT_FOUND" in error_code:
                    status = 404
                elif error_code == "DB_ERROR":
                    status = 500
                else:
                    status = 400

            self._send_json_response(result, status=status)

        except Exception as e:
            self._send_json_response({"error": {"code": "SERVER_ERROR", "message": str(e)}}, status=500)

    def _handle_post_api_request(self, path: str):
        """Handle POST API requests."""
        try:
            result = None

            # POST /api/jobs/{job_id}/bypass - Enable bypass failures
            if match := re.match(r"^/api/jobs/([^/]+)/bypass$", path):
                job_id = match.group(1)
                result = self.api_routes["bypass_failures"](job_id)

            # POST /api/jobs/{job_id}/kill - Kill job manager
            elif match := re.match(r"^/api/jobs/([^/]+)/kill$", path):
                job_id = match.group(1)
                result = self.api_routes["kill_job"](job_id)

            # POST /api/jobs/{job_id}/restart - Restart job
            elif match := re.match(r"^/api/jobs/([^/]+)/restart$", path):
                job_id = match.group(1)
                result = self.api_routes["restart_job"](job_id)

            # POST /api/jobs/{job_id}/units/{unit_id}/kill - Kill work unit
            elif match := re.match(r"^/api/jobs/([^/]+)/units/([^/]+)/kill$", path):
                job_id = match.group(1)
                unit_id = match.group(2)
                result = self.api_routes["kill_unit"](job_id, unit_id)

            # POST /api/jobs/{job_id}/units/{unit_id}/restart - Restart work unit
            elif match := re.match(r"^/api/jobs/([^/]+)/units/([^/]+)/restart$", path):
                job_id = match.group(1)
                unit_id = match.group(2)
                result = self.api_routes["restart_unit"](job_id, unit_id)

            else:
                result = {"error": {"code": "NOT_FOUND", "message": f"Unknown API endpoint: {path}"}}
                self._send_json_response(result, status=404)
                return

            status = 200
            if "error" in result:
                error_code = result["error"].get("code", "")
                if "NOT_FOUND" in error_code:
                    status = 404
                elif error_code == "DB_ERROR":
                    status = 500
                else:
                    status = 400

            self._send_json_response(result, status=status)

        except Exception as e:
            self._send_json_response({"error": {"code": "SERVER_ERROR", "message": str(e)}}, status=500)

    def _handle_static_request(self, path: str):
        """Handle static file requests and SPA routing."""

        if path == "/":
            path = "/index.html"

        file_path = STATIC_DIR / path.lstrip("/")

        if file_path.is_file():

            super().do_GET()
        else:

            self.path = "/index.html"
            super().do_GET()

    def _send_json_response(self, data: Any, status: int = 200):
        """Send JSON response."""
        response = json.dumps(data, default=str).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(response))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args):
        """Suppress default logging."""
        pass


def create_handler_class(repository: Repository) -> type:
    """Create a request handler class with repository access.

    Args:
        repository: Repository instance

    Returns:
        Configured DashboardRequestHandler class
    """
    api_routes = create_api_routes(repository)

    class ConfiguredHandler(DashboardRequestHandler):
        pass

    ConfiguredHandler.repository = repository
    ConfiguredHandler.api_routes = api_routes

    return ConfiguredHandler


def create_app(db_path: Optional[Path] = None) -> HTTPServer:
    """Create HTTP server instance.

    Args:
        db_path: Optional database path

    Returns:
        Configured HTTPServer
    """
    repository = Repository(db_path)
    handler_class = create_handler_class(repository)

    port = int(os.environ.get("ABP_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT))
    server = HTTPServer(("localhost", port), handler_class)

    return server


def run_server(db_path: Optional[Path] = None, port: Optional[int] = None):
    """Run the HTTP server.

    Args:
        db_path: Optional database path
        port: Optional port override
    """
    repository = Repository(db_path)
    handler_class = create_handler_class(repository)

    if port is None:
        port = int(os.environ.get("ABP_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT))

    server = HTTPServer(("localhost", port), handler_class)

    print(f"Dashboard server running at http://localhost:{port}")
    print(f"Database: {repository.db_path}")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


class DashboardServer:
    """Dashboard server wrapper with lifecycle management."""

    def __init__(self, db_path: Optional[Path] = None, port: Optional[int] = None):
        self.db_path = db_path
        self.port = port or int(os.environ.get("ABP_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT))
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start the server in a background thread."""
        if self._running:
            return

        repository = Repository(self.db_path)
        handler_class = create_handler_class(repository)
        self.server = HTTPServer(("localhost", self.port), handler_class)

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self._running = True

    def stop(self):
        """Stop the server."""
        if self.server and self._running:
            self.server.shutdown()
            self._running = False

    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    def get_url(self, job_id: Optional[str] = None) -> str:
        """Get dashboard URL."""
        base = f"http://localhost:{self.port}"
        if job_id:
            return f"{base}/#/job/{job_id}"
        return base

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class DetachedDashboardServer:
    """Dashboard server that runs as a detached background process.

    This server:
    - Runs as a separate process that survives parent exit
    - Uses a PID file to ensure only one instance runs
    - Can be started/stopped from any process

    Usage:
        server = DetachedDashboardServer(db_path=db_path, port=3847)
        server.ensure_running()  # Start if not already running
        print(server.get_url())
    """

    def __init__(self, db_path: Optional[Path] = None, port: Optional[int] = None, pid_dir: Optional[Path] = None):
        """Initialize detached dashboard server.

        Args:
            db_path: Path to SQLite database
            port: Port to run on (default: 3847 or ABP_DASHBOARD_PORT env var)
            pid_dir: Directory for PID file (default: ~/.agentic-batch)
        """
        self.db_path = db_path
        self.port = port or int(os.environ.get("ABP_DASHBOARD_PORT", DEFAULT_DASHBOARD_PORT))
        self.pid_dir = pid_dir or (Path.home() / DEFAULT_STORAGE_DIR)
        self.pid_file = self.pid_dir / PID_FILE_NAME

    def _read_pid(self) -> Optional[int]:
        """Read PID from file if it exists."""
        if not self.pid_file.exists():
            return None
        try:
            with open(self.pid_file, "r") as f:
                content = f.read().strip()
                if content:
                    return int(content)
        except (ValueError, IOError):
            pass
        return None

    def _write_pid(self, pid: int):
        """Write PID to file."""
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        with open(self.pid_file, "w") as f:
            f.write(str(pid))

    def _remove_pid_file(self):
        """Remove PID file."""
        if self.pid_file.exists():
            try:
                self.pid_file.unlink()
            except IOError:
                pass

    def _is_process_running(self, pid: int) -> bool:
        """Check if process with given PID is running."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:

            return True

    def is_running(self) -> bool:
        """Check if dashboard server is currently running."""
        pid = self._read_pid()
        if pid is None:
            return False
        if not self._is_process_running(pid):

            self._remove_pid_file()
            return False
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get dashboard server status."""
        pid = self._read_pid()
        running = pid is not None and self._is_process_running(pid)

        return {
            "running": running,
            "pid": pid if running else None,
            "url": f"http://localhost:{self.port}" if running else None,
            "port": self.port,
            "pid_file": str(self.pid_file),
        }

    def ensure_running(self) -> Dict[str, Any]:
        """Ensure dashboard is running, starting if necessary.

        Returns:
            Status dict with running state and URL
        """
        if self.is_running():
            return self.get_status()

        pid = self._start_detached()
        return {
            "running": True,
            "pid": pid,
            "url": f"http://localhost:{self.port}",
            "port": self.port,
            "just_started": True,
        }

    def _start_detached(self) -> int:
        """Start dashboard as detached background process.

        Returns:
            PID of spawned process
        """

        db_path_str = str(self.db_path) if self.db_path else None

        process = Process(
            target=self._run_server_process, args=(db_path_str, self.port, str(self.pid_file)), daemon=False
        )
        process.start()

        time.sleep(0.5)

        return process.pid

    @staticmethod
    def _run_server_process(db_path_str: Optional[str], port: int, pid_file_str: str):
        """Run the HTTP server (executed in child process).

        Args:
            db_path_str: Database path as string (or None)
            port: Port to bind to
            pid_file_str: Path to PID file as string
        """
        pid_file = Path(pid_file_str)

        pid_file.parent.mkdir(parents=True, exist_ok=True)
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

        should_stop = [False]

        def signal_handler(signum, frame):
            should_stop[0] = True

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:

            db_path = Path(db_path_str) if db_path_str else None
            repository = Repository(db_path)
            handler_class = create_handler_class(repository)

            server = HTTPServer(("localhost", port), handler_class)
            server.timeout = 1.0

            while not should_stop[0]:
                server.handle_request()

        except Exception as e:

            sys.stderr.write(f"Dashboard server error: {e}\n")
            sys.stderr.flush()
        finally:

            if pid_file.exists():
                try:
                    pid_file.unlink()
                except IOError:
                    pass

    def stop(self) -> bool:
        """Stop the dashboard server gracefully.

        Returns:
            True if signal sent, False if not running
        """
        pid = self._read_pid()
        if pid is None:
            return False

        if not self._is_process_running(pid):
            self._remove_pid_file()
            return False

        try:
            os.kill(pid, signal.SIGTERM)

            time.sleep(0.5)

            if self._is_process_running(pid):

                os.kill(pid, signal.SIGKILL)
            self._remove_pid_file()
            return True
        except ProcessLookupError:
            self._remove_pid_file()
            return False
        except PermissionError:
            return False

    def get_url(self, job_id: Optional[str] = None) -> str:
        """Get dashboard URL.

        Args:
            job_id: Optional job ID to link directly to

        Returns:
            Dashboard URL
        """
        base = f"http://localhost:{self.port}"
        if job_id:
            return f"{base}/#/job/{job_id}"
        return base


if __name__ == "__main__":
    run_server()
