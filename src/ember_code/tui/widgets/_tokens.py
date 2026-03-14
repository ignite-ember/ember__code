"""Token usage display widgets."""

from textual.widgets import Static


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
        super().__init__(self._render())

    @staticmethod
    def _fmt(n: int) -> str:
        """Format token count: 1234 -> '1.2k', 12345 -> '12k'."""
        if n < 1000:
            return str(n)
        if n < 10_000:
            return f"{n / 1000:.1f}k"
        return f"{n // 1000}k"

    def _render(self) -> str:
        return f"[dim]in:[/dim] {self._fmt(self._input)}  [dim]out:[/dim] {self._fmt(self._output)}"


class RunStatsWidget(Static):
    """Displays run statistics after an agent completes: elapsed time, tokens, model."""

    DEFAULT_CSS = """
    RunStatsWidget {
        height: 1;
        margin: 0 0 1 2;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        elapsed_seconds: float,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ):
        self._elapsed = elapsed_seconds
        self._input = input_tokens
        self._output = output_tokens
        self._model = model
        super().__init__(self._render())

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        """Format seconds: '0.8s', '3.2s', '1m 12s'."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"

    def _render(self) -> str:
        parts = [f"[dim]Time:[/dim] {self._fmt_time(self._elapsed)}"]
        if self._input or self._output:
            parts.append(
                f"[dim]Tokens:[/dim] {TokenBadge._fmt(self._input)}\u2191 "
                f"{TokenBadge._fmt(self._output)}\u2193"
            )
        if self._model:
            parts.append(f"[dim]Model:[/dim] {self._model}")
        return "  ".join(parts)
