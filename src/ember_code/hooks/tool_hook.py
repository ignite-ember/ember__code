"""Tool event hook — fires PreToolUse/PostToolUse/PostToolUseFailure events.

Agno fires ``tool_hooks`` around every tool call. This hook bridges Agno's
tool execution into Ember's event-based hooks system, so user-defined hooks
in ``.ember/settings.json`` can run before/after tool calls.

Example user config::

    {
      "hooks": {
        "PostToolUse": [
          {
            "type": "command",
            "command": ".ember/hooks/format.sh",
            "matcher": "Write|Edit"
          }
        ]
      }
    }

The ``matcher`` regex is tested against the tool function name (e.g.,
``save_file``, ``edit_file``, ``run_shell_command``).
"""

import asyncio
import concurrent.futures
import fnmatch
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ember_code.hooks.events import HookEvent
from ember_code.hooks.executor import HookExecutor
from ember_code.hooks.schemas import HookResult

logger = logging.getLogger(__name__)

# Shared thread pool for sync→async bridging
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)

# Tool functions that write files — we check protected paths for these
_WRITE_TOOL_FUNCTIONS = frozenset(
    {
        "save_file",
        "edit_file",
        "edit_file_replace_all",
        "create_file",
    }
)


def _run_async(coro: Any) -> HookResult:
    """Run an async coroutine from a sync context via a thread."""
    return asyncio.run(coro)


def _is_protected_path(path: str, protected_patterns: list[str]) -> bool:
    """Check if a path matches any protected path pattern."""
    filename = Path(path).name
    for pattern in protected_patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


class ToolEventHook:
    """Agno tool_hook that fires PreToolUse/PostToolUse events and
    enforces protected paths.

    This is a **sync** callable — Agno's sync tool execution path filters
    out async hooks entirely, so this must be sync. Async hook executor
    calls are bridged via a thread pool.
    """

    def __init__(
        self,
        executor: HookExecutor,
        session_id: str = "",
        protected_paths: list[str] | None = None,
    ):
        self._executor = executor
        self._session_id = session_id
        self._protected_paths = protected_paths or []
        # Cache which events have hooks to avoid overhead on every tool call
        self._has_pre = bool(executor.hooks.get(HookEvent.PRE_TOOL_USE.value))
        self._has_post = bool(executor.hooks.get(HookEvent.POST_TOOL_USE.value))
        self._has_fail = bool(executor.hooks.get(HookEvent.POST_TOOL_USE_FAILURE.value))

    def __call__(
        self,
        name: str = "",
        func: Callable | None = None,
        args: dict[str, Any] | None = None,
        agent: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Hook entry point — called by Agno around each tool execution."""
        if args is None:
            args = {}

        # ── Protected paths (always enforced) ─────────────────────
        if self._protected_paths and name in _WRITE_TOOL_FUNCTIONS:
            file_path = args.get("file_path", "")
            if file_path and _is_protected_path(file_path, self._protected_paths):
                msg = f"Blocked: '{file_path}' is a protected path and cannot be written to."
                logger.warning("Protected path blocked: %s via %s", file_path, name)
                return msg

        # ── PreToolUse ────────────────────────────────────────────
        if self._has_pre:
            pre_result = self._fire(
                HookEvent.PRE_TOOL_USE.value,
                name,
                {"tool_name": name, "tool_args": _safe_args(args)},
            )
            if not pre_result.should_continue:
                logger.info("Tool '%s' blocked by PreToolUse hook: %s", name, pre_result.message)
                return pre_result.message or "Blocked by PreToolUse hook"

        # ── Execute the tool ──────────────────────────────────────
        error = None
        result = None
        try:
            if func is not None:
                result = func(**args)
        except Exception as e:
            error = e

        # ── PostToolUseFailure ────────────────────────────────────
        if error is not None:
            if self._has_fail:
                self._fire(
                    HookEvent.POST_TOOL_USE_FAILURE.value,
                    name,
                    {
                        "tool_name": name,
                        "tool_args": _safe_args(args),
                        "error": str(error),
                    },
                )
            raise error

        # ── PostToolUse ───────────────────────────────────────────
        if self._has_post:
            self._fire(
                HookEvent.POST_TOOL_USE.value,
                name,
                {
                    "tool_name": name,
                    "tool_args": _safe_args(args),
                    "result_preview": _preview(result),
                },
            )

        return result

    def _fire(self, event: str, target: str, payload: dict[str, Any]) -> HookResult:
        """Fire hooks synchronously by running the async executor in a thread."""
        # Quick check: any hooks match this target?
        hooks = self._executor.get_matching_hooks(event, target)
        if not hooks:
            return HookResult(should_continue=True)

        payload["session_id"] = self._session_id

        try:
            future = _thread_pool.submit(
                _run_async,
                self._executor.execute(event=event, payload=payload, target=target),
            )
            return future.result(timeout=15)
        except Exception as exc:
            logger.debug("Hook execution failed for %s/%s: %s", event, target, exc)
            return HookResult(should_continue=True)


def _safe_args(args: dict[str, Any]) -> dict[str, str]:
    """Convert args to strings, truncating large values."""
    safe = {}
    for k, v in args.items():
        s = str(v)
        safe[k] = s[:500] if len(s) > 500 else s
    return safe


def _preview(result: Any) -> str:
    """Return a short preview of a tool result."""
    if result is None:
        return ""
    s = str(result)
    return s[:500] if len(s) > 500 else s
