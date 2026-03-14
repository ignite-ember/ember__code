"""Tool registry — maps Claude Code tool names to Agno toolkit instances."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agno.tools.file import FileTools
from agno.tools.shell import ShellTools

from ember_code.tools.edit import EmberEditTools
from ember_code.tools.search import GlobTools, GrepTools
from ember_code.tools.web import WebTools


class ToolRegistry:
    """Factory that maps tool names to Agno toolkit instances.

    Uses the same tool names as Claude Code (Read, Write, Edit, Bash, etc.)
    and maps them to Agno toolkit classes.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self._factories: dict[str, Callable] = {
            "Read": self._make_read,
            "Write": self._make_write,
            "Edit": self._make_edit,
            "Bash": self._make_bash,
            "BashOutput": self._make_bash,
            "Grep": self._make_grep,
            "Glob": self._make_glob,
            "LS": self._make_ls,
            "WebSearch": self._make_web_search,
            "WebFetch": self._make_web_fetch,
            "Python": self._make_python,
        }

    @property
    def available_tools(self) -> list[str]:
        """List all available tool names."""
        return sorted(self._factories.keys())

    def register(self, name: str, factory: Callable) -> None:
        """Register a custom tool factory."""
        self._factories[name] = factory

    def resolve(self, tool_names: list[str] | str) -> list:
        """Resolve tool names to Agno toolkit instances.

        Args:
            tool_names: Comma-separated string or list of tool names.

        Returns:
            List of Agno toolkit instances.
        """
        if isinstance(tool_names, str):
            tool_names = [name.strip() for name in tool_names.split(",") if name.strip()]

        tools = []
        seen: set[str] = set()

        for name in tool_names:
            if name.startswith("MCP:") or name == "Orchestrate":
                continue

            if name not in self._factories:
                raise ValueError(f"Unknown tool: '{name}'. Available: {self.available_tools}")

            # Deduplicate (Bash and BashOutput map to the same toolkit)
            canonical = "Bash" if name == "BashOutput" else name
            if canonical in seen:
                continue
            seen.add(canonical)

            tools.append(self._factories[name]())

        return tools

    # ── Factory methods ───────────────────────────────────────────

    def _make_read(self):
        return FileTools(
            base_dir=self.base_dir,
            enable_read_file=True,
            enable_save_file=False,
            enable_list_files=True,
        )

    def _make_write(self):
        return FileTools(
            base_dir=self.base_dir,
            enable_read_file=True,
            enable_save_file=True,
            enable_list_files=True,
        )

    def _make_edit(self):
        return EmberEditTools(base_dir=str(self.base_dir))

    def _make_bash(self):
        return ShellTools()

    def _make_ls(self):
        return ShellTools()

    def _make_grep(self):
        return GrepTools(base_dir=str(self.base_dir))

    def _make_glob(self):
        return GlobTools(base_dir=str(self.base_dir))

    def _make_web_search(self):
        try:
            from agno.tools.duckduckgo import DuckDuckGoTools

            return DuckDuckGoTools()
        except ImportError:
            raise ImportError(
                "Web search requires duckduckgo-search. Install: pip install ember-code[web]"
            ) from None

    def _make_web_fetch(self):
        return WebTools()

    def _make_python(self):
        from agno.tools.python import PythonTools

        return PythonTools(base_dir=str(self.base_dir))


# Convenience function for backward compatibility
def resolve_tools(
    tool_names: list[str] | str,
    base_dir: str | None = None,
    config: Any = None,
) -> list:
    """Convenience wrapper around ToolRegistry.resolve()."""
    registry = ToolRegistry(base_dir=base_dir)
    return registry.resolve(tool_names)
