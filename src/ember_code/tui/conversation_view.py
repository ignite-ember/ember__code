"""ConversationView — centralises widget-append operations on the conversation container."""

from textual.containers import ScrollableContainer
from textual.widgets import Markdown, Static

from ember_code.tui.widgets import (
    AgentTreeWidget,
    MessageWidget,
    RunStatsWidget,
    TokenBadge,
)
from ember_code.tui.widgets._constants import AUTO_SCROLL_THRESHOLD


class ConversationView:
    """Centralises widget-append operations on the conversation container,
    eliminating repetitive ``query_one`` + ``mount`` + ``scroll_end``
    boilerplate throughout the app.
    """

    def __init__(self, container: ScrollableContainer, display_config=None):
        self._container = container
        self._display = display_config

    @property
    def container(self) -> ScrollableContainer:
        return self._container

    def _is_at_bottom(self) -> bool:
        """Check if the user is scrolled to (or near) the bottom."""
        return self._container.max_scroll_y - self._container.scroll_y < AUTO_SCROLL_THRESHOLD

    def _auto_scroll(self) -> None:
        """Scroll to bottom only if user is already near the bottom."""
        if self._is_at_bottom():
            self._container.scroll_end(animate=True)

    def append(self, widget) -> None:
        self._container.mount(widget)
        self._auto_scroll()

    @property
    def _truncate_lines(self) -> int:
        return self._display.message_truncate_lines if self._display else 10

    def append_user(self, text: str, expanded: bool = False) -> None:
        self.append(
            MessageWidget(text, role="user", truncate_lines=self._truncate_lines, expanded=expanded)
        )

    def append_assistant(self, text: str, expanded: bool = False) -> None:
        self.append(
            MessageWidget(
                text, role="assistant", truncate_lines=self._truncate_lines, expanded=expanded
            )
        )

    def append_markdown(self, text: str) -> None:
        self.append(Markdown(text, classes="assistant-message"))

    def append_info(self, text: str) -> None:
        self.append(Static(f"[dim]{text}[/dim]", classes="info-message"))

    def append_error(self, text: str) -> None:
        self.append(Static(f"[red]{text}[/red]", classes="error-message"))

    def append_agent_tree(self, plan) -> None:
        self.append(
            AgentTreeWidget(
                team_name=plan.team_name,
                team_mode=plan.team_mode,
                agent_names=plan.agent_names,
                reasoning=plan.reasoning,
            )
        )

    def append_token_badge(self, input_tokens: int, output_tokens: int) -> None:
        self.append(TokenBadge(input_tokens, output_tokens))

    def append_run_stats(self, model: str = "") -> RunStatsWidget:
        """Mount a live RunStatsWidget and return it for further updates."""
        widget = RunStatsWidget(model=model)
        self.append(widget)
        return widget

    def clear(self) -> None:
        self._container.remove_children()
