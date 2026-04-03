"""Tests for protected path enforcement in ToolEventHook."""

import pytest

from ember_code.hooks.executor import HookExecutor
from ember_code.hooks.tool_hook import ToolEventHook, _is_protected_path

# ── _is_protected_path unit tests ──────────────────────────────────────


class TestIsProtectedPath:
    """Unit tests for the _is_protected_path helper."""

    def test_exact_filename_match(self):
        assert _is_protected_path(".env", [".env"])

    def test_glob_pattern_match(self):
        assert _is_protected_path(".env.production", [".env.*"])

    def test_wildcard_extension(self):
        assert _is_protected_path("server.pem", ["*.pem"])
        assert _is_protected_path("private.key", ["*.key"])

    def test_no_match(self):
        assert not _is_protected_path("app.py", [".env", "*.pem"])

    def test_full_path_filename_match(self):
        assert _is_protected_path("/home/user/project/.env", [".env"])

    def test_full_path_glob_match(self):
        assert _is_protected_path("/home/user/project/cert.pem", ["*.pem"])

    def test_credentials_pattern(self):
        assert _is_protected_path("credentials.json", ["credentials.*"])
        assert _is_protected_path("credentials.yaml", ["credentials.*"])

    def test_secrets_pattern(self):
        assert _is_protected_path("secrets.yaml", ["secrets.*"])

    def test_empty_patterns(self):
        assert not _is_protected_path(".env", [])

    def test_full_path_pattern(self):
        # fnmatch against the full path string
        assert _is_protected_path("config/secrets.yaml", ["config/*"])


# ── ToolEventHook protected path enforcement ───────────────────────────


class TestToolEventHookProtectedPaths:
    """Tests that ToolEventHook blocks writes to protected paths."""

    @pytest.fixture()
    def hook(self):
        """Hook with protected paths, no user-configured hooks."""
        executor = HookExecutor(hooks={})
        return ToolEventHook(
            executor=executor,
            session_id="test",
            protected_paths=[".env", ".env.*", "*.pem", "*.key", "credentials.*", "secrets.*"],
        )

    def test_blocks_save_file_to_env(self, hook):
        result = hook(
            name="save_file",
            func=lambda **kw: "written",
            args={"file_path": "/project/.env"},
        )
        assert "Blocked" in result
        assert ".env" in result

    def test_blocks_edit_file_to_pem(self, hook):
        result = hook(
            name="edit_file",
            func=lambda **kw: "edited",
            args={"file_path": "/project/cert.pem", "old_string": "a", "new_string": "b"},
        )
        assert "Blocked" in result

    def test_blocks_create_file_to_key(self, hook):
        result = hook(
            name="create_file",
            func=lambda **kw: "created",
            args={"file_path": "private.key"},
        )
        assert "Blocked" in result

    def test_blocks_edit_file_replace_all(self, hook):
        result = hook(
            name="edit_file_replace_all",
            func=lambda **kw: "replaced",
            args={"file_path": "secrets.yaml"},
        )
        assert "Blocked" in result

    def test_allows_write_to_normal_file(self, hook):
        called = {}

        def fake_write(**kwargs):
            called["yes"] = True
            return "ok"

        result = hook(
            name="save_file",
            func=fake_write,
            args={"file_path": "src/app.py"},
        )
        assert result == "ok"
        assert called.get("yes")

    def test_allows_read_of_protected_file(self, hook):
        """Read tools should never be blocked — only writes."""
        called = {}

        def fake_read(**kwargs):
            called["yes"] = True
            return "contents"

        result = hook(
            name="read_file",
            func=fake_read,
            args={"file_path": ".env"},
        )
        assert result == "contents"
        assert called.get("yes")

    def test_allows_shell_command(self, hook):
        """Shell commands are not write tools — should pass through."""
        called = {}

        def fake_shell(**kwargs):
            called["yes"] = True
            return "output"

        result = hook(
            name="run_shell_command",
            func=fake_shell,
            args={"args": ["cat", ".env"]},
        )
        assert result == "output"
        assert called.get("yes")

    def test_no_protected_paths_allows_all(self):
        """When no protected paths configured, all writes pass through."""
        executor = HookExecutor(hooks={})
        hook = ToolEventHook(executor=executor, session_id="test", protected_paths=[])
        called = {}

        def fake_write(**kwargs):
            called["yes"] = True
            return "ok"

        result = hook(
            name="save_file",
            func=fake_write,
            args={"file_path": ".env"},
        )
        assert result == "ok"
        assert called.get("yes")

    def test_blocks_env_variant(self, hook):
        result = hook(
            name="save_file",
            func=lambda **kw: "written",
            args={"file_path": "/app/.env.local"},
        )
        assert "Blocked" in result

    def test_func_not_called_when_blocked(self, hook):
        """The actual tool function must NOT be called when path is protected."""
        called = {}

        def should_not_run(**kwargs):
            called["ran"] = True
            return "bad"

        hook(
            name="save_file",
            func=should_not_run,
            args={"file_path": "credentials.json"},
        )
        assert "ran" not in called
