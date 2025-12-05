#!/usr/bin/env python3
"""Development reset script for Agentic Batch Processor.

Kills all running processes and clears the database for a fresh start.

Usage:
    python scripts/dev_reset.py [--keep-db] [--dry-run]

Options:
    --keep-db   Don't clear the database, only kill processes
    --dry-run   Show what would be done without actually doing it
"""

import argparse
import os
import signal
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from agentic_batch_processor.persistence.repository import Repository
from agentic_batch_processor.core.models import WorkerStatus, JobStatus


def kill_process(pid: int, name: str, dry_run: bool = False) -> bool:
    """Kill a process by PID.

    Args:
        pid: Process ID to kill
        name: Description of the process for logging
        dry_run: If True, only print what would be done

    Returns:
        True if process was killed or doesn't exist, False on error
    """
    try:

        os.kill(pid, 0)

        if dry_run:
            print(f"  [DRY RUN] Would kill {name} (PID {pid})")
            return True

        print(f"  Sending SIGTERM to {name} (PID {pid})...")
        os.kill(pid, signal.SIGTERM)

        import time

        time.sleep(0.5)

        try:
            os.kill(pid, 0)

            print(f"  Process still running, sending SIGKILL...")
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        print(f"  Killed {name} (PID {pid})")
        return True

    except ProcessLookupError:
        print(f"  {name} (PID {pid}) not running")
        return True
    except PermissionError:
        print(f"  ERROR: Permission denied killing {name} (PID {pid})")
        return False
    except Exception as e:
        print(f"  ERROR: Failed to kill {name} (PID {pid}): {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Reset development environment")
    parser.add_argument("--keep-db", action="store_true", help="Don't clear the database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    print("=" * 60)
    print("Agentic Batch Processor - Development Reset")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")

    repo = Repository()
    print(f"\nDatabase: {repo.db_path}")

    print("\n1. Killing worker processes...")
    workers_killed = 0
    try:

        with repo._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT worker_id, process_id, job_id, status
                FROM workers
                WHERE process_id IS NOT NULL
            """
            ).fetchall()

        for row in rows:
            if row["process_id"]:
                if kill_process(row["process_id"], f"Worker {row['worker_id'][:8]}", args.dry_run):
                    workers_killed += 1

        if not rows:
            print("  No worker processes found in database")
    except Exception as e:
        print(f"  ERROR reading workers: {e}")

    print("\n2. Killing job executor processes...")
    executors_killed = 0
    try:
        jobs = repo.list_jobs(limit=100)
        for job in jobs:
            executor_pid = job.metadata.get("executor_pid")
            if executor_pid:
                if kill_process(executor_pid, f"Job Executor ({job.name})", args.dry_run):
                    executors_killed += 1

        if not any(job.metadata.get("executor_pid") for job in jobs):
            print("  No job executor processes found")
    except Exception as e:
        print(f"  ERROR reading jobs: {e}")

    print("\n3. Killing dashboard process...")
    dashboard_killed = False
    try:

        pid_file = Path.home() / ".agentic-batch" / "dashboard.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            if kill_process(pid, "Dashboard Server", args.dry_run):
                dashboard_killed = True
                if not args.dry_run:
                    pid_file.unlink()
        else:
            print("  No dashboard PID file found")
    except Exception as e:
        print(f"  ERROR: {e}")

    if not args.keep_db:
        print("\n4. Clearing database...")
        if args.dry_run:
            print("  [DRY RUN] Would delete all rows from: jobs, work_units, workers, logs")
        else:
            try:
                with repo._get_connection() as conn:

                    result = conn.execute("DELETE FROM logs")
                    logs_deleted = result.rowcount

                    result = conn.execute("DELETE FROM workers")
                    workers_deleted = result.rowcount

                    result = conn.execute("DELETE FROM work_units")
                    units_deleted = result.rowcount

                    result = conn.execute("DELETE FROM jobs")
                    jobs_deleted = result.rowcount

                    conn.commit()

                print(f"  Deleted {jobs_deleted} jobs")
                print(f"  Deleted {units_deleted} work units")
                print(f"  Deleted {workers_deleted} workers")
                print(f"  Deleted {logs_deleted} log entries")
            except Exception as e:
                print(f"  ERROR clearing database: {e}")
    else:
        print("\n4. Skipping database clear (--keep-db)")

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Workers killed: {workers_killed}")
    print(f"  Job executors killed: {executors_killed}")
    print(f"  Dashboard killed: {'Yes' if dashboard_killed else 'No'}")
    if not args.keep_db and not args.dry_run:
        print("  Database cleared: Yes")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN] No changes were made. Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
