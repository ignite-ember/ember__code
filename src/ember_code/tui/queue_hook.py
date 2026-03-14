"""Queue-aware tool hook — injects queued user messages between agent steps.

Agno fires ``tool_hooks`` around every tool call. This hook checks the
message queue after each tool execution and, if new messages are waiting,
pops them and sets ``agent.additional_input`` so the agent sees them on
its next model call (alongside the tool result it just produced).

Flow:
1. Tool call N starts → clear any previously injected messages
2. Tool call N executes via ``next_func``
3. After execution → pop queued messages, set ``agent.additional_input``
4. Model call N+1 sees: [tool_result_N, user: "[User sent: ...]"]
5. Agent incorporates the new context into its next reasoning step
"""

import inspect
from collections.abc import Callable
from typing import Any


class QueueInjectorHook:
    """Agno tool_hook that bridges the message queue into a running agent.

    Parameters
    ----------
    queue:
        The shared message queue (a plain ``list[str]``). Items are popped
        from the front (index 0) when injected.
    on_inject:
        Optional callback ``(message: str) -> None`` called for each
        injected message. Used to update the TUI (e.g., show a notification,
        sync the queue panel).
    on_queue_changed:
        Optional callback ``() -> None`` called after the queue is mutated
        so the UI can refresh the panel.
    """

    def __init__(
        self,
        queue: list[str],
        on_inject: Callable[[str], None] | None = None,
        on_queue_changed: Callable[[], None] | None = None,
    ):
        self._queue = queue
        self._on_inject = on_inject
        self._on_queue_changed = on_queue_changed
        self._has_injected: bool = False

    async def __call__(
        self,
        name: str,
        func: Any,
        args: dict[str, Any],
        next_func: Callable,
        agent: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Hook entry point — called by Agno around each tool execution."""
        # ── Step 1: clear previously injected messages ────────────
        if agent and self._has_injected:
            agent.additional_input = None
            self._has_injected = False

        # ── Step 2: execute the actual tool ───────────────────────
        if inspect.iscoroutinefunction(next_func):
            result = await next_func(**args)
        else:
            result = next_func(**args)

        # ── Step 3: inject queued messages ────────────────────────
        if self._queue and agent:
            self._inject_messages(agent)

        return result

    def _inject_messages(self, agent: Any) -> None:
        """Pop all queued messages and set them as additional_input."""
        try:
            from agno.models.message import Message
        except ImportError:
            return

        messages_to_inject: list[str] = []
        while self._queue:
            messages_to_inject.append(self._queue.pop(0))

        if not messages_to_inject:
            return

        agent.additional_input = [
            Message(
                role="user",
                content=f"[New message from user while you were working]: {msg}",
            )
            for msg in messages_to_inject
        ]
        self._has_injected = True

        # Notify the UI
        for msg in messages_to_inject:
            if self._on_inject:
                self._on_inject(msg)

        if self._on_queue_changed:
            self._on_queue_changed()

    def reset(self) -> None:
        """Clear injection state. Call after a run completes."""
        self._has_injected = False


def create_queue_hook(
    queue: list[str],
    on_inject: Callable[[str], None] | None = None,
    on_queue_changed: Callable[[], None] | None = None,
) -> QueueInjectorHook:
    """Factory for the queue-aware tool hook."""
    return QueueInjectorHook(
        queue=queue,
        on_inject=on_inject,
        on_queue_changed=on_queue_changed,
    )
