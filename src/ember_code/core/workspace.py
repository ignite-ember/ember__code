"""Multi-workspace manager for --add-dir support."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages multiple project directories for cross-repo operations.

    The primary directory is the main project. Additional directories are
    added via ``--add-dir`` and made available to all tools via absolute paths.
    """

    def __init__(self, primary_dir: Path, additional_dirs: list[Path] | None = None):
        self.primary_dir = primary_dir.resolve()
        self.additional_dirs: list[Path] = []

        for d in additional_dirs or []:
            resolved = d.resolve()
            if not resolved.is_dir():
                raise ValueError(f"Additional directory does not exist: {d}")
            if resolved != self.primary_dir:
                self.additional_dirs.append(resolved)

    @property
    def all_dirs(self) -> list[Path]:
        """All workspace directories (primary first)."""
        return [self.primary_dir, *self.additional_dirs]

    @property
    def is_multi(self) -> bool:
        """Whether multiple directories are configured."""
        return len(self.additional_dirs) > 0

    def get_context_instructions(self) -> str:
        """Return a system prompt fragment listing all workspace directories.

        Agents use this to know about all available workspaces and should
        use absolute paths when working across directories.
        """
        if not self.additional_dirs:
            return ""

        lines = [
            "## Active Workspaces",
            "",
            "You have access to multiple project directories. Use absolute paths when referencing files.",
            "",
            f"**Primary:** `{self.primary_dir}`",
        ]
        for i, d in enumerate(self.additional_dirs, 1):
            lines.append(f"**Additional [{i}]:** `{d}`")
        lines.append("")
        lines.append(
            "When searching or reading files, specify which workspace you're operating in. "
            "Tools accept absolute paths and will work across all workspaces."
        )
        return "\n".join(lines)

    def short_label(self) -> str:
        """Short label for status bar display (e.g., '+2 dirs')."""
        if not self.additional_dirs:
            return ""
        return f"+{len(self.additional_dirs)} dir{'s' if len(self.additional_dirs) > 1 else ''}"
