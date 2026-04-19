"""Backend process entry point.

Usage: python -m ember_code.backend --socket /tmp/ember-code/<uuid>.sock

Starts a BackendServer, listens on the given Unix socket, and
processes FE messages until shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)


@click.command()
@click.option("--socket", "socket_path", required=True, help="Unix socket path")
@click.option("--project-dir", type=click.Path(exists=True), default=".")
@click.option("--resume-session", "resume_session_id", default=None)
@click.option("--additional-dirs", multiple=True, default=())
@click.option("--debug", is_flag=True, default=False)
def main(
    socket_path: str,
    project_dir: str,
    resume_session_id: str | None,
    additional_dirs: tuple[str, ...],
    debug: bool,
) -> None:
    """Start the Ember Code backend server."""
    if debug:
        log_path = Path.home() / ".ember" / "debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(log_path),
            level=logging.DEBUG,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            force=True,
        )
        logging.getLogger("ember_code").setLevel(logging.DEBUG)

    extra_dirs = [Path(d) for d in additional_dirs] if additional_dirs else None
    asyncio.run(_run(socket_path, Path(project_dir), resume_session_id, extra_dirs))


async def _check_update() -> dict | None:
    try:
        from ember_code.core.utils.update_checker import check_for_update

        info = await check_for_update()
        if info and info.available:
            return {"available": True, "version": info.latest_version, "message": info.message}
    except Exception:
        pass
    return None


# ── RPC dispatch table ──────────────────────────────────────────────


def _build_rpc_table(backend: Any, transport: Any) -> dict[str, Any]:
    """Build method dispatch for RPCRequest messages."""

    async def _login(args: dict) -> dict:
        # Wrap on_status callback to push notifications
        async def _on_status(text: str) -> None:
            from ember_code.protocol import messages as msg

            await transport.send(
                msg.PushNotification(channel="login_status", payload={"text": text})
            )

        success, result = await backend.login(on_status=_on_status)
        return {"success": success, "result": result}

    async def _get_skill_definitions(args: dict) -> list[dict]:
        pool = backend.get_skill_pool()
        return [
            {"name": s.name, "description": s.description, "prompt": getattr(s, "prompt", "")}
            for s in pool.list_skills()
        ]

    return {
        # Async methods
        "ensure_mcp": lambda args: backend.ensure_mcp(),
        "mcp_connect": lambda args: backend.mcp_connect(args["server_name"]),
        "mcp_disconnect": lambda args: backend.mcp_disconnect(args["server_name"]),
        "compact_if_needed": lambda args: backend.compact_if_needed(
            args["ctx_tokens"], args["max_ctx"]
        ),
        "extract_learnings": lambda args: backend.extract_learnings(
            args["user_msg"], args["assistant_msg"]
        ),
        "login": _login,
        "fire_session_start_hook": lambda args: backend.fire_session_start_hook(),
        "auto_sync_knowledge": lambda args: backend.auto_sync_knowledge(),
        "shutdown": lambda args: backend.shutdown(),
        "get_chat_history": lambda args: backend.get_chat_history(args["session_id"]),
        "execute_scheduled_task": lambda args: backend.execute_scheduled_task(args["description"]),
        "cancel_scheduled_task": lambda args: backend.cancel_scheduled_task(args["task_id"]),
        "get_scheduled_tasks": lambda args: backend.get_scheduled_tasks(
            args.get("include_done", True)
        ),
        "list_sessions": lambda args: backend.list_sessions(),
        "switch_session": lambda args: backend.switch_session(args["session_id"]),
        # Sync accessors
        "get_processing": lambda args: backend.processing,
        "get_session_id": lambda args: backend.session_id,
        "get_run_timeout": lambda args: backend.run_timeout,
        "get_skill_names": lambda args: backend.skill_names,
        "get_mcp_status": lambda args: backend.get_mcp_status(),
        "get_mcp_server_details": lambda args: backend.get_mcp_server_details(),
        "get_mcp_servers": lambda args: backend.get_mcp_servers(),
        "get_status": lambda args: backend.get_status(),
        "switch_model": lambda args: backend.switch_model(args["model_name"]),
        "reload_cloud_credentials": lambda args: backend.reload_cloud_credentials(),
        "clear_cloud_credentials": lambda args: backend.clear_cloud_credentials(),
        "toggle_verbose": lambda args: backend.toggle_verbose(),
        "cancel_run": lambda args: backend.cancel_run(),
        "check_permission": lambda args: backend.check_permission(
            args["tool_name"], args["func_name"], args["tool_args"]
        ),
        "save_permission_rule": lambda args: backend.save_permission_rule(
            args["rule"], args["level"]
        ),
        "get_display_config": lambda args: (
            backend.settings.display.model_dump()
            if hasattr(backend.settings.display, "model_dump")
            else {}
        ),
        "get_model_registry": lambda args: {
            "default": backend.settings.models.default,
            "max_context_window": backend.settings.models.max_context_window,
            "registry": {k: v for k, v in backend.settings.models.registry.items()},
        },
        "check_for_update": lambda args: _check_update(),
        "get_skill_definitions": _get_skill_definitions,
        "start_scheduler": lambda args: None,  # handled specially
    }


# ── Main loop ──────────────────────────────────────────────────────


async def _run(
    socket_path: str,
    project_dir: Path,
    resume_session_id: str | None,
    additional_dirs: list[Path] | None = None,
) -> None:
    from ember_code.backend.server import BackendServer
    from ember_code.core.config.settings import load_settings
    from ember_code.protocol import messages as msg
    from ember_code.transport.unix_socket import UnixSocketServerTransport

    settings = load_settings(project_dir=project_dir)

    backend = BackendServer(
        settings,
        project_dir=project_dir,
        resume_session_id=resume_session_id,
        additional_dirs=additional_dirs,
    )

    transport = UnixSocketServerTransport(socket_path)
    await transport.start()

    # Signal ready to FE
    print(f"READY {socket_path}", flush=True)

    # Handle SIGTERM/SIGINT
    shutdown_event = asyncio.Event()

    def _signal_handler():
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    # Queue for message injection (replaces wire_queue_hook)
    _queue: list[str] = []
    backend.wire_queue_hook(_queue)

    # Orchestrate progress → push notification
    def _on_progress(line: str) -> None:
        asyncio.ensure_future(
            transport.send(
                msg.PushNotification(channel="orchestrate_progress", payload={"line": line})
            )
        )

    backend.wire_orchestrate_progress(_on_progress)

    rpc_table = _build_rpc_table(backend, transport)

    try:
        await transport.wait_for_connection()
        logger.info("FE connected, processing messages")

        async for message in transport.receive():
            if isinstance(message, msg.Shutdown):
                break

            if shutdown_event.is_set():
                break

            await _handle_message(message, backend, transport, rpc_table, _queue)

    except Exception as exc:
        logger.error("Backend error: %s", exc, exc_info=True)
    finally:
        await backend.shutdown()
        await transport.close()
        logger.info("Backend shut down")


async def _handle_message(
    message: Any,
    backend: Any,
    transport: Any,
    rpc_table: dict,
    queue: list[str],
) -> None:
    from ember_code.protocol import messages as msg
    from ember_code.protocol.messages import Message

    req_id = message.id or ""

    # ── Streaming: run_message ──
    if isinstance(message, msg.UserMessage):
        async for proto in backend.run_message(message.text, media=message.file_contents):
            if req_id:
                proto = proto.model_copy(update={"id": req_id})
            await transport.send(proto)
        await transport.send(msg.StreamEnd(id=req_id))

    # ── Streaming: resolve_hitl ──
    elif isinstance(message, msg.HITLResponse):
        async for proto in backend.resolve_hitl(
            message.requirement_id, message.action, message.choice
        ):
            if req_id:
                proto = proto.model_copy(update={"id": req_id})
            await transport.send(proto)
        await transport.send(msg.StreamEnd(id=req_id))

    # ── Command ──
    elif isinstance(message, msg.Command):
        result = await backend.handle_command(message.text)
        result = result.model_copy(update={"id": req_id})
        await transport.send(result)

    # ── Session management (typed messages) ──
    elif isinstance(message, msg.SessionList):
        result = await backend.list_sessions()
        result = result.model_copy(update={"id": req_id})
        await transport.send(result)

    elif isinstance(message, msg.SessionSwitch):
        result = await backend.switch_session(message.session_id)
        result = result.model_copy(update={"id": req_id})
        await transport.send(result)

    elif isinstance(message, msg.ModelSwitch):
        result = backend.switch_model(message.model_name)
        result = result.model_copy(update={"id": req_id})
        await transport.send(result)

    elif isinstance(message, msg.MCPToggle):
        result = await backend.toggle_mcp(message.server_name, message.connect)
        result = result.model_copy(update={"id": req_id})
        await transport.send(result)

    # ── Queue injection ──
    elif isinstance(message, msg.QueueMessage):
        queue.append(message.text)

    # ── Cancel ──
    elif isinstance(message, msg.Cancel):
        backend.cancel_run()

    # ── Generic RPC ──
    elif isinstance(message, msg.RPCRequest):
        handler = rpc_table.get(message.method)
        if handler is None:
            await transport.send(
                msg.RPCResponse(id=req_id, error=f"Unknown RPC method: {message.method}")
            )
            return

        try:
            result = handler(message.args)
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                result = await result

            # If result is a Message, send it directly with correlation ID
            if isinstance(result, Message):
                result = result.model_copy(update={"id": req_id})
                await transport.send(result)
            else:
                # Wrap in RPCResponse for plain values
                await transport.send(msg.RPCResponse(id=req_id, result=_serialize(result)))
        except Exception as exc:
            logger.error("RPC %s failed: %s", message.method, exc, exc_info=True)
            await transport.send(msg.RPCResponse(id=req_id, error=str(exc)))

    else:
        logger.warning("Unknown FE message type: %s", type(message).__name__)


def _serialize(value: Any) -> Any:
    """Make a value JSON-serializable."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    # Pydantic models
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


if __name__ == "__main__":
    main()
