"""Tests for the WebSocket BE transport used by GUI clients."""

from __future__ import annotations

import asyncio
import json

import pytest

from ember_code.protocol import messages as msg
from ember_code.transport.websocket import WebSocketServerTransport


async def _connect(port: int):
    from websockets.asyncio.client import connect

    return await connect(f"ws://127.0.0.1:{port}")


@pytest.mark.asyncio
async def test_port_auto_assign():
    """port=0 binds an ephemeral port and exposes it via ``.port``."""
    tr = WebSocketServerTransport(port=0)
    await tr.start()
    try:
        assert tr.port > 0
    finally:
        await tr.close()


@pytest.mark.asyncio
async def test_round_trip_protocol_messages():
    """One JSON protocol message per text frame, both directions."""
    tr = WebSocketServerTransport(port=0)
    await tr.start()
    try:
        ws = await _connect(tr.port)
        await ws.send(msg.UserMessage(text="hello", id="r1").model_dump_json())

        received = None

        async def _recv_one():
            nonlocal received
            async for m in tr.receive():
                received = m
                break

        await asyncio.wait_for(_recv_one(), 5)
        assert isinstance(received, msg.UserMessage)
        assert received.text == "hello"
        assert received.id == "r1"

        await tr.send(msg.Info(text="pong"))
        raw = await asyncio.wait_for(ws.recv(), 5)
        data = json.loads(raw)
        assert data["type"] == "info"
        assert data["text"] == "pong"
        await ws.close()
    finally:
        await tr.close()


@pytest.mark.asyncio
async def test_survives_client_reconnect():
    """Client disconnect must NOT end ``receive()`` — webviews reload.

    The BE only stops on ``close()``; a reload reconnects and keeps
    talking on the same transport instance.
    """
    tr = WebSocketServerTransport(port=0)
    await tr.start()
    try:
        got: list[str] = []

        async def _drain():
            async for m in tr.receive():
                got.append(m.text)
                if len(got) >= 2:
                    break

        drain_task = asyncio.create_task(_drain())

        ws1 = await _connect(tr.port)
        await ws1.send(msg.UserMessage(text="first").model_dump_json())
        await ws1.close()

        # Wait until the server-side handler has released the slot —
        # a reconnect that races the close would be rejected as a
        # second concurrent client.
        for _ in range(100):
            if tr._conn is None and got:
                break
            await asyncio.sleep(0.02)

        ws2 = await _connect(tr.port)
        await ws2.send(msg.UserMessage(text="second").model_dump_json())

        await asyncio.wait_for(drain_task, 5)
        assert got == ["first", "second"]
        await ws2.close()
    finally:
        await tr.close()


@pytest.mark.asyncio
async def test_second_concurrent_client_rejected():
    """The BE owns one Session — a second simultaneous FE is closed
    with policy code 1008 instead of silently racing the first."""
    tr = WebSocketServerTransport(port=0)
    await tr.start()
    try:
        ws1 = await _connect(tr.port)
        # Ensure ws1's handler has claimed the slot before racing ws2.
        await asyncio.wait_for(tr.wait_for_connection(), 5)

        ws2 = await _connect(tr.port)
        from websockets.exceptions import ConnectionClosed

        with pytest.raises(ConnectionClosed) as exc_info:
            await asyncio.wait_for(ws2.recv(), 5)
        assert exc_info.value.rcvd is not None
        assert exc_info.value.rcvd.code == 1008

        # First client unaffected.
        await ws1.send(msg.UserMessage(text="still here").model_dump_json())

        async def _recv_one():
            async for m in tr.receive():
                return m

        m = await asyncio.wait_for(_recv_one(), 5)
        assert m.text == "still here"
        await ws1.close()
    finally:
        await tr.close()


@pytest.mark.asyncio
async def test_send_without_client_is_noop():
    """Events emitted while the webview is mid-reload are dropped,
    not raised — the BE must not crash because nobody is listening."""
    tr = WebSocketServerTransport(port=0)
    await tr.start()
    try:
        await tr.send(msg.Info(text="nobody listening"))  # must not raise
    finally:
        await tr.close()


@pytest.mark.asyncio
async def test_close_unblocks_receive():
    """``close()`` terminates a pending ``receive()`` iteration."""
    tr = WebSocketServerTransport(port=0)
    await tr.start()

    async def _drain():
        async for _ in tr.receive():
            pass

    task = asyncio.create_task(_drain())
    await asyncio.sleep(0.05)
    await tr.close()
    await asyncio.wait_for(task, 5)
    assert tr.is_closed
