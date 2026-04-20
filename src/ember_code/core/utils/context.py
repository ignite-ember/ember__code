"""Context utilities — hierarchical project rules loading.

Loads project rules from multiple levels, checking both ``ember.md`` and
``CLAUDE.md`` at each location:

1. **User-level** — ``~/.ember/rules.md`` (global rules for all projects)
2. **Project root** — ``ember.md`` / ``CLAUDE.md`` at the project root
3. **Subdirectory** — ``ember.md`` / ``CLAUDE.md`` in any parent directory of
   the current working file, walking up to the project root

Rules are merged top-down: user → root → subdirectory (most specific wins on
conflict, but typically they're additive). At each level, both filenames are
checked and merged if both exist.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

USER_RULES_PATH = Path.home() / ".ember" / "rules.md"


def _rules_filenames(read_claude_md: bool = True) -> tuple[str, ...]:
    """Return the list of rules filenames to check."""
    if read_claude_md:
        return ("ember.md", "CLAUDE.md")
    return ("ember.md",)


def _read_if_exists(path: Path) -> str:
    """Read file contents if it exists, else return empty string."""
    try:
        if path.is_file():
            return path.read_text()
    except Exception as e:
        logger.debug("Failed to read rules from %s: %s", path, e)
    return ""


def _read_rules_dir(directory: Path, filenames: tuple[str, ...] = ("ember.md", "CLAUDE.md")) -> str:
    """Read rules from a directory, checking all candidate filenames.

    Returns concatenated contents of all found files, separated by newlines.
    """
    parts: list[str] = []
    for name in filenames:
        content = _read_if_exists(directory / name)
        if content:
            parts.append(content)
    return "\n\n".join(parts)


def load_user_rules() -> str:
    """Load user-level global rules from ``~/.ember/rules.md``."""
    return _read_if_exists(USER_RULES_PATH)


def load_project_rules(project_dir: Path, read_claude_md: bool = True) -> str:
    """Load project root rules (``ember.md`` and/or ``CLAUDE.md``)."""
    return _read_rules_dir(project_dir, _rules_filenames(read_claude_md))


def load_subdirectory_rules(
    project_dir: Path,
    working_dir: Path | None = None,
    read_claude_md: bool = True,
) -> list[tuple[str, str]]:
    """Collect rules from subdirectories between project root and working dir.

    Walks from ``working_dir`` up to (but not including) ``project_dir``,
    collecting any rules files found along the way.

    Returns:
        List of (relative_path, content) tuples, ordered shallowest first.
    """
    if working_dir is None:
        return []

    project_dir = project_dir.resolve()
    working_dir = working_dir.resolve()

    # working_dir must be inside project_dir
    try:
        working_dir.relative_to(project_dir)
    except ValueError:
        return []

    results: list[tuple[str, str]] = []
    current = working_dir

    filenames = _rules_filenames(read_claude_md)
    while current != project_dir:
        content = _read_rules_dir(current, filenames)
        if content:
            rel = current.relative_to(project_dir)
            results.append((str(rel), content))
        current = current.parent

    # Return shallowest first (closer to root = earlier in list)
    results.reverse()
    return results


def load_project_context(
    project_dir: Path,
    project_file: str = "ember.md",
    working_dir: Path | None = None,
    read_claude_md: bool = True,
) -> str:
    """Load and merge all applicable rules into a single context string.

    Checks for ``ember.md`` at every level, and also ``CLAUDE.md`` if
    ``read_claude_md`` is True. Merges rules from three levels:

    1. User-level (``~/.ember/rules.md``)
    2. Project root (``ember.md`` and optionally ``CLAUDE.md``)
    3. Subdirectory rules (walking from working_dir up to project root)

    Args:
        project_dir: The project root directory.
        project_file: Kept for config compatibility.
        working_dir: Optional current working subdirectory for subdirectory rules.
        read_claude_md: Whether to also read ``CLAUDE.md`` files (default True).

    Returns:
        Merged rules string with clear section headers, or empty string if no
        rules files exist.
    """
    sections: list[str] = []

    # 1. User-level rules
    user = load_user_rules()
    if user:
        sections.append(f"# User Rules (~/.ember/rules.md)\n\n{user}")

    # 2. Project root rules
    root = load_project_rules(project_dir, read_claude_md)
    if root:
        sections.append(f"# Project Rules\n\n{root}")

    # 3. Subdirectory rules
    for rel_path, content in load_subdirectory_rules(project_dir, working_dir, read_claude_md):
        sections.append(f"# Directory Rules ({rel_path}/)\n\n{content}")

    return "\n\n---\n\n".join(sections)
