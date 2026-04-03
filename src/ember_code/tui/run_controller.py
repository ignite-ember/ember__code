"""RunController — thin bridge between Agno Team and TUI widgets (Controller layer).

Calls team.arun() directly, handles Agno streaming events with isinstance
checks, manages the message queue between runs, and delegates HITL to
HITLHandler. This is the only place where Agno events meet Textual widgets.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from ember_code.queue_hook import create_queue_hook
from ember_code.tui.format_helpers import (
    CONTENT_EVENTS,
    MODEL_COMPLETED_EVENTS,
    REASONING_EVENTS,
    RUN_COMPLETED_EVENTS,
    RUN_ERROR_EVENTS,
    RUN_PAUSED_EVENTS,
    RUN_STARTED_EVENTS,
    TASK_CREATED_EVENTS,
    TASK_ITERATION_EVENTS,
    TASK_STATE_UPDATED_EVENTS,
    TASK_UPDATED_EVENTS,
    TOOL_COMPLETED_EVENTS,
    TOOL_ERROR_EVENTS,
    TOOL_NAMES,
    TOOL_STARTED_EVENTS,
    extract_result,
    format_tool_args,
)
from ember_code.tui.widgets import (
    AgentActivityWidget,
    QueuePanel,
    SpinnerWidget,
    StreamingMessageWidget,
    TaskProgressWidget,
    ToolCallLiveWidget,
)
from ember_code.tui.widgets._constants import AUTO_SCROLL_THRESHOLD
from ember_code.utils.response import extract_response_text

if TYPE_CHECKING:
    from ember_code.session.core import Session
    from ember_code.tui.app import EmberApp
    from ember_code.tui.conversation_view import ConversationView
    from ember_code.tui.hitl_handler import HITLHandler
    from ember_code.tui.status_tracker import StatusTracker

logger = logging.getLogger(__name__)


class RunController:
    """Thin controller — calls team.arun() directly, dispatches Agno events to TUI.

    Responsibilities:
    - Stream Agno events and update TUI widgets
    - Manage the message queue between runs
    - Delegate HITL confirmations to HITLHandler
    - Track token metrics for the status bar
    """

    def __init__(
        self,
        app: "EmberApp",
        conversation: "ConversationView",
        status: "StatusTracker",
        hitl: "HITLHandler",
        session: "Session",
    ):
        self._app = app
        self._conversation = conversation
        self._status = status
        self._hitl = hitl
        self._session = session

        self._stream_widget: StreamingMessageWidget | None = None
        self._spinner: AgentActivityWidget | None = None
        self._task_progress: TaskProgressWidget | None = None
        self._processing = False
        self._current_task: asyncio.Task | None = None
        self._queue: list[str] = []
        self._queue_hook: Any = None

        # Per-run token tracking
        self._run_input_tokens = 0
        self._run_output_tokens = 0
        self._streamed = False

    # ── Public API ────────────────────────────────────────────────

    @property
    def processing(self) -> bool:
        return self._processing

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def enqueue(self, message: str) -> int:
        self._queue.append(message)
        self._sync_queue_panel()
        return len(self._queue)

    def dequeue_at(self, index: int) -> str | None:
        if 0 <= index < len(self._queue):
            msg = self._queue.pop(index)
            self._sync_queue_panel()
            return msg
        return None

    def set_current_task(self, task: asyncio.Task | None) -> None:
        self._current_task = task

    async def process_message(self, message: str) -> None:
        """Entry point — queue or execute a message."""
        if self._processing:
            pos = self.enqueue(message)
            self._conversation.append_info(
                f"Queued (position {pos}). Agent will see it between steps."
            )
            return
        await self._run(message)

    def cancel(self) -> None:
        if not self._processing:
            return

        team = self._session.main_team
        try:
            from agno.agent import Agent

            run_id = getattr(team, "run_id", None)
            if run_id:
                Agent.cancel_run(run_id)
        except Exception as exc:
            logger.debug("Failed to cancel run: %s", exc)

        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

        self._processing = False
        self._current_task = None
        self._queue.clear()
        self._cleanup_spinners()
        self._conversation.append_info("Cancelled.")
        self._sync_queue_panel()

    # ── Main run loop ─────────────────────────────────────────────

    async def _run(self, message: str) -> None:
        self._conversation.append_user(message)

        # Slash commands bypass the team
        if message.startswith("/"):
            result = await self._app.command_handler.handle(message)
            self._app.render_command_result(result)
            return

        # Mount activity spinner
        self._spinner = AgentActivityWidget(label="Thinking")
        self._stream_widget = None
        await self._conversation.container.mount(self._spinner)
        self._auto_scroll()

        # Start status bar timer
        self._status.start_run()
        self._processing = True

        # Reset per-run state
        self._run_input_tokens = 0
        self._run_output_tokens = 0
        self._streamed = False

        # Wire up queue hook for this run
        hook = create_queue_hook(queue=self._queue)
        self._queue_hook = hook
        team = self._session.main_team
        existing_hooks = team.tool_hooks or []
        team.tool_hooks = [*existing_hooks, hook]

        try:
            async for event in team.arun(message, stream=True):
                await self._dispatch(event, team)
        except Exception as e:
            self._conversation.append_error(f"Error: {e}")
            logger.exception("Run error: %s", e)

        # Debug: dump messages the model saw during this run
        self._log_run_messages(team)

        # Fallback: get response from team if streaming didn't produce it
        if not self._streamed:
            rr = getattr(team, "run_response", None)
            if rr:
                rm = getattr(rr, "metrics", None)
                if rm and not self._run_input_tokens:
                    self._run_input_tokens = getattr(rm, "input_tokens", 0) or 0
                    self._run_output_tokens = getattr(rm, "output_tokens", 0) or 0
                text = extract_response_text(rr)
                if text:
                    self._conversation.append_assistant(text)

        # Finalize
        self._status.set_run_tokens(self._run_input_tokens, self._run_output_tokens)
        self._status.add_tokens(self._run_input_tokens, self._run_output_tokens)
        self._finalize_spinner()
        self._status.end_run()
        self._status.update_context_usage()
        self._status.record_turn()

        # Compact history if approaching context limit
        await self._session.compact_if_needed(
            self._run_input_tokens, self._status.max_context_tokens
        )

        # Clean up hook
        team.tool_hooks = [h for h in (team.tool_hooks or []) if h is not hook]
        hook.reset()
        self._queue_hook = None
        self._processing = False
        self._current_task = None

        # Auto-name session on first turn
        if not self._session.session_named:
            self._session.session_named = True
            asyncio.create_task(self._session.persistence.auto_name(team))

        # Drain queue
        await self._drain_queue()

    async def _drain_queue(self) -> None:
        if self._queue:
            next_msg = self._queue.pop(0)
            self._sync_queue_panel()
            await self._run(next_msg)

    # ── Event dispatch ────────────────────────────────────────────

    async def _dispatch(self, event: Any, team: Any) -> None:
        """Dispatch a single Agno event to the appropriate TUI operation."""

        # ── Content streaming ──
        if isinstance(event, CONTENT_EVENTS):
            await self._on_content(event.content)
            self._streamed = True

        # ── Tool started ──
        elif isinstance(event, TOOL_STARTED_EVENTS):
            tool_exec = event.tool
            raw_name = (tool_exec.tool_name or "tool") if tool_exec else "tool"
            friendly = TOOL_NAMES.get(raw_name, raw_name)
            args_summary = format_tool_args(tool_exec.tool_args if tool_exec else None)
            await self._on_tool_started(
                friendly, raw_name, args_summary, getattr(event, "run_id", None)
            )

        # ── Tool completed ──
        elif isinstance(event, TOOL_COMPLETED_EVENTS):
            summary, full_result = extract_result(event)
            # Debug: log tool result content reaching the model
            tool_exec = getattr(event, "tool", None)
            tool_name = (tool_exec.tool_name or "?") if tool_exec else "?"
            result_obj = getattr(tool_exec, "result", None) if tool_exec else None
            logger.debug(
                "TOOL_RESULT [%s] type=%s len=%d preview=%.200s",
                tool_name,
                type(result_obj).__name__,
                len(str(result_obj)) if result_obj is not None else 0,
                str(result_obj)[:200] if result_obj is not None else "<None>",
            )
            self._on_tool_completed(summary, full_result, getattr(event, "run_id", None))

        # ── Tool error ──
        elif isinstance(event, TOOL_ERROR_EVENTS):
            self._on_tool_error(str(getattr(event, "error", "Unknown error")))

        # ── Model completed (tokens) ──
        elif isinstance(event, MODEL_COMPLETED_EVENTS):
            input_t = getattr(event, "input_tokens", 0) or 0
            output_t = getattr(event, "output_tokens", 0) or 0
            self._run_input_tokens += input_t
            self._run_output_tokens += output_t
            self._on_tokens(
                input_t,
                output_t,
                getattr(event, "run_id", None),
                getattr(event, "parent_run_id", None),
            )

        # ── Agent/run started ──
        elif isinstance(event, RUN_STARTED_EVENTS):
            name = getattr(event, "agent_name", None) or getattr(event, "team_name", None)
            run_id = getattr(event, "run_id", None)
            if name and run_id:
                self._on_agent_started(
                    name,
                    run_id,
                    getattr(event, "parent_run_id", None),
                    str(getattr(event, "model", "") or ""),
                )

        # ── Agent/run completed ──
        elif isinstance(event, RUN_COMPLETED_EVENTS):
            evt_metrics = getattr(event, "metrics", None)
            if evt_metrics and not self._run_input_tokens:
                self._run_input_tokens = getattr(evt_metrics, "input_tokens", 0) or 0
                self._run_output_tokens = getattr(evt_metrics, "output_tokens", 0) or 0
            run_id = getattr(event, "run_id", None)
            parent_run_id = getattr(event, "parent_run_id", None)
            if run_id:
                self._on_agent_completed(run_id, parent_run_id)

        # ── Run error ──
        elif isinstance(event, RUN_ERROR_EVENTS):
            await self._on_run_error(str(getattr(event, "content", "Unknown error")))

        # ── Reasoning ──
        elif isinstance(event, REASONING_EVENTS):
            if self._spinner:
                self._spinner.set_label("Reasoning")

        # ── Task orchestration ──
        elif isinstance(event, TASK_CREATED_EVENTS):
            await self._ensure_task_progress()
            self._task_progress.on_task_created(
                task_id=getattr(event, "task_id", ""),
                title=getattr(event, "title", ""),
                assignee=getattr(event, "assignee", None),
                status=getattr(event, "status", "pending"),
            )
            self._auto_scroll()

        elif isinstance(event, TASK_UPDATED_EVENTS):
            await self._ensure_task_progress()
            self._task_progress.on_task_updated(
                task_id=getattr(event, "task_id", ""),
                status=getattr(event, "status", ""),
                assignee=getattr(event, "assignee", None),
            )
            self._auto_scroll()

        elif isinstance(event, TASK_ITERATION_EVENTS):
            await self._ensure_task_progress()
            self._task_progress.on_iteration(
                getattr(event, "iteration", 0),
                getattr(event, "max_iterations", 0),
            )
            if self._spinner:
                self._spinner.set_label(f"Iteration {getattr(event, 'iteration', 0)}")
            self._auto_scroll()

        elif isinstance(event, TASK_STATE_UPDATED_EVENTS):
            await self._ensure_task_progress()
            tasks = getattr(event, "tasks", [])
            if tasks:
                self._task_progress.on_task_state_updated(tasks)
                self._auto_scroll()

        # ── HITL pause ──
        elif isinstance(event, RUN_PAUSED_EVENTS):
            await self._on_run_paused(team, event)
            # Continue after HITL resolves
            async for cont_event in self._continue_after_pause(team, event):
                await self._dispatch(cont_event, team)

        # ── Fallback: content-like events ──
        elif hasattr(event, "content") and isinstance(getattr(event, "content", None), str):
            content = event.content
            if content:
                await self._on_content(content)
                self._streamed = True

        else:
            logger.debug("Unhandled Agno event: %s", type(event).__name__)

    # ── HITL continuation ─────────────────────────────────────────

    async def _continue_after_pause(self, team: Any, event: Any):
        """Continue execution after HITL resolves the pause."""
        try:
            if hasattr(team, "acontinue_run"):
                run_id = getattr(event, "run_id", None)
                session_id = getattr(event, "session_id", None)
                requirements = getattr(event, "requirements", None)
                async for cont_event in team.acontinue_run(
                    run_id=run_id,
                    session_id=session_id,
                    requirements=requirements,
                    stream=True,
                    stream_events=True,
                ):
                    yield cont_event
        except Exception as e:
            logger.error("Error continuing run after HITL: %s", e)
            self._conversation.append_error(f"Error continuing after confirmation: {e}")

    # ── Content ───────────────────────────────────────────────────

    async def _on_content(self, text: str) -> None:
        if self._stream_widget is None:
            if self._spinner:
                self._spinner.set_label("Streaming")
            self._stream_widget = StreamingMessageWidget()
            await self._conversation.container.mount(self._stream_widget)
        self._stream_widget.append_chunk(text)
        self._auto_scroll()

    # ── Tool calls ────────────────────────────────────────────────

    async def _on_tool_started(
        self, friendly: str, raw_name: str, args_summary: str, run_id: str | None
    ) -> None:
        # Finalize streaming widget so tool appears after text
        if self._stream_widget is not None:
            self._stream_widget.finalize()
            self._stream_widget = None

        if self._spinner:
            self._spinner.set_label(f"Running {friendly}")
            if run_id and isinstance(self._spinner, AgentActivityWidget):
                self._spinner.on_agent_tool_started(run_id, friendly)

        preview_lines = self._app.settings.display.tool_result_preview_lines
        widget = ToolCallLiveWidget(
            friendly,
            args_summary,
            status="running",
            preview_lines=preview_lines,
        )
        await self._conversation.container.mount(widget)
        self._auto_scroll()

    def _on_tool_completed(self, summary: str, full_result: str, run_id: str | None) -> None:
        try:
            for w in reversed(list(self._conversation.container.query(ToolCallLiveWidget))):
                if w.is_running():
                    w.mark_done(summary, full_result)
                    break
        except Exception as exc:
            logger.debug("Failed to mark tool completed in widget: %s", exc)

        if self._spinner:
            self._spinner.set_label("Thinking")
            if run_id and isinstance(self._spinner, AgentActivityWidget):
                self._spinner.on_agent_tool_completed(run_id)

    def _on_tool_error(self, error: str) -> None:
        try:
            for w in reversed(list(self._conversation.container.query(ToolCallLiveWidget))):
                if w.is_running():
                    w.mark_done(f"Error: {error[:60]}")
                    break
        except Exception as exc:
            logger.debug("Failed to mark tool error in widget: %s", exc)
        if self._spinner:
            self._spinner.set_label("Thinking")

    # ── Tokens ────────────────────────────────────────────────────

    def _on_tokens(
        self, input_t: int, output_t: int, run_id: str | None, parent_run_id: str | None
    ) -> None:
        if self._spinner and isinstance(self._spinner, AgentActivityWidget):
            if run_id:
                self._spinner.on_agent_tokens(run_id, input_t, output_t)
            self._spinner.set_tokens(input_t + output_t)

        self._status.set_run_tokens(input_t, output_t)
        # Track the largest single input_tokens as context size —
        # the leader's request includes full history and is always the largest
        if input_t > self._status._context_input_tokens:
            self._status.add_context_tokens(input_t)

    # ── Agent lifecycle ───────────────────────────────────────────

    def _on_agent_started(
        self, name: str, run_id: str, parent_run_id: str | None, model: str
    ) -> None:
        if self._spinner and isinstance(self._spinner, AgentActivityWidget):
            self._spinner.on_agent_started(name, run_id, parent_run_id, model)

    def _on_agent_completed(self, run_id: str, parent_run_id: str | None) -> None:
        if self._spinner and isinstance(self._spinner, AgentActivityWidget):
            self._spinner.on_agent_completed(run_id)

        # Only finalize UI on top-level run completion
        if parent_run_id:
            return

        if self._stream_widget is not None:
            self._stream_widget.finalize()
            self._stream_widget = None

    # ── Run error ─────────────────────────────────────────────────

    async def _on_run_error(self, error: str) -> None:
        await self._conversation.container.mount(
            Static(f"[red]Error: {error[:120]}[/red]", classes="run-error")
        )
        self._auto_scroll()

    # ── HITL ──────────────────────────────────────────────────────

    async def _on_run_paused(self, team: Any, event: Any) -> None:
        if self._stream_widget is not None:
            self._stream_widget.finalize()
            self._stream_widget = None

        if self._spinner:
            self._spinner.set_label("Awaiting confirmation")

        await self._hitl.handle(team, event)

        if self._spinner:
            self._spinner.set_label("Continuing")

    # ── Task orchestration ────────────────────────────────────────

    async def _ensure_task_progress(self) -> None:
        """Mount the TaskProgressWidget if not already present."""
        if self._task_progress is None:
            self._task_progress = TaskProgressWidget()
            await self._conversation.container.mount(self._task_progress)

    # ── Debug logging ────────────────────────────────────────────

    def _log_run_messages(self, team: Any) -> None:
        """Dump the messages from the last run for debugging tool result delivery."""
        try:
            rr = getattr(team, "run_response", None)
            if rr is None:
                logger.debug("RUN_MESSAGES: no run_response on team")
                return

            # Get messages from the run response
            messages = getattr(rr, "messages", None)
            if messages:
                logger.debug("RUN_MESSAGES: %d messages in run_response", len(messages))
                for i, msg in enumerate(messages):
                    role = getattr(msg, "role", "?")
                    content = getattr(msg, "content", None)
                    tool_calls = getattr(msg, "tool_calls", None)
                    tool_call_id = getattr(msg, "tool_call_id", None)
                    compressed = getattr(msg, "compressed_content", None)
                    from_hist = getattr(msg, "from_history", False)

                    content_preview = ""
                    if content is not None:
                        content_str = str(content)
                        content_preview = content_str[:200]
                        if len(content_str) > 200:
                            content_preview += f"... ({len(content_str)} total chars)"

                    extras = []
                    if tool_call_id:
                        extras.append(f"tool_call_id={tool_call_id}")
                    if tool_calls:
                        tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                        extras.append(f"tool_calls={tc_names}")
                    if compressed is not None:
                        extras.append(f"COMPRESSED len={len(str(compressed))}")
                    if from_hist:
                        extras.append("from_history")

                    extra_str = " | ".join(extras) if extras else ""
                    logger.debug(
                        "  MSG[%d] role=%s %s content=%.200s",
                        i,
                        role,
                        extra_str,
                        content_preview,
                    )
            else:
                logger.debug("RUN_MESSAGES: no messages in run_response")

            # Also log the run_response content
            resp_content = getattr(rr, "content", None)
            if resp_content:
                logger.debug(
                    "RUN_RESPONSE content (len=%d): %.300s",
                    len(str(resp_content)),
                    str(resp_content)[:300],
                )
        except Exception as e:
            logger.debug("RUN_MESSAGES: error dumping messages: %s", e)

    # ── Helpers ───────────────────────────────────────────────────

    def _auto_scroll(self) -> None:
        c = self._conversation.container
        if c.max_scroll_y - c.scroll_y < AUTO_SCROLL_THRESHOLD:
            c.scroll_end(animate=True)

    def _sync_queue_panel(self) -> None:
        try:
            panel = self._app.query_one("#queue-panel", QueuePanel)
            panel.refresh_items(list(self._queue))
        except Exception as exc:
            logger.debug("Failed to sync queue panel: %s", exc)

    def _finalize_spinner(self) -> None:
        if self._spinner:
            try:
                self._spinner.stop()
                self._spinner.remove()
            except Exception as exc:
                logger.debug("Failed to finalize spinner: %s", exc)
            self._spinner = None
        # Task progress widget stays visible after run completes (read-only)
        self._task_progress = None

    def _cleanup_spinners(self) -> None:
        for cls in (SpinnerWidget, AgentActivityWidget):
            try:
                for s in self._app.query(cls):
                    s.stop()
                    s.remove()
            except Exception as exc:
                logger.debug("Failed to cleanup spinner %s: %s", cls.__name__, exc)
