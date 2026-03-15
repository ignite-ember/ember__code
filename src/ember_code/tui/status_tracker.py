"""StatusTracker — tracks token usage, context window, and message count."""

import contextlib
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

from ember_code.tui.widgets import StatusBar

if TYPE_CHECKING:
    from ember_code.tui.app import EmberApp


class StatusTracker:
    """Tracks token usage, context window, and delegates to StatusBar."""

    def __init__(self, app: "EmberApp"):
        self._app = app
        self.total_tokens_used: int = 0
        self.max_context_tokens: int = 128_000

    def _bar(self) -> StatusBar | None:
        try:
            return self._app.query_one("#status-bar", StatusBar)
        except NoMatches:
            return None

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.total_tokens_used += input_tokens + output_tokens
        bar = self._bar()
        if bar:
            bar.add_tokens(input_tokens, output_tokens)

    def start_run(self) -> None:
        bar = self._bar()
        if bar:
            bar.start_run()

    def end_run(self) -> None:
        bar = self._bar()
        if bar:
            bar.end_run()

    def set_run_tokens(self, input_tokens: int, output_tokens: int) -> None:
        bar = self._bar()
        if bar:
            bar.set_run_tokens(input_tokens, output_tokens)

    def update_status_bar(self) -> None:
        session = self._app._session
        if not session:
            return
        bar = self._bar()
        if bar:
            bar.update_model(session.settings.models.default)

    def update_context_usage(self) -> None:
        if self.total_tokens_used <= 0:
            return
        pct = min(int(self.total_tokens_used / self.max_context_tokens * 100), 100)
        bar = self._bar()
        if bar:
            bar.set_context_usage(pct)

    def record_turn(self) -> None:
        pass  # No longer tracking message count in status bar

    def reset(self) -> None:
        self.total_tokens_used = 0
