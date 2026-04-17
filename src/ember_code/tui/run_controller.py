"""RunController — thin bridge between Agno Team and TUI widgets (Controller layer).

Calls team.arun() directly, handles Agno streaming events with isinstance
checks, manages the message queue between runs, and delegates HITL to
HITLHandler. This is the only place where Agno events meet Textual widgets.
"""

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import tiktoken
from textual.widgets import Static

from ember_code.queue_hook import create_queue_hook
from ember_code.tui.format_helpers import (
    CONTENT_EVENTS,
    MODEL_COMPLETED_EVENTS,
    REASONING_CONTENT_EVENTS,
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
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

        # Per-run token tracking
        self._run_input_tokens = 0
        self._run_output_tokens = 0
        self._streamed = False

        # Learning extraction runs every N turns (or before compaction)
        self._turn_count = 0
        self._learning_interval = 10
        self._pending_learn_messages: list = []  # accumulated since last extraction

        # Hook system messages queued for injection into next AI turn
        self._pending_hook_context: list[str] = []

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

        # Fire UserPromptSubmit hook (can block)
        from ember_code.hooks.events import HookEvent

        hook_result = await self._session.hook_executor.execute(
            event=HookEvent.USER_PROMPT_SUBMIT.value,
            payload={"message": message, "session_id": self._session.session_id},
        )
        if not hook_result.should_continue:
            self._conversation.append_info(hook_result.message or "Message blocked by hook.")
            return
        if hook_result.message:
            self._pending_hook_context.append(hook_result.message)

        # Slash commands bypass the team
        if message.startswith("/"):
            result = await self._app.command_handler.handle(message)
            self._app.render_command_result(result)
            return

        # Process @file mentions — strip @ prefix and add read hint
        from ember_code.tui.input_handler import process_file_mentions

        message, mentioned_files = process_file_mentions(message)
        if mentioned_files:
            self._conversation.append_info(f"Referenced: {', '.join(mentioned_files)}")

        # Auto-detect media (images, audio, videos, documents) from message text
        from ember_code.utils.media import parse_media_from_text

        cleaned, media = parse_media_from_text(message)
        media_kwargs = media.as_kwargs()
        if media.has_media:
            message = cleaned
            self._conversation.append_info(f"Attached: {media.summary()}")

        # Mount activity spinner
        self._spinner = AgentActivityWidget(label="Thinking")
        self._stream_widget = None
        self._thinking_widget = None
        self._in_thinking = False
        self._model_uses_think_tags = False  # set True on first <think> detection
        await self._conversation.container.mount(self._spinner)
        self._auto_scroll()

        # Start status bar timer
        self._status.start_run()
        self._processing = True

        # Reset per-run state
        self._run_input_tokens = 0
        self._run_output_tokens = 0
        self._run_output_text = []  # accumulate streamed text for token counting
        self._last_token_update = 0.0  # throttle status bar updates
        self._streamed = False
        self._ui_finalized = False

        # Wire up queue hook for this run
        hook = create_queue_hook(queue=self._queue)
        self._queue_hook = hook
        team = self._session.main_team
        existing_hooks = team.tool_hooks or []
        team.tool_hooks = [*existing_hooks, hook]

        # Save original message for learning extraction (before timestamp)
        original_message = message

        # Add system context with timestamp so the agent knows the current time
        from datetime import datetime

        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        message = f"<system-context>Current datetime: {timestamp}</system-context>\n{message}"

        # Inject queued hook messages into the AI's context
        if self._pending_hook_context:
            hook_ctx = "\n".join(self._pending_hook_context)
            message = f"{message}\n<hook-context>{hook_ctx}</hook-context>"
            self._pending_hook_context.clear()

        # Inject latest learnings into agent context
        await self._session._inject_learnings()

        # Count input tokens from message
        self._run_input_tokens = len(self._tokenizer.encode(message))

        try:
            # Total run timeout — prevents indefinite hangs even when
            # keepalive data keeps the underlying connection alive.
            run_timeout = self._session.settings.models.max_run_timeout
            _llm_log = logging.getLogger("ember_code.llm_calls")
            _llm_log.info("RUN START | msg_len=%d | timeout=%ds", len(message), run_timeout)
            _run_t0 = __import__("time").monotonic()
            _chunk_count = 0
            _content_count = 0
            _last_chunk_time = _run_t0

            async with asyncio.timeout(run_timeout):
                async for event in team.arun(message, stream=True, **media_kwargs):
                    _chunk_count += 1
                    _now = __import__("time").monotonic()
                    _gap = _now - _last_chunk_time
                    _last_chunk_time = _now

                    etype = type(event).__name__
                    has_content = bool(getattr(event, "content", None))
                    if has_content:
                        _content_count += 1

                    # Log slow gaps (>5s between chunks) and every 50th chunk
                    if _gap > 5.0 or _chunk_count <= 3 or _chunk_count % 50 == 0:
                        _llm_log.info(
                            "RUN CHUNK #%d | type=%s | content=%s | gap=%.1fs | elapsed=%.1fs",
                            _chunk_count,
                            etype,
                            has_content,
                            _gap,
                            _now - _run_t0,
                        )

                    await self._dispatch(event, team)

            _elapsed = __import__("time").monotonic() - _run_t0
            _llm_log.info(
                "RUN DONE | chunks=%d | content_chunks=%d | elapsed=%.1fs",
                _chunk_count,
                _content_count,
                _elapsed,
            )
        except TimeoutError:
            _elapsed = __import__("time").monotonic() - _run_t0
            _llm_log.error(
                "RUN TIMEOUT | chunks=%d | content_chunks=%d | elapsed=%.1fs | last_gap=%.1fs",
                _chunk_count,
                _content_count,
                _elapsed,
                __import__("time").monotonic() - _last_chunk_time,
            )
            self._conversation.append_error(
                "Request timed out — the model took too long to respond. Try again."
            )
        except Exception as e:
            _elapsed = __import__("time").monotonic() - _run_t0
            _llm_log.error(
                "RUN ERROR | chunks=%d | elapsed=%.1fs | error=%s",
                _chunk_count,
                _elapsed,
                e,
            )
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

        # Finalize UI if not already done by RUN_COMPLETED event
        if not getattr(self, "_ui_finalized", False):
            if self._run_output_text:
                full_output = "".join(self._run_output_text)
                self._run_output_tokens = len(self._tokenizer.encode(full_output))
            self._status.set_run_tokens(self._run_input_tokens, self._run_output_tokens)
            self._status.add_tokens(self._run_input_tokens, self._run_output_tokens)
            self._finalize_spinner()
            self._status.end_run()
            self._status.update_context_usage()
        self._ui_finalized = False
        self._status.record_turn()

        # Accumulate messages for batched learning extraction
        self._turn_count += 1
        from agno.models.message import Message as AgnoMessage

        self._pending_learn_messages.append(AgnoMessage(role="user", content=original_message))
        if self._run_output_text:
            self._pending_learn_messages.append(
                AgnoMessage(role="assistant", content="".join(self._run_output_text))
            )

        # Compact history if approaching context limit
        ctx_tokens = self._status._context_input_tokens
        max_ctx = self._status.max_context_tokens
        compacted = await self._session.compact_if_needed(ctx_tokens, max_ctx)
        if compacted:
            # Extract learnings before context is lost
            self._flush_learnings()
            # Clear the visual conversation and show summary
            await self._conversation.container.remove_children()
            self._conversation.append_info("Context compacted — older messages summarized.")
            # Show the full summary so the user knows what was retained
            try:
                agno_session = await self._session.main_team.aget_session(
                    session_id=self._session.session_id,
                    user_id=self._session.user_id,
                )
                if agno_session and agno_session.summary and agno_session.summary.summary:
                    self._conversation.append_info(f"Summary: {agno_session.summary.summary}")
            except Exception:
                pass
            # Reset context tracking and force status bar to show 0%
            self._status._context_input_tokens = 0
            bar = self._status._bar()
            if bar:
                bar.set_context_usage(0, self._status.max_context_tokens)
                bar.set_run_tokens(0, 0)

        # Fire Stop hook — messages are injected into the AI's next turn context
        stop_result = await self._session.hook_executor.execute(
            event=HookEvent.STOP.value,
            payload={"session_id": self._session.session_id},
        )
        if stop_result.message:
            if not stop_result.should_continue:
                # Blocking: show to user
                self._conversation.append_info(stop_result.message)
            else:
                # Non-blocking: queue for AI context on next turn
                self._pending_hook_context.append(stop_result.message)

        # Extract learnings every N turns
        if self._turn_count % self._learning_interval == 0:
            self._flush_learnings()

        # Clean up hook
        self._processing = False
        self._current_task = None

        # Drain queue
        await self._drain_queue()

    def _flush_learnings(self) -> None:
        """Send accumulated messages to learning extraction and reset buffer."""
        learning = self._session._learning
        if learning is None or not self._pending_learn_messages:
            return
        messages = self._pending_learn_messages[:]
        self._pending_learn_messages.clear()
        task = asyncio.create_task(self._extract_learnings(learning, messages))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _drain_queue(self) -> None:
        if self._queue:
            next_msg = self._queue.pop(0)
            self._sync_queue_panel()
            await self._run(next_msg)

    async def _extract_learnings(self, learning: Any, messages: list) -> None:
        """Fire-and-forget learning extraction in a background thread."""

        def _run():
            import asyncio as _aio

            loop = _aio.new_event_loop()
            try:
                loop.run_until_complete(
                    learning.aprocess(
                        messages=messages,
                        user_id=self._session.user_id,
                        session_id=self._session.session_id,
                    )
                )
            except Exception as exc:
                import logging

                logging.getLogger("ember_code.llm_calls").warning(
                    "Learning extraction failed: %s", exc
                )
            finally:
                # Suppress "Event loop is closed" from httpx/asyncio cleanup
                with contextlib.suppress(Exception):
                    loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

        with contextlib.suppress(Exception):
            await asyncio.to_thread(_run)

    # ── Event dispatch ────────────────────────────────────────────

    async def _dispatch(self, event: Any, team: Any) -> None:
        """Dispatch a single Agno event to the appropriate TUI operation."""

        # ── Native reasoning content (models that separate it, e.g. OpenAI o1) ──
        if isinstance(event, REASONING_CONTENT_EVENTS):
            rc = getattr(event, "reasoning_content", "") or ""
            if rc:
                await self._append_thinking(rc)

        # ── Content streaming (with <think> tag detection for models that inline it) ──
        elif isinstance(event, CONTENT_EVENTS):
            content = event.content or ""
            if content:
                await self._on_content_chunk(content)
                self._streamed = True
                # Count output tokens — recount full text every 1s
                self._run_output_text.append(content)
                import time as _time

                now = _time.monotonic()
                if now - self._last_token_update > 1.0:
                    self._last_token_update = now
                    full_output = "".join(self._run_output_text)
                    self._run_output_tokens = len(self._tokenizer.encode(full_output))
                    self._status.set_run_tokens(self._run_input_tokens, self._run_output_tokens)

        # ── Tool started ──
        elif isinstance(event, TOOL_STARTED_EVENTS):
            tool_exec = event.tool
            raw_name = (tool_exec.tool_name or "tool") if tool_exec else "tool"
            friendly = TOOL_NAMES.get(raw_name, raw_name)
            args_summary = format_tool_args(
                tool_exec.tool_args if tool_exec else None,
                tool_name=raw_name,
            )
            await self._on_tool_started(
                friendly, raw_name, args_summary, getattr(event, "run_id", None)
            )

        # ── Tool completed ──
        elif isinstance(event, TOOL_COMPLETED_EVENTS):
            summary, full_result = extract_result(event)
            # Count tool result tokens (added to context as input)
            self._run_input_tokens += len(self._tokenizer.encode(full_result))
            self._status.set_run_tokens(self._run_input_tokens, self._run_output_tokens)
            self._status.update_status_bar()
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

        # ── Model completed (tokens) — use real numbers if available ──
        elif isinstance(event, MODEL_COMPLETED_EVENTS):
            input_t = getattr(event, "input_tokens", 0) or 0
            output_t = getattr(event, "output_tokens", 0) or 0
            if input_t > 0:
                self._run_input_tokens = input_t
            if output_t > 0:
                self._run_output_tokens = output_t
            self._on_tokens(
                input_t,
                output_t,
                getattr(event, "run_id", None),
                getattr(event, "parent_run_id", None),
            )
            # Finalize spinner and timer on model completion — don't wait
            # for background learning extraction (can take 20+ seconds).
            # Note: _processing stays True until arun() fully completes.
            if self._streamed and not self._ui_finalized:
                self._ui_finalized = True
                if self._run_output_text:
                    full_output = "".join(self._run_output_text)
                    self._run_output_tokens = len(self._tokenizer.encode(full_output))
                self._status.set_run_tokens(self._run_input_tokens, self._run_output_tokens)
                self._status.add_tokens(self._run_input_tokens, self._run_output_tokens)
                self._finalize_spinner()
                self._status.end_run()
                self._status.update_context_usage()

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

    async def _on_content_chunk(self, chunk: str) -> None:
        """Route streamed content to thinking (dimmed) or response widget.

        Models wrap thinking in ``<think>...</think>`` tags within the
        content stream.  We detect the tags and split accordingly.
        """
        # Check for <think> open tag
        if not self._in_thinking and "<think>" in chunk:
            self._in_thinking = True
            self._model_uses_think_tags = True
            chunk = chunk.split("<think>", 1)[1]
            if not chunk:
                return

        # Check for </think> close tag — handles both:
        # 1. Normal: <think>..content..</think> (in_thinking=True)
        # 2. Post-tool: content..</think> (model resumes thinking without open tag)
        if "</think>" in chunk:
            before, after = chunk.split("</think>", 1)
            if before:
                await self._append_thinking(before)
            self._in_thinking = False
            if self._thinking_widget is not None:
                self._thinking_widget.finalize()
                self._thinking_widget = None
            after = after.lstrip("\n")
            if after:
                await self._append_content(after)
            return

        if self._in_thinking:
            await self._append_thinking(chunk)
        else:
            await self._append_content(chunk)

    async def _append_thinking(self, text: str) -> None:
        """Stream thinking text in dimmed style."""
        if self._thinking_widget is None:
            if self._spinner:
                self._spinner.set_label("Thinking")
            self._thinking_widget = StreamingMessageWidget(css_class="thinking")
            await self._conversation.container.mount(self._thinking_widget)
        self._thinking_widget.append_chunk(text)
        self._auto_scroll()

    async def _append_content(self, text: str) -> None:
        """Stream response content in normal style."""
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
        # Finalize streaming/thinking widgets so tool appears after text
        if self._stream_widget is not None:
            self._stream_widget.finalize()
            self._stream_widget = None
        if self._thinking_widget is not None:
            self._thinking_widget.finalize()
            self._thinking_widget = None
        self._in_thinking = False

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

        # Wire live progress for orchestrate tools (spawn_agent/spawn_team)
        if raw_name in ("spawn_agent", "spawn_team"):
            self._wire_orchestrate_progress(widget)

    def _wire_orchestrate_progress(self, widget: ToolCallLiveWidget) -> None:
        """Set up live progress updates for orchestrate tool calls."""
        from ember_code.tools.orchestrate import OrchestrateTools

        agent = self._session.main_team
        for tool in agent.tools or []:
            if isinstance(tool, OrchestrateTools):

                def _progress(line: str, w: ToolCallLiveWidget = widget) -> None:
                    w.update_progress(line)
                    self._auto_scroll()

                tool._on_progress = _progress
                break

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

        # After a tool call, models that use <think> tags typically resume
        # thinking without an opening tag (only emitting </think> to close).
        # Pre-enter thinking mode only if we've seen <think> tags before.
        if self._model_uses_think_tags:
            self._in_thinking = True

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
            c.scroll_end(animate=False)

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
