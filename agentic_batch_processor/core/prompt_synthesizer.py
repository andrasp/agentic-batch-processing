"""Prompt synthesizer for generating per-item worker prompts.

Takes high-level user intent and generates detailed prompts for individual
work units that worker LLMs can execute autonomously.
"""

from typing import Dict, Optional


class PromptSynthesizer:
    """Generates per-item prompts from user intent.

    The synthesizer translates high-level user requests like:
    "rotate all images 90 degrees clockwise and reduce size"

    Into detailed worker prompts like:
    "You are processing the file at {file_path}.
    Your task:
    1. Load the image
    2. Rotate it 90 degrees clockwise
    3. Reduce file size by optimizing compression
    4. Save back to original location
    Use your available tools to accomplish this."
    """

    def synthesize_file_processing_prompt(
        self, user_intent: str, additional_context: Optional[str] = None, output_instructions: Optional[str] = None
    ) -> str:
        """Synthesize a prompt for file processing tasks.

        Args:
            user_intent: User's complete description of what to do (including outputs)
            additional_context: Optional context about the task
            output_instructions: How to handle outputs (usually embedded in user_intent)

        Returns:
            Prompt template with {file_path} and other placeholders
        """
        prompt_parts = [
            "You are processing a file as part of a batch operation.",
            "",
            "FILE TO PROCESS: {file_path}",
            "",
            "=== YOUR COMPLETE TASK ===",
            "The following describes EVERYTHING you must do. Follow ALL instructions including any output/storage requirements:",
            "",
            f"{user_intent}",
            "",
            "=== END TASK ===",
        ]

        if additional_context:
            prompt_parts.extend(["", "ADDITIONAL CONTEXT:", additional_context])

        prompt_parts.extend(
            [
                "",
                "EXECUTION GUIDELINES:",
                "- Use your available tools to complete this task",
                "- Work autonomously - you have full tool access",
                "- If you encounter errors, try to resolve them or fail gracefully",
                "- Complete ALL parts of the task above, including any output requirements",
                "- Report your results clearly at the end",
            ]
        )

        if output_instructions:
            prompt_parts.extend(["", "ADDITIONAL OUTPUT HANDLING:", output_instructions])

        prompt_parts.extend(["", "Complete ALL aspects of the task and report success or failure."])

        return "\n".join(prompt_parts)

    def synthesize_generic_prompt(
        self,
        user_intent: str,
        unit_type: Optional[str] = None,
        payload_description: Optional[Dict[str, str]] = None,
        additional_instructions: Optional[str] = None,
    ) -> str:
        """Synthesize a generic prompt for any work unit type.

        Args:
            user_intent: Complete description of what to accomplish (including outputs)
            unit_type: Type of work unit (file, url, record, etc.)
            payload_description: Map of payload field -> description
            additional_instructions: Extra guidance for the worker

        Returns:
            Prompt template with payload placeholders
        """
        if unit_type:
            prompt_parts = [
                f"You are processing a {unit_type} as part of a batch operation.",
            ]
        else:
            prompt_parts = [
                "You are processing an item as part of a batch operation.",
            ]

        prompt_parts.extend(
            [
                "",
                "WORK UNIT DATA:",
                "The payload for this work unit is provided below. Use the data to complete your task.",
            ]
        )

        if payload_description:
            prompt_parts.append("")
            for field, description in payload_description.items():
                prompt_parts.append(f"- {field}: { {field}}  ({description})")

        prompt_parts.extend(
            [
                "",
                "=== YOUR COMPLETE TASK ===",
                "The following describes EVERYTHING you must do. Follow ALL instructions including any output/storage requirements:",
                "",
                f"{user_intent}",
                "",
                "=== END TASK ===",
                "",
                "EXECUTION GUIDELINES:",
                "- Use your available tools to complete this task",
                "- Work autonomously - you have full tool access",
                "- If you encounter errors, try to resolve them or fail gracefully",
                "- Complete ALL parts of the task above, including any output requirements",
                "- Report your results clearly at the end",
            ]
        )

        if additional_instructions:
            prompt_parts.extend(["", "ADDITIONAL GUIDANCE:", additional_instructions])

        prompt_parts.extend(["", "Complete ALL aspects of the task and report success or failure."])

        return "\n".join(prompt_parts)
