"""Backend server — processes FE messages and streams BE events.

Owns the Session object and all Agno/AI logic. The FE never touches
Session directly — everything goes through protocol messages.

In Phase 2 (single-process), this is called in-process by the TUI.
In Phase 4 (multi-process), this runs as a separate process with
socket transport.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ember_code.protocol import messages as msg
from ember_code.protocol.serializer import serialize_event

if TYPE_CHECKING:
    from ember_code.core.config.settings import Settings

logger = logging.getLogger(__name__)


class BackendServer:
    """Wraps Session and handles all FE→BE protocol messages."""

    def __init__(
        self,
        settings: Settings,
        project_dir: Path | None = None,
        resume_session_id: str | None = None,
        additional_dirs: list[Path] | None = None,
    ):
        from ember_code.core.session import Session

        self._session = Session(
            settings,
            project_dir=project_dir,
            resume_session_id=resume_session_id,
            additional_dirs=additional_dirs,
        )
        self._settings = settings
        self._pending_requirements: dict[str, Any] = {}  # requirement_id → Agno requirement
        self._processing = False
        self._current_team: Any = None  # held during HITL pause

    # No .session property — all access goes through backend methods

    # ── Run a user message (streaming) ────────────────────────────

    async def run_message(
        self, text: str, media: dict[str, Any] | None = None
    ) -> AsyncIterator[msg.Message]:
        """Execute a user message and yield protocol messages.

        This is the main streaming entry point. The FE iterates over
        the yielded messages and renders them.
        """
        from ember_code.core.hooks.events import HookEvent
        from ember_code.protocol.agno_events import RUN_PAUSED_EVENTS

        self._processing = True
        team = self._session.main_team

        # Process @file mentions
        from ember_code.core.utils.mentions import process_file_mentions

        text, mentioned_files = process_file_mentions(text)
        if mentioned_files:
            yield msg.Info(text=f"Referenced: {', '.join(mentioned_files)}")

        # Resolve bare filenames and attach media for vision-capable models
        from ember_code.core.utils.media import resolve_file_references

        model_name = self._session.settings.models.default
        model_cfg = self._session.settings.models.registry.get(model_name, {})
        is_vision = model_cfg.get("vision", False)

        text, resolved_files = resolve_file_references(text, project_dir=self._session.project_dir)
        if resolved_files:
            if is_vision:
                from ember_code.core.utils.media import attach_resolved_files

                parsed_media = attach_resolved_files(resolved_files)
                if parsed_media:
                    media = parsed_media
                    yield msg.Info(text=f"Attached: {len(resolved_files)} file(s)")
                else:
                    yield msg.Info(text=f"Resolved: {', '.join(resolved_files)}")
            else:
                yield msg.Info(text=f"Resolved: {', '.join(resolved_files)}")

        # Attach media URLs (images, etc.) for vision models
        if is_vision:
            from ember_code.core.utils.media import extract_media_urls

            url_media = extract_media_urls(text)
            if url_media:
                if media:
                    for k, v in url_media.items():
                        media.setdefault(k, []).extend(v)
                else:
                    media = url_media
                count = sum(len(v) for v in url_media.values())
                yield msg.Info(text=f"Attached {count} URL(s)")

        # Inject learnings
        await self._session._inject_learnings()

        # Add timestamp
        from datetime import datetime

        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        message = f"<system-context>Current datetime: {timestamp}</system-context>\n{text}"

        # Fire UserPromptSubmit hook
        hook_result = await self._session.hook_executor.execute(
            event=HookEvent.USER_PROMPT_SUBMIT.value,
            payload={"message": text, "session_id": self._session.session_id},
        )
        if not hook_result.should_continue:
            yield msg.Error(text=hook_result.message or "Message blocked by hook.")
            self._processing = False
            return
        if hook_result.message:
            # Queue hook context for injection
            message = f"{message}\n<hook-context>{hook_result.message}</hook-context>"

        # Stream events from Agno
        media_kwargs = media or {}
        try:
            async for event in team.arun(message, stream=True, **media_kwargs):
                # HITL pause — hold the requirement for FE response
                if isinstance(event, RUN_PAUSED_EVENTS):
                    for pause_msg in self._handle_pause(event):
                        yield pause_msg
                    # Don't yield further — FE must send hitl_response
                    # and then call continue_run()
                    return

                proto = serialize_event(event)
                if proto is not None:
                    yield proto
        except asyncio.TimeoutError:
            yield msg.Error(text="Request timed out — the model took too long to respond.")
        except Exception as e:
            yield msg.Error(text=str(e))
        finally:
            self._processing = False
            await self._close_model_http_client(team)

        # Fire Stop hook
        stop_result = await self._session.hook_executor.execute(
            event=HookEvent.STOP.value,
            payload={"session_id": self._session.session_id},
        )
        if stop_result.message and not stop_result.should_continue:
            yield msg.Info(text=stop_result.message)

        # Compact if needed (caller provides context token count)
        # This will be triggered by a separate status_update flow

    def _handle_pause(self, event: Any) -> list[msg.Message]:
        """Convert a RunPausedEvent into protocol messages and store requirements."""
        from ember_code.protocol.agno_events import TOOL_NAMES

        run_id = getattr(event, "run_id", None)
        messages = []
        requirements = []
        for req in getattr(event, "active_requirements", []) or []:
            req_id = str(uuid.uuid4())[:8]
            # Store both the requirement and the run_id from the event
            self._pending_requirements[req_id] = (req, run_id)
            tool_exec = getattr(req, "tool_execution", None)
            raw_name = str(getattr(tool_exec, "tool_name", "") if tool_exec else "")
            requirements.append(
                msg.HITLRequest(
                    requirement_id=req_id,
                    tool_name=raw_name,
                    friendly_name=TOOL_NAMES.get(raw_name, raw_name),
                    tool_args=dict(getattr(tool_exec, "tool_args", {}) if tool_exec else {}),
                )
            )
        messages.append(
            msg.RunPaused(
                run_id=str(getattr(event, "run_id", "") or ""),
                requirements=requirements,
            )
        )
        return messages

    async def resolve_hitl(
        self, requirement_id: str, action: str, choice: str = "once"
    ) -> AsyncIterator[msg.Message]:
        """Resolve a HITL requirement and continue the run."""
        entry = self._pending_requirements.pop(requirement_id, None)
        if entry is None:
            yield msg.Error(text=f"Unknown requirement: {requirement_id}")
            return

        req, run_id = entry  # (requirement, run_id) tuple

        if action == "confirm":
            req.confirm()
        else:
            req.reject(note="User denied")

        # Continue the run — may yield more pauses for nested tool calls
        from ember_code.protocol.agno_events import RUN_PAUSED_EVENTS

        team = self._session.main_team
        import logging as _log

        _llm = _log.getLogger("ember_code.llm_calls")
        _llm.info("resolve_hitl: action=%s, req_id=%s, run_id=%s", action, requirement_id, run_id)
        try:
            chunk_count = 0
            async for event in team.acontinue_run(
                run_id=run_id,
                session_id=self._session.session_id,
                requirements=[req],
                stream=True,
                stream_events=True,
            ):
                chunk_count += 1
                _llm.info("resolve_hitl chunk #%d: %s", chunk_count, type(event).__name__)

                if isinstance(event, RUN_PAUSED_EVENTS):
                    for pause_msg in self._handle_pause(event):
                        yield pause_msg
                    return  # FE handles the new pause

                proto = serialize_event(event)
                if proto is not None:
                    yield proto
            _llm.info("resolve_hitl done: %d chunks", chunk_count)
        except Exception as e:
            _llm.error("resolve_hitl error: %s", e, exc_info=True)
            yield msg.Error(text=str(e))

        # Fire Stop hook after continuation completes
        from ember_code.core.hooks.events import HookEvent

        stop_result = await self._session.hook_executor.execute(
            event=HookEvent.STOP.value,
            payload={"session_id": self._session.session_id},
        )
        if stop_result.message and not stop_result.should_continue:
            yield msg.Info(text=stop_result.message)

    # ── Commands ──────────────────────────────────────────────────

    async def handle_command(self, text: str) -> msg.CommandResult:
        """Process a slash command and return the result."""
        from ember_code.backend.command_handler import CommandHandler

        handler = CommandHandler(self._session)
        result = await handler.handle(text)
        return msg.CommandResult(
            kind=result.kind,
            content=result.content,
            action=result.action or "",
        )

    # ── Session management ────────────────────────────────────────

    async def list_sessions(self) -> msg.SessionListResult:
        """List available sessions."""
        raw = await self._session.persistence.list_sessions(limit=20)
        return msg.SessionListResult(sessions=raw)

    async def switch_session(self, session_id: str) -> msg.Info:
        """Switch to a different session."""
        self._session.session_id = session_id
        self._session.session_named = True
        self._session.main_team.session_id = session_id
        self._session.persistence.session_id = session_id

        # Load history — aget_session triggers Agno to restore conversation
        agent = self._session.main_team
        await agent.aget_session(
            session_id=session_id,
            user_id=self._session.user_id,
        )
        name = await self._session.persistence.get_name()
        return msg.Info(text=f"Switched to session: {name or session_id}")

    # ── MCP ───────────────────────────────────────────────────────

    async def ensure_mcp(self) -> None:
        """Initialize MCP connections."""
        await self._session.ensure_mcp()

    async def toggle_mcp(self, server_name: str, connect: bool) -> msg.Info:
        """Connect or disconnect an MCP server."""
        mgr = self._session.mcp_manager
        if connect:
            await mgr.connect(server_name)
        else:
            await mgr.disconnect_one(server_name)
        self._session.rebuild_mcp()
        return msg.Info(text=f"MCP {'connected' if connect else 'disconnected'}: {server_name}")

    def get_mcp_status(self) -> list[tuple[str, bool]]:
        """Get MCP server connection status."""
        return self._session.get_mcp_status()

    # ── Permissions ────────────────────────────────────────────────

    def check_permission(self, tool_name: str, func_name: str, tool_args: dict) -> str:
        """Check permission level for a tool call. Returns 'allow'/'deny'/'ask'."""
        from ember_code.core.config.tool_permissions import FUNC_TO_TOOL, ToolPermissions

        perms = ToolPermissions(project_dir=self._session.project_dir)
        registry_name = FUNC_TO_TOOL.get(func_name, tool_name)
        return perms.check(registry_name, func_name, tool_args)

    def save_permission_rule(self, rule: str, level: str) -> None:
        """Persist a permission rule."""
        from ember_code.core.config.tool_permissions import ToolPermissions

        perms = ToolPermissions(project_dir=self._session.project_dir)
        perms.save_rule(rule, level)

    # ── Model ─────────────────────────────────────────────────────

    def switch_model(self, model_name: str) -> msg.Info:
        """Switch the active model."""
        old_name = self._session.settings.models.default
        old_cfg = self._session.settings.models.registry.get(old_name, {})
        new_cfg = self._session.settings.models.registry.get(model_name, {})

        self._session.settings.models.default = model_name
        self._session.main_team = self._session._build_main_agent()

        note = f"Switched to {model_name}"
        # Warn if switching from vision to non-vision with media in history
        if old_cfg.get("vision") and not new_cfg.get("vision"):
            note += (
                "\nNote: previous messages may contain images/files. "
                "Use /clear to reset if you get errors."
            )
        return msg.Info(text=note)

    # ── Login/Logout ──────────────────────────────────────────────

    async def login(self, on_status=None) -> tuple[bool, str]:
        """Run the browser-callback login flow.

        Args:
            on_status: optional callback(str) for status updates to FE

        Returns:
            (success, email) tuple
        """
        import webbrowser

        from ember_code.core.auth.client import (
            get_login_url,
            start_callback_server,
            validate_token,
            wait_for_token,
        )
        from ember_code.core.auth.credentials import decode_jwt_claims, save_credentials

        def _status(text: str) -> None:
            if on_status:
                result = on_status(text)
                # Support both sync and async callbacks
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)

        server = None
        try:
            _status("Starting local server...")
            server, callback_url = start_callback_server()
            port = int(callback_url.split(":")[2].split("/")[0])
            login_url = get_login_url(port)

            with contextlib.suppress(Exception):
                webbrowser.open(login_url)

            _status(
                f"Waiting for login in browser...\nIf the browser didn't open, go to:\n{login_url}"
            )

            try:
                token = await wait_for_token(server, timeout=300)
            except TimeoutError:
                return False, "Login timed out"

            _status("Fetching user info...")
            user_info = await validate_token(token, self._settings.auth.server_url)
            email = user_info.get("email", "") if user_info else ""

            # Read expiry from JWT for accurate TTL
            claims = decode_jwt_claims(token)
            if claims.get("exp"):
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc)
                exp = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
                ttl = max(int((exp - now).total_seconds()), 0)
                save_credentials(token, email, ttl=ttl)
            else:
                save_credentials(token, email)

            self.reload_cloud_credentials()
            return True, email

        except Exception as exc:
            return False, str(exc)
        finally:
            # Always close the callback server to free the port
            if server is not None:
                with contextlib.suppress(Exception):
                    server.server_close()

    def reload_cloud_credentials(self) -> msg.StatusUpdate:
        """Reload cloud credentials after login."""
        from ember_code.core.auth.credentials import get_access_token, get_org_id, get_org_name

        creds_file = self._settings.auth.credentials_file
        self._session._cloud_token = get_access_token(creds_file)
        self._session._cloud_org_id = get_org_id(creds_file)
        self._session._cloud_org_name = get_org_name(creds_file)
        self._session.main_team = self._session._build_main_agent()
        return self.get_status()

    def clear_cloud_credentials(self) -> msg.StatusUpdate:
        """Clear cloud credentials on logout."""
        self._session._cloud_token = None
        self._session._cloud_org_id = None
        self._session._cloud_org_name = None
        self._session.main_team = self._session._build_main_agent()
        return self.get_status()

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> msg.StatusUpdate:
        """Get current status bar data."""
        return msg.StatusUpdate(
            model=self._settings.models.default,
            cloud_connected=self._session.cloud_connected,
            cloud_org=self._session.cloud_org_name or "",
        )

    # ── Compaction ────────────────────────────────────────────────

    async def compact_if_needed(self, ctx_tokens: int, max_ctx: int) -> msg.SessionCleared | None:
        """Compact session if approaching context limit."""
        compacted = await self._session.compact_if_needed(ctx_tokens, max_ctx)
        if compacted:
            summary = ""
            with contextlib.suppress(Exception):
                agno_session = await self._session.main_team.aget_session(
                    session_id=self._session.session_id,
                    user_id=self._session.user_id,
                )
                if agno_session and agno_session.summary and agno_session.summary.summary:
                    summary = agno_session.summary.summary
            return msg.SessionCleared(
                new_session_id=self._session.session_id,
                summary=summary,
            )
        return None

    # ── Learning ──────────────────────────────────────────────────

    async def extract_learnings(self, user_msg: str, assistant_msg: str) -> None:
        """Run learning extraction in background."""
        learning = self._session._learning
        if learning is None:
            return

        from agno.models.message import Message as AgnoMessage

        messages = [AgnoMessage(role="user", content=user_msg)]
        if assistant_msg:
            messages.append(AgnoMessage(role="assistant", content=assistant_msg))

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
                logger.warning("Learning extraction failed: %s", exc)
            finally:
                with contextlib.suppress(Exception):
                    loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

        with contextlib.suppress(Exception):
            await asyncio.to_thread(_run)

    # ── Cleanup ───────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Graceful shutdown — disconnect MCP, fire hooks, kill bg processes."""
        from ember_code.core.hooks.events import HookEvent
        from ember_code.core.tools.shell import EmberShellTools

        with contextlib.suppress(Exception):
            await self._session.hook_executor.execute(
                event=HookEvent.SESSION_END.value,
                payload={"session_id": self._session.session_id},
            )
        with contextlib.suppress(Exception):
            if self._session.settings.orchestration.auto_cleanup:
                self._session.pool.cleanup_ephemeral()
        with contextlib.suppress(Exception):
            await self._session.mcp_manager.disconnect_all()
        with contextlib.suppress(Exception):
            killed = EmberShellTools.cleanup()
            if killed:
                logger.info("Shutdown: killed %d background process(es)", killed)

    # ── Accessors for FE (read-only state) ──────────────────────

    def wire_queue_hook(self, queue: list) -> None:
        """Wire the queue injection hook onto the agent's tool hooks."""
        from ember_code.core.queue_hook import create_queue_hook

        hook = create_queue_hook(queue=queue)
        team = self._session.main_team
        existing = team.tool_hooks or []
        team.tool_hooks = [*existing, hook]

    def wire_orchestrate_progress(self, callback) -> None:
        """Set a progress callback on the orchestrate tool."""
        from ember_code.core.tools.orchestrate import OrchestrateTools

        for tool in self._session.main_team.tools or []:
            if isinstance(tool, OrchestrateTools):
                tool._on_progress = callback
                break

    @staticmethod
    async def _close_model_http_client(team: Any) -> None:
        """Close the httpx client on the model to release open HTTP streams.

        When an Agno run finishes or is cancelled mid-stream, the underlying
        httpx connection to the API may stay open indefinitely. Closing the
        client ensures the TCP connection is torn down promptly so the server
        can release concurrency slots. A fresh client is assigned so the model
        remains usable for subsequent runs.
        """
        import httpx as _httpx

        try:
            model = getattr(team, "model", None)
            client = getattr(model, "http_client", None) if model else None
            if isinstance(client, _httpx.AsyncClient):
                await client.aclose()
                model.http_client = _httpx.AsyncClient(
                    limits=_httpx.Limits(
                        max_connections=10,
                        max_keepalive_connections=5,
                        keepalive_expiry=30,
                    ),
                )
        except Exception as exc:
            logger.debug("Failed to close model HTTP client: %s", exc)

    def cancel_run(self) -> None:
        """Cancel the currently running agent and kill any foreground process."""
        # Kill the active foreground subprocess first so the blocking
        # tool call returns quickly and the Agno cancellation can fire.
        from ember_code.core.tools.shell import cancel_foreground

        if cancel_foreground():
            logger.info("Killed foreground process on cancel")

        try:
            from agno.agent import Agent

            team = self._session.main_team
            run_id = getattr(team, "run_id", None)
            if run_id:
                Agent.cancel_run(run_id)
        except Exception as exc:
            logger.debug("Failed to cancel run: %s", exc)

    @property
    def processing(self) -> bool:
        return self._processing

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def run_timeout(self) -> int:
        return self._settings.models.max_run_timeout

    @property
    def skill_names(self) -> list[str]:
        """Skill names for input autocomplete — FE needs these for the input handler."""
        return [s.name for s in self._session.skill_pool.list_skills()]

    def get_skill_pool(self):
        """Return the skill pool for input autocomplete."""
        return self._session.skill_pool

    def get_mcp_server_details(self) -> list[dict]:
        """Full MCP server info for the panel UI."""
        mgr = self._session.mcp_manager
        servers = []
        for name in mgr.list_servers():
            config = mgr.configs.get(name)
            connected = name in mgr.list_connected()
            servers.append(
                {
                    "name": name,
                    "connected": connected,
                    "transport": config.type if config else "unknown",
                    "tool_names": mgr.get_tools(name),
                    "tool_descriptions": mgr.get_tool_descriptions(name),
                    "error": mgr.get_error(name),
                    "policy_blocked": mgr._policy.is_denied(name),
                }
            )
        return servers

    async def get_chat_history(self, session_id: str) -> list[dict]:
        """Get chat history for a session. Returns list of {role, content} dicts."""
        agent = self._session.main_team
        agno_session = await agent.aget_session(
            session_id=session_id,
            user_id=self._session.user_id,
        )
        if agno_session is None:
            return []
        messages = agno_session.get_chat_history()
        if not messages:
            return []
        return [
            {
                "role": msg.role,
                "content": msg.content if isinstance(msg.content, str) else str(msg.content or ""),
            }
            for msg in messages
        ]

    def get_mcp_servers(self) -> list[dict]:
        """MCP server info for the panel."""
        mgr = self._session.mcp_manager
        servers = []
        for name in mgr.list_servers():
            connected = name in mgr.list_connected()
            servers.append({"name": name, "connected": connected})
        return servers

    async def mcp_connect(self, server_name: str) -> msg.Info:
        """Connect a single MCP server."""
        await self._session.mcp_manager.connect(server_name)
        self._session.rebuild_mcp()
        return msg.Info(text=f"Connected MCP: {server_name}")

    async def mcp_disconnect(self, server_name: str) -> msg.Info:
        """Disconnect a single MCP server."""
        await self._session.mcp_manager.disconnect_one(server_name)
        self._session.rebuild_mcp()
        return msg.Info(text=f"Disconnected MCP: {server_name}")

    async def fire_session_start_hook(self) -> None:
        """Fire the SessionStart hook."""
        from ember_code.core.hooks.events import HookEvent

        with contextlib.suppress(Exception):
            await self._session.hook_executor.execute(
                event=HookEvent.SESSION_START.value,
                payload={"session_id": self._session.session_id},
            )

    async def auto_sync_knowledge(self) -> str | None:
        """Auto-sync knowledge file on startup. Returns status message or None."""
        if self._session.knowledge is None:
            return None
        try:
            result = await self._session.knowledge_mgr.sync_from_file()
            if result:
                return f"Knowledge synced: {result}"
        except Exception:
            pass
        return None

    async def execute_scheduled_task(self, description: str) -> str:
        """Execute a scheduled task via the agent. Returns result text."""
        from ember_code.core.utils.response import extract_response_text

        team = self._session.main_team
        response = await team.arun(description, stream=False)
        return extract_response_text(response)

    async def cancel_scheduled_task(self, task_id: str) -> msg.Info:
        """Cancel a scheduled task."""
        from ember_code.core.scheduler.models import TaskStatus
        from ember_code.core.scheduler.store import TaskStore

        store = TaskStore()
        await store.update_status(task_id, TaskStatus.cancelled)
        return msg.Info(text=f"Cancelled task {task_id}")

    async def get_scheduled_tasks(self, include_done: bool = True) -> list:
        """Get all scheduled tasks."""
        from ember_code.core.scheduler.store import TaskStore

        store = TaskStore()
        return await store.get_all(include_done=include_done)

    def start_scheduler(
        self,
        on_task_started=None,
        on_task_completed=None,
    ) -> Any:
        """Start the background scheduler. Returns the runner for stop()."""
        from ember_code.core.scheduler.runner import SchedulerRunner
        from ember_code.core.scheduler.store import TaskStore

        sched_cfg = self._settings.scheduler
        store = TaskStore()
        runner = SchedulerRunner(
            store=store,
            execute_fn=self.execute_scheduled_task,
            on_task_started=on_task_started,
            on_task_completed=on_task_completed,
            poll_interval=sched_cfg.poll_interval,
            task_timeout=sched_cfg.task_timeout,
            max_concurrent=sched_cfg.max_concurrent,
        )
        runner.start()
        return runner

    def toggle_verbose(self) -> bool:
        """Toggle verbose mode. Returns new state."""
        self._settings.display.show_routing = not self._settings.display.show_routing
        return self._settings.display.show_routing
