"""Entry point for running the dashboard HTTP server.

Usage:
    python -m agentic_batch_processor.dashboard [--port PORT] [--db PATH]

Options:
    --port      Port number (default: 3847)
    --db        Database path (default: ~/.agentic-batch/batch.db)

Note: For MCP server functionality, use:
    python -m agentic_batch_processor
"""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Batch Processor Dashboard HTTP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run dashboard server
    python -m agentic_batch_processor.dashboard

    # Run with custom port
    python -m agentic_batch_processor.dashboard --port 8080

    # Run with custom database
    python -m agentic_batch_processor.dashboard --db /path/to/batch.db

For MCP server with both orchestration and dashboard tools:
    python -m agentic_batch_processor
""",
    )

    parser.add_argument("--port", type=int, default=None, help="Port number (default: 3847)")
    parser.add_argument("--db", type=str, default=None, help="Database path (default: ~/.agentic-batch/batch.db)")

    args = parser.parse_args()

    if args.port:
        os.environ["ABP_DASHBOARD_PORT"] = str(args.port)

    db_path = Path(args.db) if args.db else None

    from .http_server import run_server

    run_server(db_path=db_path, port=args.port)


if __name__ == "__main__":
    main()
