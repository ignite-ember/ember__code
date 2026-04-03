"""Hook executor — runs hooks in response to events."""

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

from ember_code.hooks.schemas import HookDefinition, HookResult

logger = logging.getLogger(__name__)


class HookExecutor:
    """Executes hooks in response to events."""

    def __init__(self, hooks: dict[str, list[HookDefinition]]):
        self.hooks = hooks

    def get_matching_hooks(self, event: str, target: str = "") -> list[HookDefinition]:
        """Get hooks that match the event and target."""
        event_hooks = self.hooks.get(event, [])
        if not target:
            return event_hooks

        matching = []
        for hook in event_hooks:
            if not hook.matcher or re.search(hook.matcher, target):
                matching.append(hook)
        return matching

    async def execute(
        self,
        event: str,
        payload: dict[str, Any],
        target: str = "",
    ) -> HookResult:
        """Execute all matching hooks for an event.

        Foreground hooks run in parallel and are awaited — if ANY hook blocks
        (exit 2), the tool call is blocked. Background hooks are fire-and-forget.

        Args:
            event: The event name (e.g., "PreToolUse").
            payload: JSON payload to send to hooks.
            target: Target to match against (e.g., tool name).

        Returns:
            Combined result from foreground hooks only.
        """
        hooks = self.get_matching_hooks(event, target)
        if not hooks:
            return HookResult(should_continue=True)

        fg_hooks = [h for h in hooks if not h.background]
        bg_hooks = [h for h in hooks if h.background]

        # Fire-and-forget background hooks
        for hook in bg_hooks:
            if hook.type == "command":
                asyncio.create_task(self._run_command_hook(hook, payload))
            elif hook.type == "http":
                asyncio.create_task(self._run_http_hook(hook, payload))

        # Run foreground hooks in parallel and await results
        tasks = []
        for hook in fg_hooks:
            if hook.type == "command":
                tasks.append(self._run_command_hook(hook, payload))
            elif hook.type == "http":
                tasks.append(self._run_http_hook(hook, payload))

        if not tasks:
            return HookResult(should_continue=True)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        should_continue = True
        messages = []

        for result in results:
            if isinstance(result, Exception):
                continue  # Non-blocking errors
            if not result.should_continue:
                should_continue = False
            if result.message:
                messages.append(result.message)

        return HookResult(
            should_continue=should_continue,
            message="\n".join(messages),
        )

    async def _run_command_hook(self, hook: HookDefinition, payload: dict[str, Any]) -> HookResult:
        """Run a command hook."""
        try:
            timeout_secs = hook.timeout / 1000
            payload_json = json.dumps(payload)

            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                hook.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=payload_json.encode()),
                timeout=timeout_secs,
            )

            if proc.returncode == 2:
                # Block
                try:
                    data = json.loads(stdout.decode())
                    msg = data.get("systemMessage", "Blocked by hook")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    msg = stderr.decode().strip() or "Blocked by hook"
                return HookResult(should_continue=False, message=msg)

            if proc.returncode == 0:
                try:
                    data = json.loads(stdout.decode())
                    return HookResult(
                        should_continue=data.get("continue", True),
                        message=data.get("systemMessage", ""),
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return HookResult(should_continue=True)

            # Other exit codes — non-blocking error
            return HookResult(should_continue=True)

        except asyncio.TimeoutError:
            return HookResult(should_continue=True, message="Hook timed out")
        except Exception as exc:
            logger.debug("Command hook failed: %s", exc)
            return HookResult(should_continue=True)

    async def _run_http_hook(self, hook: HookDefinition, payload: dict[str, Any]) -> HookResult:
        """Run an HTTP hook."""
        try:
            timeout_secs = hook.timeout / 1000

            # Expand env vars in headers
            headers = {}
            for k, v in hook.headers.items():
                headers[k] = os.path.expandvars(v)

            async with httpx.AsyncClient(timeout=timeout_secs) as client:
                response = await client.post(
                    hook.url,
                    json=payload,
                    headers=headers,
                )

            if response.status_code == 200:
                try:
                    data = response.json()
                    return HookResult(
                        should_continue=data.get("continue", True),
                        message=data.get("systemMessage", ""),
                    )
                except Exception as exc:
                    logger.debug("Failed to parse HTTP hook response: %s", exc)
                    return HookResult(should_continue=True)

            return HookResult(should_continue=True)

        except Exception as exc:
            logger.debug("HTTP hook failed: %s", exc)
            return HookResult(should_continue=True)
