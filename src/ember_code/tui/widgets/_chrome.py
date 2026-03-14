"""App chrome widgets: banners, bars, spinner, queue panel."""

from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from ember_code import __version__
from ember_code.tui.widgets._constants import SPINNER_FRAMES
from ember_code.tui.widgets._tokens import TokenBadge


class WelcomeBanner(Static):
    """Welcome banner shown at startup."""

    def __init__(self):
        banner = (
            f"[bold blue]Ember Code[/bold blue] v{__version__}\n"
            "[dim]AI coding assistant powered by Agno[/dim]\n"
            "[dim]Type a message or /help for commands. Ctrl+D to quit.[/dim]"
        )
        super().__init__(banner)


class SpinnerWidget(Static):
    """Animated spinner with token counter and status text."""

    DEFAULT_CSS = """
    SpinnerWidget {
        height: 1;
        margin: 0 0 0 2;
        color: $accent;
    }
    """

    def __init__(self, label: str = "Thinking"):
        self._label = label
        self._frame = 0
        self._tokens = 0
        self._timer: Timer | None = None
        super().__init__(self._render())

    def on_mount(self) -> None:
        self._timer = self.set_interval(1 / 12, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        self.update(self._render())

    def _render(self) -> str:
        frame = SPINNER_FRAMES[self._frame]
        tokens_str = f"  [dim]{TokenBadge._fmt(self._tokens)} tokens[/dim]" if self._tokens else ""
        return f"[bold]{frame}[/bold] {self._label}...{tokens_str}"

    def set_label(self, label: str) -> None:
        self._label = label
        self.update(self._render())

    def set_tokens(self, tokens: int) -> None:
        self._tokens = tokens
        self.update(self._render())

    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None


class StatusBar(Static):
    """Status bar showing session info and cumulative token usage."""

    model_name = reactive("MiniMax-M2.5")
    session_id = reactive("")
    agent_count = reactive(0)
    message_count = reactive(0)
    total_input_tokens = reactive(0)
    total_output_tokens = reactive(0)
    context_used_pct = reactive(0)

    def update_status(
        self,
        model: str = "",
        session_id: str = "",
        agent_count: int = 0,
        message_count: int = 0,
    ):
        if model:
            self.model_name = model
        if session_id:
            self.session_id = session_id
        if agent_count:
            self.agent_count = agent_count
        self.message_count = message_count
        self._render_status()

    def add_tokens(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        """Accumulate token usage from a response."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self._render_status()

    def set_context_usage(self, used_pct: int) -> None:
        """Update context window usage percentage."""
        self.context_used_pct = used_pct
        self._render_status()

    @staticmethod
    def _fmt(n: int) -> str:
        if n < 1000:
            return str(n)
        if n < 10_000:
            return f"{n / 1000:.1f}k"
        return f"{n // 1000}k"

    def _render_status(self) -> None:
        tokens_str = (
            f"  |  Tokens: {self._fmt(self.total_input_tokens)}\u2191 "
            f"{self._fmt(self.total_output_tokens)}\u2193"
        )
        context_str = ""
        if self.context_used_pct > 0:
            color = ""
            if self.context_used_pct >= 80:
                color = "[red]"
            elif self.context_used_pct >= 60:
                color = "[yellow]"
            context_str = f"  |  Context: {color}{self.context_used_pct}%{'[/]' if color else ''}"
        self.update(
            f" [bold]{self.model_name}[/bold]"
            f"  |  Session: {self.session_id}"
            f"  |  Agents: {self.agent_count}"
            f"  |  Messages: {self.message_count}"
            f"{tokens_str}{context_str}"
        )


class QueuePanel(Widget):
    """Interactive panel showing queued messages."""

    DEFAULT_CSS = """
    QueuePanel {
        dock: bottom;
        height: auto;
        max-height: 10;
        background: $surface;
        border-top: solid $accent;
        padding: 0 1;
    }

    QueuePanel.-hidden {
        display: none;
    }

    QueuePanel .queue-header {
        color: $accent;
        text-style: bold;
        height: 1;
    }

    QueuePanel .queue-item {
        height: 1;
        padding: 0 1;
    }

    QueuePanel .queue-item.-selected {
        background: $accent 30%;
        text-style: bold;
    }

    QueuePanel .queue-hint {
        color: $text-muted;
        height: 1;
    }
    """

    class ItemDeleted(Message):
        """Posted when a queue item is deleted."""

        def __init__(self, index: int):
            self.index = index
            super().__init__()

    class ItemEditRequested(Message):
        """Posted when the user wants to edit a queue item."""

        def __init__(self, index: int, text: str):
            self.index = index
            self.text = text
            super().__init__()

    class PanelClosed(Message):
        """Posted when the user closes the panel with Escape."""

        pass

    selected_index = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._items: list[str] = []
        self.add_class("-hidden")

    def refresh_items(self, items: list[str]) -> None:
        """Update the displayed queue items."""
        self._items = list(items)
        if not self._items:
            self.add_class("-hidden")
            return
        self.remove_class("-hidden")
        self.selected_index = min(self.selected_index, max(0, len(self._items) - 1))
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild child widgets from current items."""
        self.remove_children()
        if not self._items:
            return
        self.mount(
            Static(
                f"[bold $accent]Queue ({len(self._items)})[/bold $accent]"
                "  [dim]↑↓ navigate  Del remove  Enter edit  Esc close[/dim]",
                classes="queue-header",
            )
        )
        for i, text in enumerate(self._items):
            first_line = text.split("\n", 1)[0].strip()
            preview = first_line if len(first_line) <= 50 else first_line[:47] + "..."
            cls = "queue-item -selected" if i == self.selected_index else "queue-item"
            self.mount(Static(f"  {i + 1}. {preview}", id=f"q-{i}", classes=cls))

    def watch_selected_index(self, old: int, new: int) -> None:
        try:
            old_w = self.query_one(f"#q-{old}", Static)
            old_w.remove_class("-selected")
        except Exception:
            pass
        try:
            new_w = self.query_one(f"#q-{new}", Static)
            new_w.add_class("-selected")
        except Exception:
            pass

    def on_key(self, event) -> None:
        if not self._items:
            return

        if event.key == "up":
            event.prevent_default()
            self.selected_index = max(0, self.selected_index - 1)
        elif event.key == "down":
            event.prevent_default()
            self.selected_index = min(len(self._items) - 1, self.selected_index + 1)
        elif event.key in ("delete", "backspace"):
            event.prevent_default()
            if 0 <= self.selected_index < len(self._items):
                self.post_message(self.ItemDeleted(self.selected_index))
        elif event.key == "enter":
            event.prevent_default()
            if 0 <= self.selected_index < len(self._items):
                self.post_message(
                    self.ItemEditRequested(self.selected_index, self._items[self.selected_index])
                )
        elif event.key == "escape":
            event.prevent_default()
            self.post_message(self.PanelClosed())


class TipBar(Static):
    """Bottom bar showing a usage tip."""

    DEFAULT_CSS = """
    TipBar {
        dock: bottom;
        height: 1;
        background: $primary-background-darken-1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, tip: str | None = None, **kwargs):
        self._tip = tip or ""
        display = f"[dim italic]Tip: {self._tip}[/dim italic]" if self._tip else ""
        super().__init__(display, **kwargs)

    def set_tip(self, tip: str) -> None:
        """Update the displayed tip."""
        self._tip = tip
        self.update(f"[dim italic]Tip: {tip}[/dim italic]")


class UpdateBar(Static):
    """Bottom bar showing an available update notification."""

    DEFAULT_CSS = """
    UpdateBar {
        dock: bottom;
        height: 1;
        background: $warning 20%;
        color: $warning;
        padding: 0 1;
    }

    UpdateBar.-hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.add_class("-hidden")

    def show_update(self, current: str, latest: str, url: str = "") -> None:
        """Display an update notification."""
        msg = f"Update available: v{current} -> v{latest}"
        if url:
            msg += f"  |  {url}"
        self.update(msg)
        self.remove_class("-hidden")

    def hide(self) -> None:
        self.add_class("-hidden")
