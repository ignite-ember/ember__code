"""EmberEditTools — targeted string-replacement editing."""

from pathlib import Path

from agno.tools import Toolkit


class EmberEditTools(Toolkit):
    """Targeted string-replacement editing tools.

    Instead of rewriting entire files, these tools replace specific text spans,
    producing minimal, reviewable diffs. Inspired by Claude Code's Edit tool.
    """

    def __init__(self, base_dir: str | None = None, **kwargs):
        super().__init__(name="ember_edit", **kwargs)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.register(self.edit_file)
        self.register(self.edit_file_replace_all)
        self.register(self.create_file)

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to base_dir."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    def edit_file(self, file_path: str, old_string: str, new_string: str) -> str:
        """Replace a specific string in a file. The old_string must appear exactly once.

        Args:
            file_path: Path to the file to edit.
            old_string: The exact text to find and replace. Must be unique in the file.
            new_string: The replacement text.

        Returns:
            Success or error message.
        """
        path = self._resolve_path(file_path)

        if not path.exists():
            return f"Error: File not found: {path}"

        content = path.read_text()
        count = content.count(old_string)

        if count == 0:
            return f"Error: old_string not found in {path}. Make sure the string matches exactly (including whitespace and indentation)."

        if count > 1:
            return f"Error: old_string appears {count} times in {path}. Provide more surrounding context to make it unique, or use edit_file_replace_all."

        new_content = content.replace(old_string, new_string, 1)
        path.write_text(new_content)

        return f"Successfully edited {path}"

    def edit_file_replace_all(self, file_path: str, old_string: str, new_string: str) -> str:
        """Replace ALL occurrences of a string in a file.

        Args:
            file_path: Path to the file to edit.
            old_string: The text to find.
            new_string: The replacement text.

        Returns:
            Success message with count of replacements.
        """
        path = self._resolve_path(file_path)

        if not path.exists():
            return f"Error: File not found: {path}"

        content = path.read_text()
        count = content.count(old_string)

        if count == 0:
            return f"Error: old_string not found in {path}."

        new_content = content.replace(old_string, new_string)
        path.write_text(new_content)

        return f"Successfully replaced {count} occurrence(s) in {path}"

    def create_file(self, file_path: str, content: str) -> str:
        """Create a new file. Fails if the file already exists.

        Args:
            file_path: Path for the new file.
            content: File content.

        Returns:
            Success or error message.
        """
        path = self._resolve_path(file_path)

        if path.exists():
            return f"Error: File already exists: {path}. Use edit_file to modify it."

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

        return f"Successfully created {path}"
