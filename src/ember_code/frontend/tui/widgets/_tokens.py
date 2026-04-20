"""Token usage display widgets."""

import time

from textual.timer import Timer
from textual.widgets import Static

from ember_code.frontend.tui.widgets._formatting import format_elapsed_time, format_token_count


class TokenBadge(Static):
    """Inline token usage display shown after an assistant message."""

    DEFAULT_CSS = """
    TokenBadge {
        height: 1;
        margin: 0 0 1 2;
        color: $text-muted;

    }
    """

    def __init__(self, input_tokens: int, output_tokens: int):
        self._input = input_tokens
        self._output = output_tokens
        super().__init__(self._format())

    @staticmethod
    def _fmt(n: int) -> str:
        """Format token count: 1234 -> '1.2k', 12345 -> '12k', 1000000 -> '1.0m'."""
        return format_token_count(n)

    def render_text(self) -> str:
        return f"in: {self._fmt(self._input)}  out: {self._fmt(self._output)}"

    def _format(self) -> str:
        return f"[dim]in:[/dim] {self._fmt(self._input)}  [dim]out:[/dim] {self._fmt(self._output)}"


class RunStatsWidget(Static):
    """Displays live run statistics: elapsed time and tokens.

    Mounts immediately when streaming starts and updates every 100ms
    with the current elapsed time.  Token counts are pushed in via
    ``update_tokens()`` as ``ModelRequestCompletedEvent`` arrives.
    When the run finishes, call ``finalize()`` to freeze the display.
    """

    DEFAULT_CSS = """
    RunStatsWidget {
        height: 1;
        margin: 0 0 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, model: str = ""):
        self._start_time = time.monotonic()
        self._elapsed: float = 0.0
        self._input: int = 0
        self._output: int = 0
        self._model = model
        self._finalized = False
        self._timer: Timer | None = None
        super().__init__(self._format())

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        if self._finalized:
            return
        self._elapsed = time.monotonic() - self._start_time
        self.update(self._format())

    def update_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Push updated token counts (called on each ModelRequestCompletedEvent)."""
        self._input = input_tokens
        self._output = output_tokens
        if not self._finalized:
            self.update(self._format())

    def finalize(self, elapsed_override: float | None = None) -> None:
        """Freeze the display with final values."""
        self._finalized = True
        if elapsed_override is not None:
            self._elapsed = elapsed_override
        else:
            self._elapsed = time.monotonic() - self._start_time
        if self._timer:
            self._timer.stop()
            self._timer = None
        self.update(self._format())

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        return format_elapsed_time(seconds)

    def render_text(self) -> str:
        """Plain-text render used by tests and direct inspection."""
        parts = [f"Time: {self._fmt_time(self._elapsed)}"]
        if self._input or self._output:
            parts.append(
                f"Tokens: {format_token_count(self._input)}\u2191 "
                f"{format_token_count(self._output)}\u2193"
            )
        if self._model:
            parts.append(f"Model: {self._model}")
        return "  ".join(parts)

    def _format(self) -> str:
        parts = [f"[dim]Time:[/dim] {self._fmt_time(self._elapsed)}"]
        if self._input or self._output:
            parts.append(
                f"[dim]Tokens:[/dim] {format_token_count(self._input)}\u2191 "
                f"{format_token_count(self._output)}\u2193"
            )
        if self._model:
            parts.append(f"[dim]Model:[/dim] {self._model}")
        return "  ".join(parts)
