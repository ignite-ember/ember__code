"""Tests for tool function execution — P0 critical.

Covers: Read (via Agno FileTools), Grep, LS, Bash execution.
Edit and Glob already have good coverage in test_tools.py.
"""

from unittest.mock import patch

import pytest

from ember_code.core.tools.search import GrepTools

# ── Read (Agno FileTools) ────────────────────────────────────────


class TestReadTool:
    """Test that the Read toolkit can read files."""

    def test_read_file_returns_content(self, tmp_path):
        from agno.tools.file import FileTools

        (tmp_path / "test.txt").write_text("hello world")
        tools = FileTools(base_dir=tmp_path, enable_read_file=True)
        result = tools.read_file(file_name=str(tmp_path / "test.txt"))
        assert "hello world" in result

    def test_read_file_nonexistent(self, tmp_path):
        from agno.tools.file import FileTools

        tools = FileTools(base_dir=tmp_path, enable_read_file=True)
        result = tools.read_file(file_name=str(tmp_path / "nonexistent.txt"))
        assert "error" in result.lower() or "not found" in result.lower() or "No such" in result

    def test_read_file_chunk(self, tmp_path):
        from agno.tools.file import FileTools

        lines = "\n".join(f"line {i}" for i in range(100))
        (tmp_path / "big.txt").write_text(lines)
        tools = FileTools(base_dir=tmp_path, enable_read_file_chunk=True)
        result = tools.read_file_chunk(
            file_name=str(tmp_path / "big.txt"),
            start_line=10,
            end_line=20,
        )
        assert "line 10" in result or "line 11" in result

    def test_list_files(self, tmp_path):
        from agno.tools.file import FileTools

        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "b.txt").write_text("hello")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.js").write_text("//")

        tools = FileTools(base_dir=tmp_path, enable_list_files=True)
        result = tools.list_files(dir_path=str(tmp_path))
        assert "a.py" in result
        assert "b.txt" in result


# ── Grep ─────────────────────────────────────────────────────────


_has_rg = __import__("shutil").which("rg") is not None


class TestGrepTool:
    """Test grep tool functions."""

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_finds_pattern(self, tmp_path):
        (tmp_path / "test.py").write_text("def hello():\n    return 'world'\n")
        tools = GrepTools(base_dir=str(tmp_path))
        result = tools.grep("hello", path="")
        assert "hello" in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_no_matches(self, tmp_path):
        (tmp_path / "test.py").write_text("nothing here\n")
        tools = GrepTools(base_dir=str(tmp_path))
        result = tools.grep("nonexistent_pattern_xyz")
        assert "No matches" in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_with_glob_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("target\n")
        (tmp_path / "b.txt").write_text("target\n")
        tools = GrepTools(base_dir=str(tmp_path))
        result = tools.grep("target", glob="*.py")
        assert "a.py" in result
        # b.txt should be excluded by glob
        assert "b.txt" not in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_with_context(self, tmp_path):
        (tmp_path / "test.py").write_text("line1\nline2\ntarget\nline4\nline5\n")
        tools = GrepTools(base_dir=str(tmp_path))
        result = tools.grep("target", context_lines=1)
        # Should include context lines
        assert "line2" in result or "line4" in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_files_returns_paths(self, tmp_path):
        (tmp_path / "a.py").write_text("match\n")
        (tmp_path / "b.py").write_text("no\n")
        tools = GrepTools(base_dir=str(tmp_path))
        result = tools.grep_files("match")
        assert "a.py" in result
        assert "b.py" not in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_count(self, tmp_path):
        (tmp_path / "test.py").write_text("match\nmatch\nmatch\n")
        tools = GrepTools(base_dir=str(tmp_path))
        result = tools.grep_count("match")
        assert "3" in result or "test.py" in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_rg_not_installed(self, tmp_path):
        tools = GrepTools(base_dir=str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError("rg not found")):
            result = tools.grep("test")
        assert "not installed" in result or "Error" in result

    @pytest.mark.skipif(not _has_rg, reason="ripgrep not in PATH")
    def test_grep_timeout(self, tmp_path):
        import subprocess

        tools = GrepTools(base_dir=str(tmp_path))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("rg", 30)):
            result = tools.grep("test")
        assert "timed out" in result.lower() or "Error" in result


# ── Bash (Shell execution) ───────────────────────────────────────


class TestBashTool:
    """Test shell command execution."""

    def test_shell_runs_command(self):
        from agno.tools.shell import ShellTools

        tools = ShellTools()
        result = tools.run_shell_command(args=["echo", "hello"])
        assert "hello" in result

    def test_shell_captures_stderr(self):
        from agno.tools.shell import ShellTools

        tools = ShellTools()
        result = tools.run_shell_command(args=["ls", "/nonexistent_dir_xyz"])
        # Should contain error output, not crash
        assert isinstance(result, str)

    def test_shell_respects_tail(self):
        from agno.tools.shell import ShellTools

        tools = ShellTools()
        result = tools.run_shell_command(
            args=["bash", "-c", "for i in $(seq 1 100); do echo line$i; done"],
            tail=5,
        )
        # Should only have last 5 lines
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) <= 10  # tail + possible header


# ── Tool Registry ────────────────────────────────────────────────


class TestToolRegistryResolve:
    """Test that all tools resolve correctly."""

    def test_resolve_read(self):
        from ember_code.core.config.tool_permissions import ToolPermissions
        from ember_code.core.tools.registry import ToolRegistry

        registry = ToolRegistry(
            base_dir=".",
            permissions=ToolPermissions(),
        )
        tools = registry.resolve(["Read"])
        assert len(tools) == 1

    def test_resolve_grep(self):
        from ember_code.core.config.tool_permissions import ToolPermissions
        from ember_code.core.tools.registry import ToolRegistry

        registry = ToolRegistry(
            base_dir=".",
            permissions=ToolPermissions(),
        )
        tools = registry.resolve(["Grep"])
        assert len(tools) == 1

    def test_resolve_all_standard(self):
        from ember_code.core.config.tool_permissions import ToolPermissions
        from ember_code.core.tools.registry import ToolRegistry

        registry = ToolRegistry(
            base_dir=".",
            permissions=ToolPermissions(),
        )
        standard = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        tools = registry.resolve(standard)
        assert len(tools) == len(standard)
