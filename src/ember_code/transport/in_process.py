"""In-process transport using asyncio.Queue pairs.

Used for single-process mode (current default) and testing.
No serialization overhead — messages are passed as Python objects.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ember_code.protocol.messages import Message
from ember_code.transport.base import Transport


class InProcessTransport(Transport):
    """Transport using paired asyncio.Queues within a single process.

    Create a pair with ``InProcessTransport.create_pair()`` which
    returns ``(fe_transport, be_transport)``. Messages sent on one
    side are received on the other.
    """

    def __init__(
        self, send_queue: asyncio.Queue[Message | None], recv_queue: asyncio.Queue[Message | None]
    ):
        self._send_q = send_queue
        self._recv_q = recv_queue
        self._closed = False

    @classmethod
    def create_pair(cls) -> tuple[InProcessTransport, InProcessTransport]:
        """Create a connected pair of in-process transports.

        Returns (fe_side, be_side). Messages sent on fe_side are
        received on be_side, and vice versa.
        """
        fe_to_be: asyncio.Queue[Message | None] = asyncio.Queue()
        be_to_fe: asyncio.Queue[Message | None] = asyncio.Queue()

        fe_side = cls(send_queue=fe_to_be, recv_queue=be_to_fe)
        be_side = cls(send_queue=be_to_fe, recv_queue=fe_to_be)
        return fe_side, be_side

    async def send(self, message: Message) -> None:
        """Send a message to the other side."""
        if self._closed:
            return
        await self._send_q.put(message)

    async def receive(self) -> AsyncIterator[Message]:
        """Receive messages from the other side."""
        while not self._closed:
            msg = await self._recv_q.get()
            if msg is None:
                # Shutdown signal
                break
            yield msg

    async def close(self) -> None:
        """Close the transport by sending a sentinel."""
        if self._closed:
            return
        self._closed = True
        await self._send_q.put(None)  # sentinel

    @property
    def is_closed(self) -> bool:
        return self._closed
