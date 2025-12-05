"""MCP tool schema definitions for Agentic Batch Processor."""

MCP_TOOLS = [
    {
        "name": "dashboard_open",
        "description": "Opens the Agentic Batch Processor Dashboard in the default web browser. The dashboard provides real-time visualization of jobs, workers, and work units.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Optional job ID to open directly to that job's detail view.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "dashboard_status",
        "description": "Check if the dashboard server is running and get its URL.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "dashboard_url",
        "description": "Get the dashboard URL without opening a browser.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "Optional job ID for direct link."}},
            "required": [],
        },
    },
    {
        "name": "dashboard_stop",
        "description": "Stop the dashboard server. The dashboard runs as a detached process, so it survives MCP server restarts. Use this to explicitly stop it if needed.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_jobs",
        "description": "List batch processing jobs with optional status filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: created, running, post_processing, completed, failed",
                    "enum": [
                        "created",
                        "testing",
                        "ready",
                        "running",
                        "paused",
                        "post_processing",
                        "completed",
                        "failed",
                    ],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of jobs to return (default: 20)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_job",
        "description": "Get detailed information about a specific job.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "The job ID to get details for."}},
            "required": ["job_id"],
        },
    },
    {
        "name": "list_enumerators",
        "description": "List available enumerator types and their configuration schemas. Use this to discover what data sources can be used with create_job.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_job",
        "description": """Create a batch processing job. Three patterns available:

**MAP PATTERN** (1 input → 1 output): Each item produces independent output files.
Example: Analyze images, write analysis_*.json for each.
- user_intent: describe per-item processing and output file naming (include working_directory in payload for each item)
- post_processing_prompt: DO NOT SET

**SCATTER-GATHER PATTERN** (N inputs → shared sink): All items write to a shared database/file.
Example: Extract data from documents into a SQLite database.
- user_intent: MUST include the shared sink path (e.g., "write results to /output/results.db")
- The sink must handle concurrent writes (SQLite with WAL, or append-only files like JSONL/CSV)
- post_processing_prompt: DO NOT SET

**SCATTER-GATHER-SYNTHESIZE** (aggregation + synthesis): Items write to shared sink, then synthesis step generates final output.
Example: Analyze photos into results.db, then generate an HTML gallery from the database.
- user_intent: MUST include shared sink path (absolute path)
- post_processing_prompt: SET THIS - describes the synthesis step (runs ONCE after ALL items complete)
  The synthesizer reads from the shared sink and generates reports, summaries, visualizations, etc.
  Include working_directory in the post-processing payload.

Enumerator types: file (glob patterns), sql (SQLite queries), csv, json, dynamic (custom code).
For dynamic enumerators: if response contains 'pending_approval', show code to user, then re-call with 'approved': true.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable name for this job"},
                "user_intent": {
                    "type": "string",
                    "description": "CRITICAL: This becomes the worker prompt for EACH item. Include ALL requirements: (1) what to analyze/process, (2) what outputs to produce, (3) where to write results (absolute paths!), (4) any formatting requirements. The worker LLM receives ONLY this prompt - any requirement not included here will be lost. For scatter-gather patterns, include the shared sink path.",
                },
                "enumerator_type": {
                    "type": "string",
                    "description": "Data source type",
                    "enum": ["file", "sql", "csv", "json", "dynamic"],
                },
                "enumerator_config": {
                    "type": "object",
                    "description": "Config for enumerator. File: {base_directory, pattern}. SQL: {connection_string, query}. Use list_enumerators for full schemas.",
                },
                "post_processing_prompt": {
                    "type": "string",
                    "description": "SCATTER-GATHER-SYNTHESIZE ONLY: Synthesis prompt that runs ONCE after ALL items complete. Describe what to generate from the aggregated data (reports, visualizations, exports, etc.). Leave empty/omit for map or scatter-gather patterns.",
                },
                "post_processing_name": {
                    "type": "string",
                    "description": "Human-readable name for the post-processing task (shown in dashboard). E.g., 'Generate HTML Report'.",
                },
                "post_processing_output_directory": {
                    "type": "string",
                    "description": "Directory where post-processing can write output files (absolute path). Required if post-processing needs to create files.",
                },
            },
            "required": ["name", "user_intent", "enumerator_type", "enumerator_config"],
        },
    },
    {
        "name": "start_job",
        "description": "Start a batch job. IMPORTANT: Open the dashboard (dashboard_open) BEFORE calling start_job so users can monitor progress. On first call, runs a test on the first work unit and returns results for review. Call again with approve=true to process remaining units, or approve=false to reject and reset. Use skip_test=true to bypass testing (or set ABP_SKIP_TEST=1 env var).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID to start"},
                "approve": {
                    "type": "boolean",
                    "description": "After test: true to approve and start full batch, false to reject and reset to CREATED",
                },
                "skip_test": {
                    "type": "boolean",
                    "description": "Skip the test phase and start immediately (default: false)",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "get_job_status",
        "description": "Get current status and progress of a job.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "The job ID to check"}},
            "required": ["job_id"],
        },
    },
]
