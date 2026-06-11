"""WebSocket transport — one JSON protocol message per text frame.

Serves browser-based frontends (the shared web UI used by the Tauri
app, the VSCode webview, and the JetBrains JCEF panel). Wire format
is the same JSON the Unix-socket transport uses, except WebSocket
frames already delimit messages so no newline framing is needed.

Differences from ``UnixSocketServerTransport`` that callers should
know about:

* **Reconnect-friendly.** Webviews reload (dev hot-reload, panel
  close/reopen), which drops the WS connection. ``receive()`` does
  NOT terminate on client disconnect — it keeps waiting for the
  next connection so the BE survives page reloads. The BE only
  exits via ``Shutdown``, signals, or the parent watchdog.
* **Single client.** A second concurrent connection is rejected
  with close code 1008 — the BE owns one Session and two FEs would
  race it (same reason the TUI holds one socket).
* **Loopback only by default.** Binds ``127.0.0.1``; the BE
  executes arbitrary tool calls, so it must never listen on a
  routable interface.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from ember_code.protocol.messages import Message
from ember_code.transport.base import Transport
from ember_code.transport.unix_socket import deserialize_message

logger = logging.getLogger(__name__)

# Mirror the Unix transport's frame cap — a single message can carry
# MCP tool catalogues or large tool results.
_MAX_FRAME_BYTES = 64 * 1024 * 1024


class WebSocketServerTransport(Transport):
    """BE-side transport: listens on loopback WS, serves one client at a time."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._server = None
        self._conn = None
        self._closed = False
        self._connected = asyncio.Event()
        # Incoming frames land here from the per-connection handler;
        # ``receive()`` drains it. ``None`` is the close sentinel —
        # enqueued only by ``close()``, never on client disconnect.
        self._inbox: asyncio.Queue[Message | None] = asyncio.Queue()

    @property
    def port(self) -> int:
        """The bound port — meaningful after ``start()`` (supports port=0)."""
        return self._port

    async def start(self) -> None:
        from websockets.asyncio.server import serve

        self._server = await serve(
            self._handler,
            self._host,
            self._port,
            max_size=_MAX_FRAME_BYTES,
        )
        # Resolve the real port for port=0 (auto-assign) so the ready
        # line can advertise it to the embedding shell.
        sockets = self._server.sockets or []
        if sockets:
            self._port = sockets[0].getsockname()[1]
        logger.info("BE listening on ws://%s:%d", self._host, self._port)

    async def wait_for_connection(self, timeout: float = 30.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def _handler(self, conn) -> None:
        if self._conn is not None:
            await conn.close(1008, "another client is already connected")
            return
        self._conn = conn
        self._connected.set()
        logger.info("FE connected via WebSocket")
        try:
            async for raw in conn:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                msg = deserialize_message(raw)
                if msg is not None:
                    await self._inbox.put(msg)
        except Exception as exc:
            logger.info("WS connection ended: %s", exc)
        finally:
            self._conn = None
            logger.info("FE disconnected; awaiting reconnect")

    async def send(self, message: Message) -> None:
        conn = self._conn
        if conn is None or self._closed:
            # No client attached (e.g. webview mid-reload). Events are
            # fire-and-forget; RPC callers re-issue after reconnect.
            return
        try:
            await conn.send(message.model_dump_json())
        except Exception as exc:
            logger.debug("WS send failed (client gone?): %s", exc)

    async def receive(self) -> AsyncIterator[Message]:
        while not self._closed:
            msg = await self._inbox.get()
            if msg is None:
                break
            yield msg

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._inbox.put(None)
        conn = self._conn
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def is_closed(self) -> bool:
        return self._closed
