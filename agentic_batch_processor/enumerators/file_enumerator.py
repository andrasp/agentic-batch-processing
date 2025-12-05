"""File-based enumerator using glob patterns.

Enumerates files from the filesystem matching glob patterns.
This is the most common enumerator for batch file processing tasks.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseEnumerator, EnumeratorResult
from .registry import register_enumerator


@register_enumerator
class FileEnumerator(BaseEnumerator):
    """Enumerate files using glob patterns.

    Configuration:
        base_directory: Root directory to search in
        pattern: Glob pattern (e.g., "**/*.jpg", "*.txt")
        exclude_patterns: Optional list of patterns to exclude
        include_hidden: Whether to include hidden files (default: False)

    Each enumerated item has payload:
        {
            "file_path": "/absolute/path/to/file.jpg",
            "relative_path": "subdir/file.jpg",
            "file_name": "file.jpg",
            "file_extension": ".jpg",
            "file_size": 12345
        }
    """

    enumerator_type = "file"
    description = "Enumerate files from filesystem using glob patterns"

    def __init__(self, config: Dict[str, Any]):
        """Initialize file enumerator.

        Args:
            config: Configuration with base_directory and pattern
        """
        self.base_directory = Path(config.get("base_directory", "."))
        self.pattern = config.get("pattern", "**/*")
        self.exclude_patterns = config.get("exclude_patterns", [])
        self.include_hidden = config.get("include_hidden", False)
        self.limit = config.get("limit")

    def validate_config(self) -> Optional[str]:
        """Validate configuration."""
        if not self.base_directory.exists():
            return f"Base directory does not exist: {self.base_directory}"

        if not self.base_directory.is_dir():
            return f"Base directory is not a directory: {self.base_directory}"

        if not self.pattern:
            return "Pattern cannot be empty"

        return None

    def enumerate(self) -> EnumeratorResult:
        """Enumerate files matching the pattern."""

        error = self.validate_config()
        if error:
            return EnumeratorResult(success=False, error=error)

        try:
            items = []
            base_resolved = self.base_directory.resolve()

            for file_path in base_resolved.glob(self.pattern):

                if not file_path.is_file():
                    continue

                if not self.include_hidden and file_path.name.startswith("."):
                    continue

                relative = file_path.relative_to(base_resolved)
                excluded = False
                for exclude in self.exclude_patterns:
                    if relative.match(exclude):
                        excluded = True
                        break
                if excluded:
                    continue

                item = {
                    "file_path": str(file_path),
                    "relative_path": str(relative),
                    "file_name": file_path.name,
                    "file_extension": file_path.suffix.lower(),
                    "file_size": file_path.stat().st_size,
                }
                items.append(item)

                if self.limit and len(items) >= self.limit:
                    break

            items.sort(key=lambda x: x["file_path"])

            extensions = {}
            for item in items:
                ext = item["file_extension"] or "(no extension)"
                extensions[ext] = extensions.get(ext, 0) + 1

            return EnumeratorResult(
                success=True,
                items=items,
                metadata={
                    "base_directory": str(base_resolved),
                    "pattern": self.pattern,
                    "file_counts_by_extension": extensions,
                },
            )

        except Exception as e:
            return EnumeratorResult(success=False, error=f"File enumeration failed: {str(e)}")

    def get_sample_item(self) -> Optional[Dict[str, Any]]:
        """Get first matching file for testing."""

        original_limit = self.limit
        self.limit = 1

        result = self.enumerate()

        self.limit = original_limit

        if result.success and result.items:
            return result.items[0]
        return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get JSON schema for file enumerator configuration."""
        return {
            "type": "object",
            "properties": {
                "base_directory": {"type": "string", "description": "Root directory to search for files"},
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '**/*.jpg', '*.txt')",
                    "default": "**/*",
                },
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns to exclude from results",
                    "default": [],
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Whether to include hidden files (starting with .)",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of files to enumerate (for testing)",
                    "minimum": 1,
                },
            },
            "required": ["base_directory"],
            "additionalProperties": False,
        }
