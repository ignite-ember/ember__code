"""Stream handler — processes Agno streaming events into TUI widgets."""

import logging
from typing import Any

from agno.run import agent as agent_events
from agno.run import team as team_events
from textual.containers import ScrollableContainer
from textual.widgets import Static

from ember_code.tui.widgets import (
    SpinnerWidget,
    StreamingMessageWidget,
    ToolCallLiveWidget,
)

logger = logging.getLogger(__name__)


class TokenMetrics:
    """Accumulates token usage across streaming events."""

    def __init__(self):
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def accumulate(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0

    def accumulate_from_metrics(self, metrics: Any) -> None:
        """Add token counts from a metrics object (RunCompletedEvent/RunOutput)."""
        if metrics and not self.input_tokens:
            self.input_tokens = getattr(metrics, "input_tokens", 0) or 0
            self.output_tokens = getattr(metrics, "output_tokens", 0) or 0


# ── Event type sets (agent + team) ──────────────────────────────────────

_CONTENT_EVENTS = (agent_events.RunContentEvent, team_events.RunContentEvent)
_TOOL_STARTED_EVENTS = (agent_events.ToolCallStartedEvent, team_events.ToolCallStartedEvent)
_TOOL_COMPLETED_EVENTS = (agent_events.ToolCallCompletedEvent, team_events.ToolCallCompletedEvent)
_TOOL_ERROR_EVENTS = (agent_events.ToolCallErrorEvent, team_events.ToolCallErrorEvent)
_MODEL_COMPLETED_EVENTS = (
    agent_events.ModelRequestCompletedEvent,
    team_events.ModelRequestCompletedEvent,
)
_RUN_COMPLETED_EVENTS = (
    agent_events.RunCompletedEvent,
    team_events.RunCompletedEvent,
    agent_events.RunOutput,
    team_events.RunOutput,
)
_RUN_STARTED_EVENTS = (agent_events.RunStartedEvent, team_events.RunStartedEvent)
_RUN_ERROR_EVENTS = (agent_events.RunErrorEvent, team_events.RunErrorEvent)
_REASONING_EVENTS = (agent_events.ReasoningStartedEvent, team_events.ReasoningStartedEvent)
_TASK_CREATED_EVENTS = (team_events.TaskCreatedEvent,)
_TASK_UPDATED_EVENTS = (team_events.TaskUpdatedEvent,)
_TASK_ITERATION_STARTED = (team_events.TaskIterationStartedEvent,)
_TASK_STATE_UPDATED = (team_events.TaskStateUpdatedEvent,)


class StreamHandler:
    """Processes Agno streaming events and renders them into the conversation.

    Handles both Agent and Team event types:
    - RunContentEvent → StreamingMessageWidget
    - ToolCallStartedEvent/CompletedEvent → ToolCallLiveWidget
    - ModelRequestCompletedEvent → token counting in spinner
    - RunCompletedEvent / RunOutput → final metrics
    - TaskCreatedEvent/TaskUpdatedEvent → orchestration display
    - RunStartedEvent → agent dispatch display
    """

    def __init__(self, conversation: ScrollableContainer, spinner: SpinnerWidget, status_bar=None):
        self._conversation = conversation
        self._spinner = spinner
        self._status_bar = status_bar
        self._stream_widget: StreamingMessageWidget | None = None
        self.metrics = TokenMetrics()
        self.has_streamed_content: bool = False

    def _auto_scroll(self) -> None:
        """Scroll to bottom only if user is already near the bottom."""
        if self._conversation.max_scroll_y - self._conversation.scroll_y < 3:
            self._conversation.scroll_end(animate=True)

    async def process_stream(self, executor: Any, message: str) -> str:
        """Consume the async event stream and return the final response text."""
        final_response = None
        async for event in executor.arun(message, stream=True):
            await self._dispatch_event(event)
            final_response = event

        # If streaming produced content via StreamingMessageWidget, use that
        if self._stream_widget and self._stream_widget.text:
            return self._stream_widget.finalize()

        # Otherwise try to extract text from the last event / RunOutput
        if final_response is not None:
            if hasattr(final_response, "content") and final_response.content:
                text = str(final_response.content)
                if text:
                    return text
            if hasattr(final_response, "messages"):
                for msg in reversed(final_response.messages):
                    if hasattr(msg, "content") and msg.content:
                        return str(msg.content)

        return ""

    async def _dispatch_event(self, event: Any) -> None:
        """Route a single event to the appropriate handler."""
        if isinstance(event, _CONTENT_EVENTS):
            await self._on_content(event)
        elif isinstance(event, _TOOL_STARTED_EVENTS):
            await self._on_tool_started(event)
        elif isinstance(event, _TOOL_COMPLETED_EVENTS):
            self._on_tool_completed(event)
        elif isinstance(event, _TOOL_ERROR_EVENTS):
            await self._on_tool_error(event)
        elif isinstance(event, _MODEL_COMPLETED_EVENTS):
            self._on_model_request_completed(event)
        elif isinstance(event, _RUN_COMPLETED_EVENTS):
            self._on_run_completed(event)
        elif isinstance(event, _RUN_STARTED_EVENTS):
            await self._on_run_started(event)
        elif isinstance(event, _RUN_ERROR_EVENTS):
            await self._on_run_error(event)
        elif isinstance(event, _REASONING_EVENTS):
            self._spinner.set_label("Reasoning")
        elif isinstance(event, _TASK_CREATED_EVENTS):
            await self._on_task_created(event)
        elif isinstance(event, _TASK_UPDATED_EVENTS):
            await self._on_task_updated(event)
        elif isinstance(event, _TASK_ITERATION_STARTED):
            await self._on_task_iteration(event)
        elif isinstance(event, _TASK_STATE_UPDATED):
            pass  # TaskStateUpdated is noisy, skip
        elif hasattr(event, "content") and isinstance(getattr(event, "content", None), str):
            content = event.content
            if content:
                await self._on_content_text(content)
        else:
            # Log unhandled events for debugging
            event_type = type(event).__name__
            logger.debug("Unhandled stream event: %s", event_type)

    # ── Content ────────────────────────────────────────────────────

    async def _on_content_text(self, text: str) -> None:
        if self._stream_widget is None:
            self._spinner.set_label("Streaming")
            self._stream_widget = StreamingMessageWidget()
            await self._conversation.mount(self._stream_widget)
        self._stream_widget.append_chunk(text)
        self.has_streamed_content = True
        self._auto_scroll()

    async def _on_content(self, event: Any) -> None:
        if self._stream_widget is None:
            self._spinner.set_label("Streaming")
            self._stream_widget = StreamingMessageWidget()
            await self._conversation.mount(self._stream_widget)
        self._stream_widget.append_chunk(event.content)
        self.has_streamed_content = True
        self._auto_scroll()

    # ── Tool calls ─────────────────────────────────────────────────

    async def _on_tool_started(self, event: Any) -> None:
        tool_exec = event.tool
        tool_name = (tool_exec.tool_name or "tool") if tool_exec else "tool"
        args_summary = self._format_tool_args(tool_exec.tool_args if tool_exec else None)
        self._spinner.set_label(f"Running {tool_name}")
        widget = ToolCallLiveWidget(tool_name, args_summary, status="running")
        await self._conversation.mount(widget)
        self._auto_scroll()

    def _on_tool_completed(self, event: Any = None) -> None:
        result_summary = ""
        if event is not None:
            result_summary = self._extract_result_summary(event)
        try:
            for w in reversed(list(self._conversation.query(ToolCallLiveWidget))):
                if w._status == "running":
                    w.mark_done(result_summary)
                    break
        except Exception:
            pass
        self._spinner.set_label("Thinking")

    async def _on_tool_error(self, event: Any) -> None:
        error = getattr(event, "error", "Unknown error")
        tool = getattr(event, "tool", None)
        tool_name = (tool.tool_name or "tool") if tool else "tool"
        # Mark the running widget as done with error
        try:
            for w in reversed(list(self._conversation.query(ToolCallLiveWidget))):
                if w._status == "running":
                    w.mark_done(f"Error: {str(error)[:60]}")
                    break
        except Exception:
            pass
        self._spinner.set_label("Thinking")

    # ── Model / Run lifecycle ──────────────────────────────────────

    def _on_model_request_completed(self, event: Any) -> None:
        input_t = getattr(event, "input_tokens", 0)
        output_t = getattr(event, "output_tokens", 0)
        self.metrics.accumulate(input_t, output_t)
        self._spinner.set_tokens(self.metrics.total)
        if self._status_bar:
            # status_bar is actually a StatusTracker
            self._status_bar.set_run_tokens(self.metrics.input_tokens, self.metrics.output_tokens)

    def _on_run_completed(self, event: Any) -> None:
        self.metrics.accumulate_from_metrics(getattr(event, "metrics", None))

    async def _on_run_started(self, event: Any) -> None:
        """Show which agent/team member is being dispatched."""
        name = getattr(event, "agent_name", None) or getattr(event, "team_name", None)
        model = getattr(event, "model", None)
        if name:
            label = f"[dim]▸ {name}[/dim]"
            if model:
                label += f" [dim]({model})[/dim]"
            await self._conversation.mount(Static(label, classes="agent-dispatch"))
            self._auto_scroll()

    async def _on_run_error(self, event: Any) -> None:
        error = getattr(event, "content", None) or "Unknown error"
        await self._conversation.mount(
            Static(f"[red]Error: {str(error)[:120]}[/red]", classes="run-error")
        )
        self._auto_scroll()

    # ── Team orchestration ─────────────────────────────────────────

    async def _on_task_created(self, event: Any) -> None:
        title = getattr(event, "title", "")
        assignee = getattr(event, "assignee", "")
        status = getattr(event, "status", "")
        label = f"[dim]📋 Task: {title}[/dim]"
        if assignee:
            label += f" [dim]→ {assignee}[/dim]"
        if status:
            label += f" [dim][{status}][/dim]"
        await self._conversation.mount(Static(label, classes="task-event"))
        self._auto_scroll()

    async def _on_task_updated(self, event: Any) -> None:
        title = getattr(event, "title", "")
        status = getattr(event, "status", "")
        assignee = getattr(event, "assignee", "")
        prev = getattr(event, "previous_status", "")
        transition = f"{prev} → {status}" if prev else status
        label = f"[dim]📋 {title}: {transition}[/dim]"
        if assignee:
            label += f" [dim]({assignee})[/dim]"
        await self._conversation.mount(Static(label, classes="task-event"))
        self._auto_scroll()

    async def _on_task_iteration(self, event: Any) -> None:
        iteration = getattr(event, "iteration", 0)
        max_iter = getattr(event, "max_iterations", 0)
        label = f"[dim]⟳ Iteration {iteration}"
        if max_iter:
            label += f"/{max_iter}"
        label += "[/dim]"
        await self._conversation.mount(Static(label, classes="task-event"))
        self._auto_scroll()
        self._spinner.set_label(f"Iteration {iteration}")

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _extract_result_summary(event: Any) -> str:
        result = getattr(event, "result", None) or getattr(event, "content", None)
        if result is None:
            return ""
        text = str(result)
        if not text:
            return ""
        lines = text.strip().splitlines()
        n_lines = len(lines)
        if n_lines <= 1:
            short = text[:80]
            return short + "..." if len(text) > 80 else short
        return f"{n_lines} lines of output"

    @staticmethod
    def _format_tool_args(tool_args: dict | None) -> str:
        if not tool_args or not isinstance(tool_args, dict):
            return ""
        parts = []
        for k, v in list(tool_args.items())[:3]:
            val = str(v)
            if len(val) > 30:
                val = val[:27] + "..."
            parts.append(f"{k}={val}")
        return ", ".join(parts)
