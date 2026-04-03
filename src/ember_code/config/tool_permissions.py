"""Tool permission settings — Claude Code-style allow/ask/deny with argument rules.

Reads from (highest priority last):
1. ~/.ember/settings.json (user global defaults)
2. ~/.ember/settings.local.json (user local overrides, runtime saves)
3. .ember/settings.json (project overrides, committed)
4. .ember/settings.local.json (project local overrides)

Format:
{
  "permissions": {
    "allow": [
      "Read",
      "Grep",
      "Bash(git status)",
      "Bash(git diff:*)",
      "WebFetch(domain:github.com)"
    ],
    "ask": ["Bash", "Write", "Edit"],
    "deny": ["WebSearch"]
  }
}

Rules:
- "ToolName"              — matches all calls to that tool
- "ToolName(exact args)"  — matches specific arguments
- "ToolName(prefix:*)"    — matches arguments starting with prefix
- "ToolName(key:value)"   — matches a specific key in the tool args dict
"""

import contextlib
import fnmatch
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default permission levels for each tool (bare tool name)
_DEFAULTS: dict[str, str] = {
    "Read": "allow",
    "Glob": "allow",
    "Grep": "allow",
    "LS": "allow",
    "Write": "ask",
    "Edit": "ask",
    "Bash": "ask",
    "BashOutput": "ask",
    "Python": "ask",
    "WebSearch": "deny",
    "WebFetch": "deny",
    "NotebookEdit": "ask",
}

# Maps Agno function names to our tool names
FUNC_TO_TOOL: dict[str, str] = {
    "run_shell_command": "Bash",
    "read_file": "Read",
    "save_file": "Write",
    "list_files": "LS",
    "edit_file": "Edit",
    "replace_in_file": "Edit",
    "grep_search": "Grep",
    "glob_files": "Glob",
    "web_fetch": "WebFetch",
    "duckduckgo_search": "WebSearch",
    "duckduckgo_news": "WebSearch",
    "run_python_code": "Python",
    "notebook_read": "NotebookEdit",
    "notebook_read_cell": "NotebookEdit",
    "notebook_edit_cell": "NotebookEdit",
    "notebook_add_cell": "NotebookEdit",
    "notebook_remove_cell": "NotebookEdit",
}

_RULE_RE = re.compile(r"^(\w+)(?:\((.+)\))?$")


def _parse_rule(rule: str) -> tuple[str, str | None]:
    """Parse a rule like 'Bash(git:*)' into (tool_name, arg_pattern)."""
    m = _RULE_RE.match(rule.strip())
    if not m:
        return rule.strip(), None
    return m.group(1), m.group(2)


def _args_to_str(tool_args: dict[str, Any] | None) -> str:
    """Convert tool args dict to a matchable string."""
    if not tool_args:
        return ""
    # For shell commands: join the args list
    if "args" in tool_args and isinstance(tool_args["args"], list):
        return " ".join(str(a) for a in tool_args["args"])
    # For file operations: use the path/file_path
    for key in ("path", "file_path", "file_name", "url", "query"):
        if key in tool_args:
            return str(tool_args[key])
    # Fallback: serialize all values
    return " ".join(str(v) for v in tool_args.values())


def _extract_domain(url: str) -> str:
    """Extract domain from a URL."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc
    except Exception as exc:
        logger.debug("Failed to extract domain from URL: %s", exc)
        return ""


def _match_rule_args(pattern: str, tool_name: str, tool_args: dict[str, Any] | None) -> bool:
    """Check if tool args match a rule's argument pattern.

    Patterns:
    - "git status"         → exact match against args string
    - "git:*"              → prefix wildcard match
    - "domain:github.com"  → key:value match against extracted properties
    - "path:src/*"         → glob match against file path
    """
    args_str = _args_to_str(tool_args)

    # key:value patterns
    if ":" in pattern:
        key, value = pattern.split(":", 1)

        if key == "domain" and tool_args:
            # Extract domain from URL args
            url = tool_args.get("url", "") or tool_args.get("query", "")
            domain = _extract_domain(str(url))
            return fnmatch.fnmatch(domain, value)

        if key == "path" and tool_args:
            path = (
                tool_args.get("path", "")
                or tool_args.get("file_path", "")
                or tool_args.get("file_name", "")
            )
            return fnmatch.fnmatch(str(path), value)

        # Generic: treat as prefix:glob against the full args string
        return fnmatch.fnmatch(args_str, f"{key} {value}" if " " not in key else pattern)

    # Direct match or glob against args string
    return fnmatch.fnmatch(args_str, pattern)


class ToolPermissions:
    """Resolves per-tool permission levels from settings files.

    Supports both bare tool rules ("Bash") and argument-specific rules
    ("Bash(git status)", "WebFetch(domain:github.com)").

    Resolution order for a specific call:
    1. Check argument-specific rules (most specific wins)
    2. Fall back to bare tool-level rule
    3. Fall back to default ("ask")
    """

    def __init__(self, project_dir: Path | None = None):
        self._project_dir = project_dir or Path.cwd()
        # Bare tool-level permissions
        self._tool_levels: dict[str, str] = dict(_DEFAULTS)
        # Argument-specific rules: list of (tool_name, arg_pattern, level)
        self._rules: list[tuple[str, str, str]] = []
        self._load()

    def _load(self) -> None:
        """Load settings files in priority order (last wins).

        Hierarchy:
        1. ~/.ember/settings.json (user global defaults)
        2. ~/.ember/settings.local.json (user local overrides)
        3. .ember/settings.json (project overrides, committed)
        4. .ember/settings.local.json (project local overrides, gitignored)
        """
        home_ember = Path.home() / ".ember"
        paths = [
            home_ember / "settings.json",
            home_ember / "settings.local.json",
            self._project_dir / ".ember" / "settings.json",
            self._project_dir / ".ember" / "settings.local.json",
        ]
        for path in paths:
            self._apply_file(path)

    def _apply_file(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            perms = data.get("permissions", {})
            for level in ("allow", "ask", "deny"):
                for rule in perms.get(level, []):
                    tool_name, arg_pattern = _parse_rule(rule)
                    if arg_pattern:
                        self._rules.append((tool_name, arg_pattern, level))
                    else:
                        self._tool_levels[tool_name] = level
        except Exception as e:
            logger.warning("Failed to load %s: %s", path, e)

    def check(
        self, tool_name: str, func_name: str | None = None, tool_args: dict[str, Any] | None = None
    ) -> str:
        """Check permission for a specific tool call.

        Args:
            tool_name: Our tool name (e.g. "Bash", "Write")
            func_name: Agno function name (e.g. "run_shell_command")
            tool_args: The actual arguments being passed

        Returns:
            "allow", "ask", or "deny"
        """
        # Resolve tool name from function name if needed
        if not tool_name and func_name:
            tool_name = FUNC_TO_TOOL.get(func_name, func_name)

        # Check argument-specific rules first (last matching rule wins)
        matched_level = None
        for rule_tool, arg_pattern, level in self._rules:
            if rule_tool == tool_name and _match_rule_args(arg_pattern, tool_name, tool_args):
                matched_level = level

        if matched_level is not None:
            return matched_level

        # Fall back to bare tool-level
        return self._tool_levels.get(tool_name, "ask")

    # Convenience methods for bare tool-level checks (used at registry time)
    def get_level(self, tool_name: str) -> str:
        return self._tool_levels.get(tool_name, "ask")

    def is_denied(self, tool_name: str) -> bool:
        return self.get_level(tool_name) == "deny"

    def needs_confirmation(self, tool_name: str) -> bool:
        return self.get_level(tool_name) == "ask"

    def has_arg_rules(self, tool_name: str) -> bool:
        """Check if there are argument-specific rules for this tool."""
        return any(t == tool_name for t, _, _ in self._rules)

    def save_rule(self, rule: str, level: str) -> None:
        """Persist a permission rule to ~/.ember/settings.local.json.

        Args:
            rule: e.g. "Bash", "Bash(git status)", "WebFetch(domain:github.com)"
            level: "allow", "ask", or "deny"
        """
        path = Path.home() / ".ember" / "settings.local.json"
        data: dict[str, Any] = {}
        if path.exists():
            with contextlib.suppress(Exception):
                data = json.loads(path.read_text())

        perms = data.setdefault("permissions", {})
        # Remove from other lists if exact match exists
        for key in ("allow", "ask", "deny"):
            lst = perms.get(key, [])
            if rule in lst:
                lst.remove(rule)

        # Add to the right list
        perms.setdefault(level, []).append(rule)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")

        # Update in-memory
        tool_name, arg_pattern = _parse_rule(rule)
        if arg_pattern:
            self._rules.append((tool_name, arg_pattern, level))
        else:
            self._tool_levels[tool_name] = level
