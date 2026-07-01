"""EmberEditTools — targeted string-replacement editing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from agno.tools import Toolkit

logger = logging.getLogger(__name__)


# ── File-edit notification hook ─────────────────────────────────────
#
# The backend wires a callback here at startup (see
# ``backend/__main__.py``) that turns every successful edit into a
# ``file_edited`` PushNotification. Downstream clients react:
#
#   • JetBrains plugin   → ``LocalFileSystem.refreshAndFindFileByPath``
#                          (Local History captures the change, open
#                          editor tabs reload, the "modified
#                          externally" prompt stops firing).
#   • VSCode extension   → ``workspace.openTextDocument`` reveal +
#                          ``editor.action.revert`` reload.
#   • Tauri / web        → no-op (the FE doesn't own an editor).
#
# Keeping the hook a module-level callable instead of a constructor
# arg means we don't have to thread the wiring through every agent's
# toolkit construction site, and tests + the TUI can leave it unset.

_FileEditListener = Callable[[str], None]
_listener: _FileEditListener | None = None


def set_file_edit_listener(fn: _FileEditListener | None) -> None:
    """Register (or clear) the callback fired after each successful
    edit. ``fn`` receives the absolute path of the file that was
    written. Exceptions are swallowed so a flaky listener can never
    break an edit."""
    global _listener
    _listener = fn


def _notify(path: Path) -> None:
    fn = _listener
    if fn is None:
        return
    try:
        fn(str(path))
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("file-edit listener raised: %s", exc)


class EmberEditTools(Toolkit):
    """Targeted string-replacement editing tools.

    Instead of rewriting entire files, these tools replace specific text spans,
    producing minimal, reviewable diffs. Inspired by Claude Code's Edit tool.
    """

    def __init__(self, base_dir: str | None = None, **kwargs):
        confirm_tools = kwargs.pop("requires_confirmation_tools", None)
        super().__init__(name="ember_edit", **kwargs)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.register(self.edit_file)
        self.register(self.edit_file_replace_all)
        self.register(self.create_file)
        if confirm_tools:
            self.requires_confirmation_tools = confirm_tools
            # Same async-vs-sync split as ``shell.py`` — iterate
            # BOTH registries. Agno routes async callables into
            # ``async_functions``; skipping that dict silently
            # fails to gate them, which is the exact hole that
            # let ``run_shell_command`` slip past HITL in v0.8.0.
            for registry in (self.functions, self.async_functions):
                for name, func in registry.items():
                    if name in confirm_tools:
                        func.requires_confirmation = True

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
        _notify(path)

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
        _notify(path)

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
        _notify(path)

        return f"Successfully created {path}"
