"""Tests for tui/session_manager.py — session lifecycle delegation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ember_code.frontend.tui.session_manager import SessionManager
from ember_code.protocol.messages import Info


def _make_manager() -> tuple[SessionManager, MagicMock, MagicMock, MagicMock]:
    """Create a SessionManager with all mocked deps."""
    app = MagicMock()
    # Mock the backend
    backend = MagicMock()
    backend.session_id = "current-session"
    backend.switch_session = AsyncMock(
        return_value=Info(text="Switched to session: My Session (abc-123)")
    )
    backend.session.main_team.aget_session = AsyncMock(return_value=None)
    backend.session.user_id = "test-user"
    app.backend = backend

    conversation = MagicMock()
    status = MagicMock()
    mgr = SessionManager(app, conversation, status)
    return mgr, app, conversation, status


class TestClear:
    def test_clears_conversation(self):
        mgr, _, conversation, _ = _make_manager()
        mgr.clear()
        conversation.clear.assert_called_once()

    def test_resets_message_count(self):
        mgr, _, _, status = _make_manager()
        mgr.clear()
        assert status.message_count == 0


class TestSwitchTo:
    @pytest.mark.asyncio
    async def test_clears_and_resets(self):
        mgr, app, conversation, status = _make_manager()
        app.query_one.return_value = MagicMock()
        await mgr.switch_to("abc-123")
        conversation.clear.assert_called_once()
        status.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_shows_session_info(self):
        mgr, app, conversation, status = _make_manager()
        app.query_one.return_value = MagicMock()
        await mgr.switch_to("abc-123")
        # Should show the result text from backend
        conversation.append_info.assert_called()
        calls = [str(c) for c in conversation.append_info.call_args_list]
        assert any("Switched" in c or "session" in c.lower() for c in calls)

    @pytest.mark.asyncio
    async def test_updates_status_bar(self):
        mgr, app, conversation, status = _make_manager()
        app.query_one.return_value = MagicMock()
        await mgr.switch_to("abc-123")
        status.update_status_bar.assert_called_once()

    @pytest.mark.asyncio
    async def test_focuses_input(self):
        mgr, app, conversation, status = _make_manager()
        input_widget = MagicMock()
        app.query_one.return_value = input_widget
        await mgr.switch_to("abc-123")
        input_widget.focus.assert_called()

    @pytest.mark.asyncio
    async def test_calls_backend_switch(self):
        mgr, app, conversation, status = _make_manager()
        app.query_one.return_value = MagicMock()
        await mgr.switch_to("abc-123")
        app.backend.switch_session.assert_awaited_once_with("abc-123")
