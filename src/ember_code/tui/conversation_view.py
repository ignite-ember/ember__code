"""ConversationView — centralises widget-append operations on the conversation container."""

from textual.containers import ScrollableContainer
from textual.widgets import Markdown, Static

from ember_code.tui.widgets import (
    AgentTreeWidget,
    MessageWidget,
    RunStatsWidget,
    TokenBadge,
    WelcomeBanner,
)


class ConversationView:
    """Centralises widget-append operations on the conversation container,
    eliminating repetitive ``query_one`` + ``mount`` + ``scroll_end``
    boilerplate throughout the app.
    """

    def __init__(self, container: ScrollableContainer):
        self._container = container

    @property
    def container(self) -> ScrollableContainer:
        return self._container

    def append(self, widget) -> None:
        self._container.mount(widget)
        self._container.scroll_end()

    def append_user(self, text: str) -> None:
        self.append(MessageWidget(text, role="user"))

    def append_assistant(self, text: str) -> None:
        self.append(MessageWidget(text, role="assistant"))

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

    def append_run_stats(
        self,
        elapsed_seconds: float,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> None:
        self.append(RunStatsWidget(elapsed_seconds, input_tokens, output_tokens, model))

    def clear(self) -> None:
        self._container.remove_children()
        self._container.mount(WelcomeBanner())
