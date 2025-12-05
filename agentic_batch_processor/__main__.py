"""Entry point for running the Agentic Batch Processor MCP server.

Usage:
    python -m agentic_batch_processor [--port PORT] [--db PATH]

This starts the MCP server which provides tools for:
- Job orchestration (create, start, monitor)
- Dashboard interaction (open browser, get URLs)

Configure in .claude/mcp.json:
    {
        "mcpServers": {
            "agentic-batch-processor": {
                "command": "python",
                "args": ["-m", "agentic_batch_processor"]
            }
        }
    }
"""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Batch Processor MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run MCP server (for use with Claude Code)
    python -m agentic_batch_processor

    # Run with custom database
    python -m agentic_batch_processor --db /path/to/batch.db

    # Run with custom dashboard port
    python -m agentic_batch_processor --port 8080

MCP Configuration (.claude/mcp.json):
    {
        "mcpServers": {
            "agentic-batch-processor": {
                "command": "python",
                "args": ["-m", "agentic_batch_processor"]
            }
        }
    }
""",
    )

    parser.add_argument("--port", type=int, default=None, help="Dashboard port number (default: 3847)")
    parser.add_argument("--db", type=str, default=None, help="Database path (default: ~/.agentic-batch/batch.db)")

    args = parser.parse_args()

    if args.port:
        os.environ["ABP_DASHBOARD_PORT"] = str(args.port)

    db_path = Path(args.db) if args.db else None

    from .mcp_server import run_mcp_server

    run_mcp_server(db_path=db_path)


if __name__ == "__main__":
    main()
