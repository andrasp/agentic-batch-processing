"""Dashboard package for Agentic Batch Processor.

Provides a web-based dashboard for real-time visualization of jobs, workers, and work units.
"""

from .http_server import create_app, run_server, DashboardServer, DetachedDashboardServer

__all__ = ["create_app", "run_server", "DashboardServer", "DetachedDashboardServer"]
