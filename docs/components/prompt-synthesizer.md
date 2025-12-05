# Prompt Synthesizer

The Prompt Synthesizer transforms high-level user intent into detailed prompts that worker LLMs can execute autonomously. It bridges the gap between what the user wants ("rotate all images 90 degrees") and what the worker needs to know to accomplish the task.

## Purpose

When a user describes their intent, they speak at a high level. But each worker processing an individual item needs:

- Clear context about what they're processing
- The specific task to accomplish
- Instructions for autonomous operation
- Guidance on handling outputs and errors

The synthesizer generates this detailed prompt once, and it's reused (with per-item substitution) for every work unit in the job.

## Prompt Structure

Generated prompts follow a consistent structure:

1. **Context**: What the worker is processing and why
2. **Work Unit Data**: Placeholders for item-specific information
3. **Task**: The user's intent, clearly stated
4. **Instructions**: Guidance for autonomous operation
5. **Output Handling**: How to handle results
6. **Closing**: Direction to report success or failure

## Placeholder Substitution

Prompts contain placeholders in `{field_name}` format that are filled with work unit payload data at execution time. Common placeholders:

- `{file_path}`: Full path to the file being processed
- `{file_name}`: Just the filename
- `{file_extension}`: The file extension
- Custom fields from other enumerator types

The worker implementation handles this substitution before sending the prompt to the LLM.

## Synthesis Methods

### synthesize_file_processing_prompt()

For file-based work units. Generates prompts with:

- FILE TO PROCESS section with `{file_path}` placeholder
- Default output handling: modify in place, preserve permissions
- Option for custom output instructions

### synthesize_generic_prompt()

For non-file work units (SQL records, CSV rows, JSON items, etc.). Generates prompts with:

- WORK UNIT DATA section explaining the payload
- Optional payload field descriptions
- Flexible structure for any data type

### synthesize_from_template()

For custom prompt templates. Allows users to provide their own template structure while still benefiting from placeholder substitution.

## Convenience Functions

The module provides helper functions for common use cases:

### create_image_processing_prompt()

Adds image-specific context:
- "This is an image file. Use appropriate image processing tools."
- Guidance on backups, quality, and reporting dimensions

### create_code_processing_prompt()

Adds code-specific context:
- "This is a source code file. Preserve syntax and formatting."
- Guidance on code structure, comments, and validity

### create_document_processing_prompt()

Adds document-specific context:
- "This is a document file. Preserve formatting and structure."
- Guidance on formatting, metadata, and change reporting

## Worker Autonomy

A key principle reflected in all generated prompts is worker autonomy. Every prompt includes:

- "Work autonomously - you have full tool access"
- "If you encounter errors, try to resolve them or fail gracefully"

This instructs the worker LLM to take action, not just analyze or suggest. Workers are expected to actually modify files, make API calls, update databases — whatever the task requires.

## Integration with Orchestrator

The Orchestrator calls the synthesizer during job creation:

1. For file enumerators: uses `synthesize_file_processing_prompt()`
2. For other enumerators: uses `synthesize_generic_prompt()`

The generated prompt is stored on the Job record as `worker_prompt_template` and passed to every worker.

## Extensibility

Custom synthesizers can be provided to the Orchestrator constructor. This allows:

- Domain-specific prompt structures
- Additional instructions or constraints
- Different output handling patterns
- Integration with prompt engineering tools

## Example Output

For user intent "Describe all objects in the image and add alt text":

```
You are processing a file as part of a batch operation.

FILE TO PROCESS: {file_path}

YOUR TASK:
Describe all objects in the image and add alt text

ADDITIONAL CONTEXT:
This is an image file. Use appropriate image processing tools.

INSTRUCTIONS:
- Use your available tools to complete this task
- Work autonomously - you have full tool access
- If you encounter errors, try to resolve them or fail gracefully
- Report your results clearly at the end

OUTPUT HANDLING:
- For destructive operations, consider backing up the original
- Maintain image quality where possible
- Report final file size and dimensions

Complete the task and report success or failure.
```
