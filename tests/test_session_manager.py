"""Tests for tui/session_manager.py — session lifecycle delegation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ember_code.tui.session_manager import SessionManager


def _make_manager() -> tuple[SessionManager, MagicMock, MagicMock, MagicMock]:
    """Create a SessionManager with all mocked deps."""
    app = MagicMock()
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
    async def test_updates_session_id(self):
        mgr, app, conversation, status = _make_manager()
        session = MagicMock()
        session.persistence.get_name = AsyncMock(return_value="My Session")
        app.session = session
        app.query_one.return_value = MagicMock()

        await mgr.switch_to("abc-123")
        assert session.session_id == "abc-123"
        assert session.session_named is True

    @pytest.mark.asyncio
    async def test_clears_and_resets(self):
        mgr, app, conversation, status = _make_manager()
        session = MagicMock()
        session.persistence.get_name = AsyncMock(return_value=None)
        app.session = session
        app.query_one.return_value = MagicMock()

        await mgr.switch_to("abc-123")
        conversation.clear.assert_called()
        status.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_shows_session_name(self):
        mgr, app, conversation, status = _make_manager()
        session = MagicMock()
        session.persistence.get_name = AsyncMock(return_value="Feature Work")
        app.session = session
        app.query_one.return_value = MagicMock()

        await mgr.switch_to("s-42")
        # Should append info with session name
        conversation.append_info.assert_called_once()
        msg = conversation.append_info.call_args[0][0]
        assert "Feature Work" in msg
        assert "s-42" in msg

    @pytest.mark.asyncio
    async def test_no_name_shows_id(self):
        mgr, app, conversation, status = _make_manager()
        session = MagicMock()
        session.persistence.get_name = AsyncMock(return_value=None)
        app.session = session
        app.query_one.return_value = MagicMock()

        await mgr.switch_to("s-99")
        msg = conversation.append_info.call_args[0][0]
        assert "s-99" in msg

    @pytest.mark.asyncio
    async def test_updates_status_bar(self):
        mgr, app, conversation, status = _make_manager()
        session = MagicMock()
        session.persistence.get_name = AsyncMock(return_value=None)
        app.session = session
        app.query_one.return_value = MagicMock()

        await mgr.switch_to("s-1")
        status.update_status_bar.assert_called_once()

    @pytest.mark.asyncio
    async def test_focuses_input(self):
        mgr, app, conversation, status = _make_manager()
        session = MagicMock()
        session.persistence.get_name = AsyncMock(return_value=None)
        app.session = session
        input_widget = MagicMock()
        app.query_one.return_value = input_widget

        await mgr.switch_to("s-1")
        input_widget.focus.assert_called_once()
