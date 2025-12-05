"""Claude CLI worker implementation.

Spawns Claude CLI processes to execute work units with full conversation capture.
Uses --output-format stream-json to capture the complete agent conversation.
"""

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from .base import BaseWorker, WorkerResult
from ..config import DEFAULT_WORKER_TIMEOUT


StreamCallback = Callable[[str, Dict[str, Any]], None]
ProcessCallback = Callable[[int], None]  # Called with PID when process starts


class ClaudeCliWorker(BaseWorker):
    """Worker that uses the Claude CLI to execute work units.

    Each work unit execution spawns a new `claude` process with:
    - The prompt template filled with work unit data
    - --output-format stream-json for full conversation capture
    - --print flag for non-interactive mode
    - Streaming JSONL output parsed for conversation history

    The conversation capture enables:
    - Full debugging of failed work units
    - Understanding exactly what the agent did
    - Cost tracking per work unit
    - Session ID for potential resume
    """

    def __init__(self, cli_path: str = "claude", max_turns: Optional[int] = None, model: Optional[str] = None):
        """Initialize Claude CLI worker.

        Args:
            cli_path: Path to claude CLI executable (default: "claude")
            max_turns: Optional max agentic turns limit
            model: Optional model override (e.g., "claude-sonnet-4-20250514")
        """
        self.cli_path = cli_path
        self.max_turns = max_turns
        self.model = model

    def execute(
        self,
        prompt: str,
        work_unit_payload: Dict[str, Any],
        timeout: Optional[float] = None,
        on_stream_event: Optional[StreamCallback] = None,
        on_process_start: Optional[ProcessCallback] = None,
    ) -> WorkerResult:
        """Execute work unit using Claude CLI with full conversation capture.

        Args:
            prompt: Template prompt for the LLM
            work_unit_payload: Work unit specific data to inject into prompt
            timeout: Optional timeout in seconds (default: 600)
            on_stream_event: Optional callback called for each streaming event.
                             Receives (event_type, event_data) for real-time updates.
            on_process_start: Optional callback called when subprocess starts.
                              Receives the process PID for tracking/killing.

        Returns:
            WorkerResult with execution outcome and full conversation history
        """
        if timeout is None:
            timeout = DEFAULT_WORKER_TIMEOUT

        start_time = time.time()

        try:

            rendered_prompt = self._render_prompt(prompt, work_unit_payload)

            cmd = self._build_command(rendered_prompt, work_unit_payload)

            return self._execute_with_streaming(
                cmd=cmd,
                rendered_prompt=rendered_prompt,
                work_unit_payload=work_unit_payload,
                timeout=timeout,
                start_time=start_time,
                on_stream_event=on_stream_event,
                on_process_start=on_process_start,
            )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            return WorkerResult(
                success=False,
                error=f"Execution timed out after {timeout} seconds",
                execution_time=execution_time,
                rendered_prompt=rendered_prompt if "rendered_prompt" in locals() else None,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            return WorkerResult(
                success=False,
                error=f"Execution failed: {str(e)}",
                execution_time=execution_time,
                rendered_prompt=rendered_prompt if "rendered_prompt" in locals() else None,
            )

    def _build_command(self, rendered_prompt: str, work_unit_payload: Dict[str, Any]) -> List[str]:
        """Build the Claude CLI command.

        Args:
            rendered_prompt: The rendered prompt to send
            work_unit_payload: Work unit payload for additional options

        Returns:
            Command list for subprocess
        """
        cmd = [
            self.cli_path,
            "--print",
            rendered_prompt,
            "--output-format",
            "stream-json",
            "--verbose",
        ]

        if self.model:
            cmd.extend(["--model", self.model])

        if self.max_turns:
            cmd.extend(["--max-turns", str(self.max_turns)])

        return cmd

    def _execute_with_streaming(
        self,
        cmd: List[str],
        rendered_prompt: str,
        work_unit_payload: Dict[str, Any],
        timeout: float,
        start_time: float,
        on_stream_event: Optional[StreamCallback] = None,
        on_process_start: Optional[ProcessCallback] = None,
    ) -> WorkerResult:
        """Execute command and parse streaming JSON output.

        Args:
            cmd: Command to execute
            rendered_prompt: The rendered prompt (for storing in result)
            work_unit_payload: Work unit payload
            timeout: Timeout in seconds
            start_time: When execution started
            on_stream_event: Optional callback for streaming events
            on_process_start: Optional callback when process starts (receives PID)

        Returns:
            WorkerResult with parsed conversation
        """
        conversation: List[Dict[str, Any]] = []
        final_result = None
        session_id = None

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=work_unit_payload.get("working_directory"),
            start_new_session=True,
        )

        if on_process_start:
            on_process_start(process.pid)

        try:

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)

                    event_type = event.get("type")

                    if event_type == "system" and event.get("subtype") == "init":
                        session_id = event.get("session_id")
                        if on_stream_event:
                            on_stream_event(event_type, event)

                    elif event_type in ("user", "assistant", "tool_use", "tool_result"):
                        conversation.append(event)

                        if on_stream_event:
                            on_stream_event(event_type, event)

                    elif event_type == "result":
                        final_result = event
                        if on_stream_event:
                            on_stream_event(event_type, event)

                except json.JSONDecodeError:

                    pass

            process.wait(timeout=timeout)
            stderr_output = process.stderr.read()

        except subprocess.TimeoutExpired:

            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            raise

        execution_time = time.time() - start_time

        if final_result:
            is_error = final_result.get("is_error", False)
            result_text = final_result.get("result", "")

            return WorkerResult(
                success=not is_error,
                output=result_text if not is_error else None,
                error=result_text if is_error else None,
                execution_time=execution_time,
                conversation=conversation,
                rendered_prompt=rendered_prompt,
                metadata={
                    "session_id": session_id,
                    "num_turns": final_result.get("num_turns"),
                    "total_cost_usd": final_result.get("total_cost_usd"),
                    "duration_ms": final_result.get("duration_ms"),
                    "duration_api_ms": final_result.get("duration_api_ms"),
                    "return_code": process.returncode,
                },
            )
        else:

            return WorkerResult(
                success=False,
                error=f"No result received. Return code: {process.returncode}. stderr: {stderr_output}",
                execution_time=execution_time,
                conversation=conversation,
                rendered_prompt=rendered_prompt,
                metadata={
                    "session_id": session_id,
                    "return_code": process.returncode,
                },
            )

    def _render_prompt(self, template: str, payload: Dict[str, Any]) -> str:
        """Render prompt template with work unit payload.

        Supports simple {key} substitution and {payload.key} for nested access.

        Args:
            template: Prompt template string
            payload: Work unit payload data

        Returns:
            Rendered prompt
        """

        context = {"payload": payload, **payload}

        try:

            return template.format(**context)
        except KeyError as e:

            return f"{template}\n\n[ERROR: Missing template variable: {e}]"

    def is_available(self) -> bool:
        """Check if Claude CLI is available."""
        return shutil.which(self.cli_path) is not None

    def get_name(self) -> str:
        """Get worker name."""
        return "claude-cli"


class ClaudeCliWorkerWithFiles(ClaudeCliWorker):
    """Extended Claude CLI worker that grants access to file directories.

    Useful for file-based work units where the LLM needs to read/process files.
    Uses --add-dir to grant Claude CLI access to the directories containing
    the files referenced in the work unit payload.
    """

    def _build_command(self, rendered_prompt: str, work_unit_payload: Dict[str, Any]) -> List[str]:
        """Build command with directory access for files.

        Args:
            rendered_prompt: The rendered prompt to send
            work_unit_payload: Work unit payload with file_path or file_paths

        Returns:
            Command list with --add-dir for file directories
        """

        cmd = super()._build_command(rendered_prompt, work_unit_payload)

        directories = set()
        if "file_path" in work_unit_payload:
            file_path = Path(work_unit_payload["file_path"])
            if file_path.exists():
                directories.add(str(file_path.parent))
        if "file_paths" in work_unit_payload:
            for fp in work_unit_payload["file_paths"]:
                file_path = Path(fp)
                if file_path.exists():
                    directories.add(str(file_path.parent))

        if "output_directory" in work_unit_payload and work_unit_payload["output_directory"]:
            output_dir = Path(work_unit_payload["output_directory"])
            if output_dir.exists():
                directories.add(str(output_dir))
            elif output_dir.parent.exists():
                directories.add(str(output_dir.parent))

        if directories:
            cmd.append("--dangerously-skip-permissions")
            for directory in directories:
                cmd.extend(["--add-dir", directory])

        return cmd

    def get_name(self) -> str:
        """Get worker name."""
        return "claude-cli-with-files"
