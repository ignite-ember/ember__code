"""Tests for tui/status_tracker.py — token tracking and status bar delegation."""

from unittest.mock import MagicMock

from ember_code.tui.status_tracker import StatusTracker


def _make_tracker(bar: MagicMock | None = None) -> StatusTracker:
    """Create a StatusTracker with a mocked app and optional bar."""
    app = MagicMock()
    tracker = StatusTracker(app)
    # Patch _bar to return our mock (or None)
    tracker._bar = MagicMock(return_value=bar)
    return tracker


class TestInitialState:
    def test_defaults(self):
        app = MagicMock()
        tracker = StatusTracker(app)
        assert tracker.total_tokens_used == 0
        assert tracker._context_input_tokens == 0
        assert tracker.max_context_tokens == 128_000


class TestAddTokens:
    def test_accumulates_total(self):
        tracker = _make_tracker(bar=MagicMock())
        tracker.add_tokens(100, 50)
        assert tracker.total_tokens_used == 150
        tracker.add_tokens(200, 100)
        assert tracker.total_tokens_used == 450

    def test_delegates_to_bar(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.add_tokens(100, 50)
        bar.add_tokens.assert_called_once_with(100, 50)

    def test_no_bar_still_accumulates(self):
        tracker = _make_tracker(bar=None)
        tracker.add_tokens(100, 50)
        assert tracker.total_tokens_used == 150


class TestStartEndRun:
    def test_start_run_delegates(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.start_run()
        bar.start_run.assert_called_once()

    def test_end_run_delegates(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.end_run()
        bar.end_run.assert_called_once()

    def test_start_run_no_bar(self):
        tracker = _make_tracker(bar=None)
        tracker.start_run()  # should not raise

    def test_end_run_no_bar(self):
        tracker = _make_tracker(bar=None)
        tracker.end_run()  # should not raise


class TestSetRunTokens:
    def test_delegates_to_bar(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.set_run_tokens(500, 200)
        bar.set_run_tokens.assert_called_once_with(500, 200)

    def test_no_bar(self):
        tracker = _make_tracker(bar=None)
        tracker.set_run_tokens(500, 200)  # should not raise


class TestUpdateStatusBar:
    def test_delegates_model_and_cloud(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        session = MagicMock()
        session.settings.models.default = "test-model"
        session.cloud_connected = True
        session.cloud_org_id = "org-123"
        tracker._app.session = session
        tracker.update_status_bar()
        bar.update_model.assert_called_once_with("test-model")
        bar.set_cloud_status.assert_called_once_with(True, "org-123")

    def test_no_session(self):
        tracker = _make_tracker(bar=MagicMock())
        tracker._app.session = None
        tracker.update_status_bar()  # should not raise

    def test_cloud_org_id_none(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        session = MagicMock()
        session.cloud_connected = False
        session.cloud_org_id = None
        tracker._app.session = session
        tracker.update_status_bar()
        bar.set_cloud_status.assert_called_once_with(False, "")


class TestContextTokens:
    def test_add_context_tokens(self):
        tracker = _make_tracker()
        tracker.add_context_tokens(5000)
        assert tracker._context_input_tokens == 5000

    def test_add_context_tokens_replaces(self):
        tracker = _make_tracker()
        tracker.add_context_tokens(5000)
        tracker.add_context_tokens(8000)
        assert tracker._context_input_tokens == 8000

    def test_update_context_usage_delegates(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.max_context_tokens = 100_000
        tracker.add_context_tokens(50_000)
        tracker.update_context_usage()
        bar.set_context_usage.assert_called_once_with(50_000, 100_000)

    def test_update_context_usage_skips_zero(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.update_context_usage()
        bar.set_context_usage.assert_not_called()

    def test_update_context_usage_no_bar(self):
        tracker = _make_tracker(bar=None)
        tracker.add_context_tokens(5000)
        tracker.update_context_usage()  # should not raise


class TestSetIdeStatus:
    def test_delegates(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.set_ide_status("VS Code", True)
        bar.set_ide_status.assert_called_once_with("VS Code", True)

    def test_no_bar(self):
        tracker = _make_tracker(bar=None)
        tracker.set_ide_status("VS Code", True)  # should not raise


class TestSetCloudStatus:
    def test_delegates(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.set_cloud_status(True, "my-org")
        bar.set_cloud_status.assert_called_once_with(True, "my-org")

    def test_default_org_name(self):
        bar = MagicMock()
        tracker = _make_tracker(bar=bar)
        tracker.set_cloud_status(False)
        bar.set_cloud_status.assert_called_once_with(False, "")


class TestRecordTurn:
    def test_noop(self):
        tracker = _make_tracker()
        tracker.record_turn()  # should not raise, it's a no-op


class TestReset:
    def test_clears_state(self):
        tracker = _make_tracker()
        tracker.total_tokens_used = 5000
        tracker._context_input_tokens = 3000
        tracker.reset()
        assert tracker.total_tokens_used == 0
        assert tracker._context_input_tokens == 0
