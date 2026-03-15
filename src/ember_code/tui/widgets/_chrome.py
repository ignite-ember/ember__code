"""App chrome widgets: banners, bars, spinner, queue panel."""

from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from ember_code import __version__
from ember_code.tui.widgets._constants import SPINNER_FRAMES

_QUIT_KEY = "Ctrl+D"


class WelcomeBanner(Static):
    """Welcome banner shown at startup — minimal Claude Code style."""

    DEFAULT_CSS = """
    WelcomeBanner {
        padding: 1 0 0 0;
        margin: 0 0 1 0;
    }
    """

    def __init__(self):
        banner = (
            f"  [bold]Ember Code[/bold] [dim]v{__version__}[/dim]\n"
            f"  [dim]/help for commands · {_QUIT_KEY} to quit[/dim]"
        )
        super().__init__(banner)


class SpinnerWidget(Static):
    """Claude Code-style activity indicator.

    Keeps it simple — just a label with animated dots.
    All token/time stats live in the footer StatusBar.
    """

    DEFAULT_CSS = """
    SpinnerWidget {
        height: 1;
        margin: 0 0 0 2;
    }
    """

    def __init__(self, label: str = "Thinking"):
        self._label = label
        self._frame = 0
        self._timer: Timer | None = None
        super().__init__(self._format())

    def on_mount(self) -> None:
        self._timer = self.set_interval(1 / 12, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        self.update(self._format())

    def _format(self) -> str:
        frame = SPINNER_FRAMES[self._frame]
        if self._label == "Thinking":
            return f"[dim]{frame} Thinking...[/dim]"
        return f"[bold $accent]{frame} {self._label}...[/bold $accent]"

    def set_label(self, label: str) -> None:
        self._label = label
        self.update(self._format())

    def set_tokens(self, tokens: int) -> None:
        """No-op — tokens are shown in the footer StatusBar."""
        pass

    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None


class StatusBar(Widget):
    """Status bar showing model, tokens (real-time), elapsed time, and context usage.

    Uses a reactive ``_tick`` counter so Textual re-renders automatically.
    This avoids the Static.update() clearing issue entirely.
    """

    _tick = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model_name: str = ""
        self._run_input: int = 0
        self._run_output: int = 0
        self._run_elapsed: float = 0.0
        self._context_pct: int = 0
        self._running: bool = False
        self._run_timer: Timer | None = None
        self._last_elapsed: float = 0.0
        self._last_input: int = 0
        self._last_output: int = 0

    def update_model(self, model: str) -> None:
        self._model_name = model
        self._tick += 1

    def add_tokens(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """No-op — kept for API compatibility."""
        pass

    def set_run_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self._run_input = input_tokens
        self._run_output = output_tokens
        self._tick += 1

    def set_context_usage(self, used_pct: int) -> None:
        self._context_pct = used_pct
        self._tick += 1

    def start_run(self) -> None:
        self._running = True
        self._run_elapsed = 0.0
        self._run_input = 0
        self._run_output = 0
        if self._run_timer:
            self._run_timer.stop()
        self._run_timer = self.set_interval(0.1, self._tick_elapsed)
        self._tick += 1

    def end_run(self) -> None:
        self._running = False
        if self._run_timer:
            self._run_timer.stop()
            self._run_timer = None
        self._last_elapsed = self._run_elapsed
        self._last_input = self._run_input
        self._last_output = self._run_output
        self._tick += 1

    def _tick_elapsed(self) -> None:
        if not self._running:
            return
        self._run_elapsed += 0.1
        self._tick += 1

    @staticmethod
    def _fmt(n: int) -> str:
        if n < 1000:
            return str(n)
        if n < 10_000:
            return f"{n / 1000:.1f}k"
        return f"{n // 1000}k"

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    def render(self) -> Text:
        """Build the status line. Textual calls this whenever _tick changes."""
        _ = self._tick  # access reactive to register dependency

        parts = []

        if self._model_name:
            parts.append(f"[bold]{self._model_name}[/bold]")

        if self._running:
            elapsed = self._run_elapsed
            r_in, r_out = self._run_input, self._run_output
        else:
            elapsed = self._last_elapsed
            r_in, r_out = self._last_input, self._last_output

        if elapsed > 0:
            parts.append(self._fmt_time(elapsed))
        if r_in or r_out:
            parts.append(f"{self._fmt(r_in)}\u2191 {self._fmt(r_out)}\u2193 tokens")

        if self._context_pct > 0:
            color = ""
            if self._context_pct >= 80:
                color = "[red]"
            elif self._context_pct >= 60:
                color = "[yellow]"
            parts.append(f"Context: {color}{self._context_pct}%{'[/]' if color else ''}")

        if not parts:
            markup = f"[dim]{self._model_name or 'Ready'}[/dim]"
        else:
            markup = "[dim]" + "  |  ".join(parts) + "[/dim]"

        return Text.from_markup(markup)


class QueuePanel(Widget):
    """Interactive panel showing queued messages."""

    DEFAULT_CSS = """
    QueuePanel {
        dock: bottom;
        height: auto;
        max-height: 10;
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
