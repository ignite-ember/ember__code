"""Stream handler — processes Agno streaming events into TUI widgets."""

from typing import Any

from agno.run.agent import (
    ModelRequestCompletedEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from textual.containers import ScrollableContainer

from ember_code.tui.widgets import (
    SpinnerWidget,
    StreamingMessageWidget,
    ToolCallLiveWidget,
)


class TokenMetrics:
    """Accumulates token usage across streaming events."""

    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def accumulate_from_event(self, event: ModelRequestCompletedEvent) -> None:
        """Add token counts from a ModelRequestCompletedEvent."""
        self.input_tokens += event.input_tokens or 0
        self.output_tokens += event.output_tokens or 0

    def accumulate_from_metrics(self, metrics: Any) -> None:
        """Add token counts from a metrics object (RunCompletedEvent/RunOutput)."""
        if metrics and not self.input_tokens:
            self.input_tokens = getattr(metrics, "input_tokens", 0) or 0
            self.output_tokens = getattr(metrics, "output_tokens", 0) or 0


class StreamHandler:
    """Processes Agno streaming events and renders them into the conversation.

    Handles:
    - RunContentEvent → StreamingMessageWidget
    - ToolCallStartedEvent/CompletedEvent → ToolCallLiveWidget
    - ModelRequestCompletedEvent → token counting in spinner
    - RunCompletedEvent / RunOutput → final metrics
    """

    def __init__(self, conversation: ScrollableContainer, spinner: SpinnerWidget):
        self._conversation = conversation
        self._spinner = spinner
        self._stream_widget: StreamingMessageWidget | None = None
        self.metrics = TokenMetrics()

    async def process_stream(self, executor: Any, message: str) -> str:
        """Consume the async event stream and return the final response text.

        Args:
            executor: An Agno Agent or Team with ``arun(stream=True)``.
            message: The user message to send.

        Returns:
            The accumulated response text.
        """
        async for event in executor.arun(message, stream=True):
            await self._dispatch_event(event)

        return self._stream_widget.finalize() if self._stream_widget else ""

    async def _dispatch_event(self, event: Any) -> None:
        """Route a single event to the appropriate handler."""
        if isinstance(event, RunContentEvent):
            await self._on_content(event)
        elif isinstance(event, ToolCallStartedEvent):
            await self._on_tool_started(event)
        elif isinstance(event, ToolCallCompletedEvent):
            self._on_tool_completed()
        elif isinstance(event, ModelRequestCompletedEvent):
            self._on_model_request_completed(event)
        elif isinstance(event, (RunCompletedEvent, RunOutput)):
            self._on_run_completed(event)

    # ── Event handlers ────────────────────────────────────────────

    async def _on_content(self, event: RunContentEvent) -> None:
        if self._stream_widget is None:
            self._spinner.set_label("Streaming")
            self._stream_widget = StreamingMessageWidget()
            await self._conversation.mount(self._stream_widget)
        self._stream_widget.append_chunk(event.content)
        self._conversation.scroll_end()

    async def _on_tool_started(self, event: ToolCallStartedEvent) -> None:
        tool_exec = event.tool
        tool_name = (tool_exec.tool_name or "tool") if tool_exec else "tool"
        args_summary = self._format_tool_args(tool_exec.tool_args if tool_exec else None)
        widget = ToolCallLiveWidget(tool_name, args_summary, status="running")
        await self._conversation.mount(widget)
        self._conversation.scroll_end()

    def _on_tool_completed(self) -> None:
        try:
            for w in reversed(list(self._conversation.query(ToolCallLiveWidget))):
                if w._status == "running":
                    w.mark_done()
                    break
        except Exception:
            pass

    def _on_model_request_completed(self, event: ModelRequestCompletedEvent) -> None:
        self.metrics.accumulate_from_event(event)
        self._spinner.set_tokens(self.metrics.total)

    def _on_run_completed(self, event: Any) -> None:
        self.metrics.accumulate_from_metrics(getattr(event, "metrics", None))

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _format_tool_args(tool_args: dict | None) -> str:
        """Format tool arguments into a compact summary string."""
        if not tool_args or not isinstance(tool_args, dict):
            return ""
        parts = []
        for k, v in list(tool_args.items())[:3]:
            val = str(v)
            if len(val) > 30:
                val = val[:27] + "..."
            parts.append(f"{k}={val}")
        return ", ".join(parts)
