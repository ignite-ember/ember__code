"""Context utilities — project context loading.

Conversation history is managed natively by Agno via ``Agent(db=...,
session_id=..., add_history_to_context=True)``.  This module only
handles loading project-level instructions (e.g. ``ember.md``).
"""

from pathlib import Path


def load_project_context(project_dir: Path, project_file: str = "ember.md") -> str:
    """Load project instructions from a file (e.g. ``ember.md``).

    Returns the file contents, or an empty string if the file does not exist.
    """
    path = project_dir / project_file
    if path.exists():
        return path.read_text()
    return ""
