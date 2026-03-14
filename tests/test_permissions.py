"""Tests for config/permissions.py."""

import pytest

from ember_code.config.permissions import PermissionGuard
from ember_code.config.settings import PermissionsConfig, Settings


class TestPermissionGuard:
    @pytest.fixture
    def guard(self, tmp_path):
        """Guard with all-allow permissions for testing."""
        settings = Settings(
            permissions=PermissionsConfig(
                file_read="allow",
                file_write="allow",
                shell_execute="allow",
            )
        )
        g = PermissionGuard(settings)
        g.permissions_path = tmp_path / "permissions.yaml"
        return g

    @pytest.fixture
    def strict_guard(self, tmp_path):
        """Guard with deny permissions."""
        settings = Settings(
            permissions=PermissionsConfig(
                file_read="deny",
                file_write="deny",
                shell_execute="deny",
            )
        )
        g = PermissionGuard(settings)
        g.permissions_path = tmp_path / "permissions.yaml"
        return g

    def test_file_read_allow(self, guard):
        assert guard.check_file_read("any_file.py") is True

    def test_file_read_deny(self, strict_guard):
        assert strict_guard.check_file_read("any_file.py") is False

    def test_file_write_allow(self, guard):
        assert guard.check_file_write("any_file.py") is True

    def test_file_write_deny(self, strict_guard):
        assert strict_guard.check_file_write("any_file.py") is False

    def test_shell_execute_allow(self, guard):
        assert guard.check_shell_execute("ls -la") is True

    def test_shell_execute_deny(self, strict_guard):
        assert strict_guard.check_shell_execute("ls -la") is False

    def test_protected_path_blocks_write(self, tmp_path):
        settings = Settings(
            permissions=PermissionsConfig(file_write="allow"),
        )
        guard = PermissionGuard(settings)
        guard.permissions_path = tmp_path / "permissions.yaml"
        assert guard.check_file_write(".env") is False
        assert guard.check_file_write("secrets.json") is False
        assert guard.check_file_write("server.pem") is False
        assert guard.check_file_write("private.key") is False

    def test_blocked_command(self, tmp_path):
        settings = Settings(
            permissions=PermissionsConfig(shell_execute="allow"),
        )
        guard = PermissionGuard(settings)
        guard.permissions_path = tmp_path / "permissions.yaml"
        assert guard.check_shell_execute("rm -rf /") is False

    def test_is_protected_path(self, tmp_path):
        settings = Settings()
        guard = PermissionGuard(settings)
        guard.permissions_path = tmp_path / "permissions.yaml"

        assert guard._is_protected_path(".env") is True
        assert guard._is_protected_path(".env.production") is True
        assert guard._is_protected_path("server.pem") is True
        assert guard._is_protected_path("my.key") is True
        assert guard._is_protected_path("credentials.json") is True
        assert guard._is_protected_path("secrets.yaml") is True
        assert guard._is_protected_path("regular_file.py") is False

    def test_is_blocked_command(self, tmp_path):
        settings = Settings()
        guard = PermissionGuard(settings)
        guard.permissions_path = tmp_path / "permissions.yaml"

        assert guard._is_blocked_command("rm -rf /") is True
        assert guard._is_blocked_command(":(){ :|:& };:") is True
        assert guard._is_blocked_command("ls -la") is False

    def test_allowlist_matching(self, tmp_path):
        settings = Settings(
            permissions=PermissionsConfig(file_write="ask"),
        )
        guard = PermissionGuard(settings)
        guard.permissions_path = tmp_path / "permissions.yaml"
        guard.allowlist = {"file_write": ["src/*", "tests/*"]}

        assert guard._is_in_allowlist("file_write", "src/main.py") is True
        assert guard._is_in_allowlist("file_write", "tests/test_x.py") is True
        assert guard._is_in_allowlist("file_write", "config/secret.yaml") is False

    def test_generate_pattern(self):
        assert PermissionGuard._generate_pattern("npm test") == "npm *"
        assert PermissionGuard._generate_pattern("pytest tests/") == "pytest *"
        assert PermissionGuard._generate_pattern("src/auth.py") == "src/*"
        assert PermissionGuard._generate_pattern("standalone") == "standalone"
