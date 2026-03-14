"""StatusTracker — tracks token usage, context window, and message count."""

import contextlib
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

from ember_code.tui.widgets import StatusBar

if TYPE_CHECKING:
    from ember_code.tui.app import EmberApp
    from ember_code.tui.conversation_view import ConversationView


class StatusTracker:
    """Tracks token usage, context window, and message count.

    Updates the ``StatusBar`` widget via ``app.query_one``.
    """

    def __init__(self, app: "EmberApp"):
        self._app = app
        self.message_count: int = 0
        self.total_tokens_used: int = 0
        self.max_context_tokens: int = 128_000

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.total_tokens_used += input_tokens + output_tokens

    def record_turn(self) -> None:
        self.message_count += 2  # user + assistant

    def update_status_bar(self) -> None:
        session = self._app._session
        if not session:
            return
        with contextlib.suppress(NoMatches):
            bar = self._app.query_one("#status-bar", StatusBar)
            bar.update_status(
                model=session.settings.models.default,
                session_id=session.session_id,
                agent_count=len(session.pool.agent_names),
                message_count=self.message_count,
            )

    def update_context_usage(self) -> None:
        if self.total_tokens_used <= 0:
            return
        pct = min(int(self.total_tokens_used / self.max_context_tokens * 100), 100)
        with contextlib.suppress(NoMatches):
            self._app.query_one("#status-bar", StatusBar).set_context_usage(pct)

    def push_token_badge(
        self,
        conversation: "ConversationView",
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        if input_tokens or output_tokens:
            conversation.append_token_badge(input_tokens, output_tokens)
            with contextlib.suppress(NoMatches):
                self._app.query_one("#status-bar", StatusBar).add_tokens(
                    input_tokens,
                    output_tokens,
                )
            self.add_tokens(input_tokens, output_tokens)

    def reset(self) -> None:
        self.message_count = 0
        self.total_tokens_used = 0
