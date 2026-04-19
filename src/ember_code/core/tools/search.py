"""Search tools — Grep (ripgrep) and Glob (pathlib) wrappers."""

import subprocess
from pathlib import Path

from agno.tools import Toolkit


class GrepTools(Toolkit):
    """Content search using ripgrep (rg)."""

    def __init__(self, base_dir: str | None = None, **kwargs):
        super().__init__(name="ember_grep", **kwargs)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.register(self.grep)
        self.register(self.grep_files)
        self.register(self.grep_count)

    def grep(
        self,
        pattern: str,
        path: str = "",
        glob: str = "",
        file_type: str = "",
        context_lines: int = 0,
        max_results: int = 50,
    ) -> str:
        """Search file contents with regex using ripgrep.

        Args:
            pattern: Regex pattern to search for.
            path: Directory or file to search in. Defaults to project root.
            glob: Glob pattern to filter files (e.g., "*.py").
            file_type: File type filter (e.g., "py", "js").
            context_lines: Number of context lines around matches.
            max_results: Maximum results to return.

        Returns:
            Matching lines with file paths and line numbers.
        """
        cmd = ["rg", "--no-heading", "-n"]

        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])
        if glob:
            cmd.extend(["--glob", glob])
        if file_type:
            cmd.extend(["--type", file_type])

        cmd.extend(["-m", str(max_results)])
        cmd.append(pattern)

        search_path = str(self.base_dir / path) if path else str(self.base_dir)
        cmd.append(search_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout[:10000] or "No matches found."
            elif result.returncode == 1:
                return "No matches found."
            else:
                return f"Error running ripgrep: {result.stderr}"
        except FileNotFoundError:
            return "Error: ripgrep (rg) is not installed. Install it: brew install ripgrep"
        except subprocess.TimeoutExpired:
            return "Error: Search timed out after 30 seconds."

    def grep_files(self, pattern: str, path: str = "", glob: str = "") -> str:
        """Search and return only matching file paths.

        Args:
            pattern: Regex pattern to search for.
            path: Directory to search in.
            glob: Glob pattern to filter files.

        Returns:
            List of file paths containing matches.
        """
        cmd = ["rg", "--files-with-matches"]
        if glob:
            cmd.extend(["--glob", glob])
        cmd.append(pattern)

        search_path = str(self.base_dir / path) if path else str(self.base_dir)
        cmd.append(search_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout or "No matching files found."
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return f"Error: {e}"

    def grep_count(self, pattern: str, path: str = "") -> str:
        """Return match counts per file.

        Args:
            pattern: Regex pattern to search for.
            path: Directory to search in.

        Returns:
            File paths with match counts.
        """
        cmd = ["rg", "--count", pattern]
        search_path = str(self.base_dir / path) if path else str(self.base_dir)
        cmd.append(search_path)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout or "No matches found."
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return f"Error: {e}"


class GlobTools(Toolkit):
    """File pattern matching using pathlib."""

    def __init__(self, base_dir: str | None = None, **kwargs):
        super().__init__(name="ember_glob", **kwargs)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.register(self.glob_files)

    def glob_files(self, pattern: str, path: str = "", max_results: int = 100) -> str:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "**/*.py", "src/**/*.ts").
            path: Subdirectory to search in. Defaults to project root.
            max_results: Maximum number of results.

        Returns:
            List of matching file paths, sorted by modification time.
        """
        search_dir = self.base_dir / path if path else self.base_dir

        if not search_dir.exists():
            return f"Error: Directory not found: {search_dir}"

        _SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".tox", ".mypy_cache"}

        matches = []
        for p in search_dir.glob(pattern):
            if p.is_file() and not (_SKIP_DIRS & set(p.parts)):
                matches.append(p)
                if len(matches) >= max_results:
                    break

        # Sort by modification time (newest first)
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if not matches:
            return f"No files matching '{pattern}' found in {search_dir}"

        lines = [str(p.relative_to(self.base_dir)) for p in matches]
        return "\n".join(lines)
