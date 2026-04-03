"""Tests for tui/hitl_handler.py — HITL pure functions and permission flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.tui.hitl_handler import (
    HITLHandler,
    _build_pattern_rule,
    _build_rule,
    _format_args_detail,
    _format_args_short,
)

# ── Pure function tests: _format_args_short ────────────────────


class TestFormatArgsShort:
    def test_shell_command(self):
        result = _format_args_short({"args": ["git", "status"]})
        assert result == "git status"

    def test_shell_command_single(self):
        result = _format_args_short({"args": ["ls"]})
        assert result == "ls"

    def test_path_key(self):
        result = _format_args_short({"path": "/tmp/foo.py"})
        assert result == "/tmp/foo.py"

    def test_file_path_key(self):
        result = _format_args_short({"file_path": "src/main.py"})
        assert result == "src/main.py"

    def test_url_key(self):
        result = _format_args_short({"url": "https://example.com"})
        assert result == "https://example.com"

    def test_query_key(self):
        result = _format_args_short({"query": "search term"})
        assert result == "search term"

    def test_priority_order(self):
        # path wins over url
        result = _format_args_short({"path": "/a", "url": "http://b"})
        assert result == "/a"

    def test_fallback_to_str(self):
        result = _format_args_short({"custom": "value"})
        assert "custom" in result
        assert "value" in result

    def test_truncation(self):
        long_args = {"custom": "x" * 200}
        result = _format_args_short(long_args)
        assert len(result) <= 100

    def test_empty_args(self):
        result = _format_args_short({})
        assert isinstance(result, str)

    def test_args_not_list(self):
        # args key exists but isn't a list — should fall through
        result = _format_args_short({"args": "not a list", "path": "/foo"})
        assert result == "/foo"


# ── Pure function tests: _format_args_detail ───────────────────


class TestFormatArgsDetail:
    def test_shell_command(self):
        result = _format_args_detail({"args": ["git", "push", "--force"]})
        assert result == "$ git push --force"

    def test_path_key(self):
        result = _format_args_detail({"path": "/tmp/foo.py"})
        assert result == "/tmp/foo.py"

    def test_file_path_key(self):
        result = _format_args_detail({"file_path": "src/main.py"})
        assert result == "src/main.py"

    def test_file_name_key(self):
        result = _format_args_detail({"file_name": "output.txt"})
        assert result == "output.txt"

    def test_fallback_all_args(self):
        result = _format_args_detail({"key1": "val1", "key2": "val2"})
        assert "key1: val1" in result
        assert "key2: val2" in result
        assert "\n" in result

    def test_empty_args(self):
        result = _format_args_detail({})
        assert result == ""

    def test_args_not_list_falls_through(self):
        result = _format_args_detail({"args": "string", "path": "/x"})
        assert result == "/x"


# ── Pure function tests: _build_rule ───────────────────────────


class TestBuildRule:
    def test_with_shell_args(self):
        result = _build_rule("Bash", {"args": ["git", "status"]})
        assert result == "Bash(git status)"

    def test_with_path(self):
        result = _build_rule("Edit", {"file_path": "src/main.py"})
        assert result == "Edit(src/main.py)"

    def test_empty_args(self):
        # _format_args_short({}) returns "{}" which is truthy
        result = _build_rule("Bash", {})
        assert result.startswith("Bash")

    def test_with_url(self):
        result = _build_rule("WebFetch", {"url": "https://example.com"})
        assert result == "WebFetch(https://example.com)"


# ── Pure function tests: _build_pattern_rule ───────────────────


class TestBuildPatternRule:
    def test_shell_pattern(self):
        result = _build_pattern_rule("Bash", {"args": ["git", "push"]})
        assert result == "Bash(git:*)"

    def test_shell_single_arg(self):
        result = _build_pattern_rule("Bash", {"args": ["npm"]})
        assert result == "Bash(npm:*)"

    def test_shell_empty_args_list(self):
        result = _build_pattern_rule("Bash", {"args": []})
        # falls through to path/url checks, then fallback
        assert result == "Bash"

    def test_file_path_pattern(self):
        result = _build_pattern_rule("Edit", {"file_path": "src/ember_code/tui/app.py"})
        assert result == "Edit(path:src/ember_code/tui/*)"

    def test_path_pattern(self):
        result = _build_pattern_rule("Read", {"path": "/home/user/project/main.py"})
        assert result == "Read(path:/home/user/project/*)"

    def test_path_root_file(self):
        # A file at the root dir: parent is "." — should fallback
        result = _build_pattern_rule("Read", {"path": "file.py"})
        assert result == "Read"

    def test_url_domain_pattern(self):
        result = _build_pattern_rule("WebFetch", {"url": "https://api.example.com/v1/data"})
        assert result == "WebFetch(domain:api.example.com)"

    def test_url_no_domain(self):
        result = _build_pattern_rule("WebFetch", {"url": "not-a-url"})
        assert result == "WebFetch"

    def test_no_matching_keys(self):
        result = _build_pattern_rule("Custom", {"custom_key": "value"})
        assert result == "Custom"

    def test_args_not_list_falls_through(self):
        result = _build_pattern_rule("Bash", {"args": "string", "path": "src/foo.py"})
        assert "path:src/*" in result


# ── HITLHandler logic tests ────────────────────────────────────


class TestHITLHandlerHandle:
    @pytest.mark.asyncio
    async def test_routes_confirmation(self):
        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
        )
        handler._handle_confirmation = AsyncMock()

        req = MagicMock()
        req.needs_confirmation = True
        req.needs_user_input = False

        run_response = MagicMock()
        run_response.active_requirements = [req]

        await handler.handle(MagicMock(), run_response)
        handler._handle_confirmation.assert_called_once_with(req)

    @pytest.mark.asyncio
    async def test_routes_user_input(self):
        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
        )

        req = MagicMock()
        req.needs_confirmation = False
        req.needs_user_input = True

        run_response = MagicMock()
        run_response.active_requirements = [req]

        await handler.handle(MagicMock(), run_response)
        req.provide_user_input.assert_called_once_with({})

    @pytest.mark.asyncio
    async def test_empty_requirements(self):
        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
        )
        run_response = MagicMock()
        run_response.active_requirements = []

        await handler.handle(MagicMock(), run_response)  # should not raise


class TestHITLConfirmation:
    @pytest.mark.asyncio
    async def test_no_tool_exec_confirms(self):
        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
        )
        req = MagicMock()
        req.tool_execution = None

        await handler._handle_confirmation(req)
        req.confirm.assert_called_once()

    @pytest.mark.asyncio
    async def test_allowed_by_permissions(self):
        permissions = MagicMock()
        permissions.check.return_value = "allow"

        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
            permissions=permissions,
        )

        req = MagicMock()
        req.tool_execution.tool_name = "read_file"
        req.tool_execution.tool_args = {"path": "/tmp/x"}

        await handler._handle_confirmation(req)
        req.confirm.assert_called_once()

    @pytest.mark.asyncio
    async def test_denied_by_permissions(self):
        permissions = MagicMock()
        permissions.check.return_value = "deny"

        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
            permissions=permissions,
        )

        req = MagicMock()
        req.tool_execution.tool_name = "run_shell"
        req.tool_execution.tool_args = {"args": ["rm", "-rf", "/"]}

        await handler._handle_confirmation(req)
        req.reject.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_approval_hit(self):
        permissions = MagicMock()
        permissions.check.return_value = "ask"

        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
            permissions=permissions,
        )

        # Pre-populate session approval
        handler._session_approvals.add("Bash(git status)")

        req = MagicMock()
        req.tool_execution.tool_name = "run_shell"
        req.tool_execution.tool_args = {"args": ["git", "status"]}

        # Patch FUNC_TO_TOOL to map run_shell -> Bash
        with patch.dict(
            "ember_code.tui.hitl_handler.FUNC_TO_TOOL",
            {"run_shell": "Bash"},
        ):
            await handler._handle_confirmation(req)

        req.confirm.assert_called_once()


class TestSessionApprovals:
    def test_initial_empty(self):
        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
        )
        assert len(handler._session_approvals) == 0

    def test_add_and_lookup(self):
        handler = HITLHandler(
            app=MagicMock(),
            conversation=MagicMock(),
        )
        handler._session_approvals.add("Bash(git push)")
        assert "Bash(git push)" in handler._session_approvals
        assert "Bash(git pull)" not in handler._session_approvals
