"""ExecutionManager — orchestrates message processing, run lifecycle, and cancellation."""

import asyncio
import time
from typing import TYPE_CHECKING, Any

from ember_code.tui.queue_hook import create_queue_hook
from ember_code.tui.stream_handler import StreamHandler
from ember_code.tui.widgets import QueuePanel, SpinnerWidget

if TYPE_CHECKING:
    from ember_code.session import Session
    from ember_code.tui.app import EmberApp
    from ember_code.tui.conversation_view import ConversationView
    from ember_code.tui.hitl_handler import HITLHandler
    from ember_code.tui.status_tracker import StatusTracker


class ExecutionManager:
    """Orchestrates message processing: planning, execution, streaming,
    HITL, and token tracking.

    Messages submitted while a run is in progress are queued (no limit)
    and processed sequentially after the current run finishes. The queue
    is exposed via a ``QueuePanel`` widget that allows editing and
    deleting items.
    """

    def __init__(
        self,
        app: "EmberApp",
        conversation: "ConversationView",
        status: "StatusTracker",
        hitl: "HITLHandler",
    ):
        self._app = app
        self._conversation = conversation
        self._status = status
        self._hitl = hitl

        self.processing: bool = False
        self.current_task: asyncio.Task | None = None
        self.current_run_id: str | None = None
        self.current_executor: Any | None = None
        self._queue: list[str] = []
        self._queue_hook: Any | None = None

    @property
    def _session(self) -> "Session":
        return self._app._session

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    # ── Queue management ───────────────────────────────────────────

    def enqueue(self, message: str) -> int:
        """Add a message to the queue. Returns the 1-based position."""
        self._queue.append(message)
        self._sync_queue_panel()
        return len(self._queue)

    def dequeue_at(self, index: int) -> str | None:
        """Remove and return the message at *index*, or None if invalid."""
        if 0 <= index < len(self._queue):
            msg = self._queue.pop(index)
            self._sync_queue_panel()
            return msg
        return None

    def edit_at(self, index: int, new_text: str) -> bool:
        """Replace the message at *index*. Returns True on success."""
        if 0 <= index < len(self._queue):
            self._queue[index] = new_text
            self._sync_queue_panel()
            return True
        return False

    def clear_queue(self) -> None:
        """Remove all queued messages."""
        self._queue.clear()
        self._sync_queue_panel()

    def _sync_queue_panel(self) -> None:
        """Push current queue state to the QueuePanel widget."""
        try:
            panel = self._app.query_one("#queue-panel", QueuePanel)
            panel.refresh_items(list(self._queue))
        except Exception:
            pass

    # ── Message processing ─────────────────────────────────────────

    async def process_message(self, message: str) -> None:
        if self.processing:
            pos = self.enqueue(message)
            self._conversation.append_info(
                f"Queued (position {pos}). Agent will see it between steps."
            )
            return
        await self._run_message(message)

    async def _run_message(self, message: str) -> None:
        self.processing = True
        start_time = time.monotonic()

        try:
            self._conversation.append_user(message)

            # Slash commands
            if message.startswith("/"):
                result = await self._app._command_handler.handle(message)
                self._app._render_command_result(result)
                return

            # Planning spinner
            spinner = SpinnerWidget(label="Planning")
            await self._conversation.container.mount(spinner)
            self._conversation.container.scroll_end()

            # Orchestrate
            plan = await self._session.orchestrator.plan(
                message=message,
                session_id=self._session.session_id,
                project_instructions=self._session.project_instructions,
            )

            if self._session.settings.display.show_routing or len(plan.agent_names) > 1:
                self._conversation.append_agent_tree(plan)

            # Build executor with Agno-native features + queue hook
            from ember_code.team_builder import build_team

            features = self._session.create_features()

            hook = create_queue_hook(
                queue=self._queue,
                on_inject=lambda msg: self._conversation.append_info(
                    f"[Injected from queue]: {msg[:60]}{'…' if len(msg) > 60 else ''}"
                ),
                on_queue_changed=self._sync_queue_panel,
            )
            self._queue_hook = hook
            existing = features.tool_hooks or []
            features.tool_hooks = [*existing, hook]

            executor = build_team(
                plan,
                self._session.pool,
                features=features,
            )
            self.current_executor = executor

            spinner.set_label("Executing")

            # Stream execution
            response_text = ""
            handler = StreamHandler(self._conversation.container, spinner)

            try:
                response_text = await handler.process_stream(executor, message)
            except (TypeError, AttributeError, NotImplementedError):
                # Fallback: non-streaming
                if hasattr(executor, "arun"):
                    response = await executor.arun(message)
                else:
                    response = executor.run(message)
                response_text = self._session._extract_response_text(response)
                self._conversation.append_assistant(response_text)

            # Remove spinner
            try:
                spinner.stop()
                spinner.remove()
            except Exception:
                pass

            # HITL: handle active_requirements
            if hasattr(response_text, "is_paused") and response_text.is_paused:
                await self._hitl.handle(executor, response_text)

            self.current_executor = None
            self.current_run_id = None

            self._status.record_turn()

            # Auto-generate session name on first turn
            if not self._session.session_named:
                await self._session.persistence.auto_name(executor)
                self._session.session_named = True

            # Run stats
            elapsed = time.monotonic() - start_time
            m = handler.metrics
            self._conversation.append_run_stats(
                elapsed_seconds=elapsed,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
                model=self._session.settings.models.default,
            )
            self._status.push_token_badge(
                self._conversation,
                m.input_tokens,
                m.output_tokens,
            )
            self._status.update_context_usage()
            self._status.update_status_bar()

        except Exception as e:
            self._conversation.append_error(f"Error: {e}")
            self._cleanup_spinners()
        finally:
            self.processing = False
            self.current_task = None
            if self._queue_hook:
                self._queue_hook.reset()
                self._queue_hook = None
            # Process next queued message (arrived after last tool call)
            await self._drain_queue()

    async def _drain_queue(self) -> None:
        """Process the next queued message, if any."""
        if self._queue:
            next_message = self._queue.pop(0)
            self._sync_queue_panel()
            await self._run_message(next_message)

    # ── Cancellation ───────────────────────────────────────────────

    def cancel(self) -> None:
        if not self.processing:
            return

        # Use Agno's native cancel_run if we have a run_id
        if self.current_run_id and self.current_executor:
            try:
                from agno.agent import Agent

                Agent.cancel_run(self.current_run_id)
            except Exception:
                pass

        if self.current_task and not self.current_task.done():
            self.current_task.cancel()

        self._cleanup_spinners()
        self._conversation.append_info("Cancelled.")
        self.processing = False
        self.current_task = None
        self.current_run_id = None
        self.current_executor = None

        # Clear the queue on cancel
        self.clear_queue()

    def _cleanup_spinners(self) -> None:
        try:
            for s in self._app.query(SpinnerWidget):
                s.stop()
                s.remove()
        except Exception:
            pass
