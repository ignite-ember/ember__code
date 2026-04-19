"""Agent run container — groups tool calls and content under an agent header."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


class AgentRunContainer(Widget):
    """Visual container for a single agent's run — groups its tools and content.

    Main agent: no indent, no border.
    Sub-agents: left border + indent to show nesting.
    """

    DEFAULT_CSS = """
    AgentRunContainer {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0;
    }

    AgentRunContainer.-sub-agent {
        margin-left: 2;
        border-left: solid $accent 40%;
        padding-left: 1;
    }

    AgentRunContainer .agent-header {
        height: 1;
        color: $accent;
        text-style: bold;
    }

    AgentRunContainer .agent-body {
        height: auto;
        width: 100%;
    }
    """

    def __init__(
        self,
        agent_name: str,
        run_id: str,
        model: str = "",
        is_sub_agent: bool = False,
    ):
        super().__init__()
        self.agent_name = agent_name
        self.run_id = run_id
        self._model = model
        self._is_sub_agent = is_sub_agent
        if is_sub_agent:
            self.add_class("-sub-agent")

    def compose(self) -> ComposeResult:
        prefix = "├─" if self._is_sub_agent else "●"
        safe_name = self.agent_name.replace("[", "\\[")
        model_hint = f" [dim]({self._model})[/dim]" if self._model else ""
        yield Static(
            f"[bold $accent]{prefix} {safe_name}[/bold $accent]{model_hint}",
            classes="agent-header",
        )
        yield Vertical(classes="agent-body")

    @property
    def body(self) -> Vertical:
        """The container where tools and content are mounted."""
        return self.query_one(".agent-body", Vertical)
