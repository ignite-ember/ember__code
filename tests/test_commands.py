"""Tests for session/commands.py — slash command dispatch and handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.session.commands import (
    _ASYNC_COMMANDS,
    _SYNC_COMMANDS,
    _SYNC_COMMANDS_WITH_ARGS,
    dispatch,
)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_known_sync_command(self):
        session = MagicMock()
        session.pool.list_agents.return_value = []
        result = await dispatch(session, "/agents")
        assert result is True

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command(self):
        session = MagicMock()
        result = await dispatch(session, "/nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_async_command(self):
        session = MagicMock()
        session.knowledge_mgr.share_enabled.return_value = False
        result = await dispatch(session, "/sync-knowledge")
        assert result is True

    def test_all_expected_commands_registered(self):
        expected_sync = {"/help", "/agents", "/skills", "/clear", "/config"}
        expected_sync_with_args = {"/hooks"}
        expected_async = {"/sync-knowledge", "/evals"}
        assert expected_sync.issubset(set(_SYNC_COMMANDS.keys()))
        assert expected_sync_with_args.issubset(set(_SYNC_COMMANDS_WITH_ARGS.keys()))
        assert expected_async.issubset(set(_ASYNC_COMMANDS.keys()))


class TestHelpCommand:
    def test_help_lists_skills(self):
        session = MagicMock()
        skill = MagicMock()
        skill.name = "commit"
        skill.argument_hint = "-m 'message'"
        skill.description = "Create a git commit"
        session.skill_pool.list_skills.return_value = [skill]

        with patch("ember_code.session.commands.print_markdown") as mock_print:
            _SYNC_COMMANDS["/help"](session)
            printed = mock_print.call_args[0][0]
            assert "/commit" in printed


class TestAgentsCommand:
    def test_lists_agents(self):
        defn = MagicMock()
        defn.name = "editor"
        defn.description = "Edits files"
        defn.tools = ["Read", "Edit"]

        session = MagicMock()
        session.pool.list_agents.return_value = [defn]

        with patch("ember_code.session.commands.print_markdown") as mock_print:
            _SYNC_COMMANDS["/agents"](session)
            printed = mock_print.call_args[0][0]
            assert "editor" in printed
            assert "Read, Edit" in printed


class TestClearCommand:
    def test_resets_session_id(self):
        session = MagicMock()
        session.session_id = "old-id"

        with patch("ember_code.session.commands.print_info"):
            _SYNC_COMMANDS["/clear"](session)

        assert session.session_id != "old-id"
        assert len(session.session_id) == 8


class TestConfigCommand:
    def test_prints_config(self):
        session = MagicMock()
        session.settings.models.default = "test-model"
        session.settings.permissions.file_read = "allow"
        session.settings.permissions.file_write = "ask"
        session.settings.permissions.shell_execute = "ask"
        session.settings.storage.backend = "sqlite"
        session.settings.storage.session_db = "~/.ember/sessions.db"
        session.settings.storage.audit_log = "~/.ember/audit.log"
        session.settings.orchestration.max_total_agents = 20
        session.settings.orchestration.generate_ephemeral = False
        session.settings.skills.auto_trigger = True
        session.settings.display.show_routing = False
        session.project_dir = "/tmp/project"
        session.session_id = "s123"

        with patch("ember_code.session.commands.print_markdown") as mock_print:
            _SYNC_COMMANDS["/config"](session)
            printed = mock_print.call_args[0][0]
            assert "test-model" in printed
            assert "s123" in printed


class TestSyncKnowledgeCommand:
    @pytest.mark.asyncio
    async def test_not_enabled(self):
        session = MagicMock()
        session.knowledge_mgr.share_enabled.return_value = False

        with patch("ember_code.session.commands.print_info") as mock_print:
            await _ASYNC_COMMANDS["/sync-knowledge"](session, "")
            assert "not enabled" in mock_print.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_sync_enabled(self):
        session = MagicMock()
        session.knowledge_mgr.share_enabled.return_value = True
        result1 = MagicMock(direction="file_to_db", summary="Loaded 3 entries")
        result2 = MagicMock(direction="db_to_file", summary="Exported 1 entry")
        session.knowledge_mgr.sync_bidirectional = AsyncMock(return_value=[result1, result2])

        with patch("ember_code.session.commands.print_info"):
            await _ASYNC_COMMANDS["/sync-knowledge"](session, "")
            session.knowledge_mgr.sync_bidirectional.assert_called_once()
