"""Tool event hook — fires PreToolUse/PostToolUse/PostToolUseFailure events.

Agno fires ``tool_hooks`` around every tool call. This async hook works
in Agno's async execution chain (``aexecute``). For sync tools, Agno
wraps them in the async chain and our hook properly handles both sync
and async ``func`` via ``inspect.isawaitable``.
"""

import fnmatch
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ember_code.core.hooks.events import HookEvent
from ember_code.core.hooks.executor import HookExecutor
from ember_code.core.hooks.schemas import HookResult

logger = logging.getLogger(__name__)

_WRITE_TOOL_FUNCTIONS = frozenset(
    {
        "save_file",
        "edit_file",
        "edit_file_replace_all",
        "create_file",
    }
)

_SHELL_TOOL_FUNCTIONS = frozenset({"run_shell_command"})


def _is_protected_path(path: str, protected_patterns: list[str]) -> bool:
    filename = Path(path).name
    for pattern in protected_patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


class ToolEventHook:
    """Async Agno tool_hook for pre/post events and protected paths."""

    def __init__(
        self,
        executor: HookExecutor,
        session_id: str = "",
        protected_paths: list[str] | None = None,
        blocked_commands: list[str] | None = None,
    ):
        # Mark instance as coroutine function so Agno uses aexecute() path
        inspect.markcoroutinefunction(self)
        self._executor = executor
        self._session_id = session_id
        self._protected_paths = protected_paths or []
        self._blocked_commands = blocked_commands or []
        self._has_pre = bool(executor.hooks.get(HookEvent.PRE_TOOL_USE.value))
        self._has_post = bool(executor.hooks.get(HookEvent.POST_TOOL_USE.value))
        self._has_fail = bool(executor.hooks.get(HookEvent.POST_TOOL_USE_FAILURE.value))

    async def __call__(
        self,
        name: str = "",
        func: Callable | None = None,
        args: dict[str, Any] | None = None,
        agent: Any = None,
        **kwargs: Any,
    ) -> Any:
        if args is None:
            args = {}

        # Protected paths
        if self._protected_paths and name in _WRITE_TOOL_FUNCTIONS:
            file_path = args.get("file_path", "")
            if file_path and _is_protected_path(file_path, self._protected_paths):
                msg = f"Blocked: '{file_path}' is a protected path and cannot be written to."
                logger.warning("Protected path blocked: %s via %s", file_path, name)
                return msg

        # Blocked commands
        if self._blocked_commands and name in _SHELL_TOOL_FUNCTIONS:
            cmd_args = args.get("args", [])
            cmd_str = (
                " ".join(str(a) for a in cmd_args) if isinstance(cmd_args, list) else str(cmd_args)
            )
            for blocked in self._blocked_commands:
                if blocked in cmd_str:
                    msg = f"Blocked: command matches blocked pattern '{blocked}'."
                    logger.warning("Blocked command: %s", cmd_str)
                    return msg

        # PreToolUse
        if self._has_pre:
            pre_result = await self._fire(
                HookEvent.PRE_TOOL_USE.value,
                name,
                {"tool_name": name, "tool_args": _safe_args(args)},
            )
            if not pre_result.should_continue:
                return pre_result.message or "Blocked by PreToolUse hook"

        # Execute the tool
        if func is None:
            return None

        error = None
        result = None
        try:
            result = func(**args)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            error = e

        # PostToolUseFailure
        if error is not None:
            if self._has_fail:
                await self._fire(
                    HookEvent.POST_TOOL_USE_FAILURE.value,
                    name,
                    {"tool_name": name, "tool_args": _safe_args(args), "error": str(error)},
                )
            raise error

        # PostToolUse
        if self._has_post:
            await self._fire(
                HookEvent.POST_TOOL_USE.value,
                name,
                {
                    "tool_name": name,
                    "tool_args": _safe_args(args),
                    "result_preview": _preview(result),
                },
            )

        return result

    async def _fire(self, event: str, target: str, payload: dict[str, Any]) -> HookResult:
        hooks = self._executor.get_matching_hooks(event, target)
        if not hooks:
            return HookResult(should_continue=True)
        payload["session_id"] = self._session_id
        try:
            return await self._executor.execute(event=event, payload=payload, target=target)
        except Exception as exc:
            logger.debug("Hook %s/%s failed: %s", event, target, exc)
            return HookResult(should_continue=True)


def _safe_args(args: dict[str, Any]) -> dict[str, str]:
    safe = {}
    for k, v in args.items():
        s = str(v)
        safe[k] = s[:500] if len(s) > 500 else s
    return safe


def _preview(result: Any) -> str:
    if result is None:
        return ""
    s = str(result)
    return s[:500] if len(s) > 500 else s
