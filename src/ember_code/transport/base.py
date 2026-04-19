"""Abstract transport interface for BE↔FE communication."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ember_code.protocol.messages import Message


class Transport(ABC):
    """Bidirectional message transport between backend and frontend.

    Implementations must handle serialization/deserialization of
    protocol messages to/from the underlying medium.
    """

    @abstractmethod
    async def send(self, message: Message) -> None:
        """Send a protocol message to the other side."""

    @abstractmethod
    def receive(self) -> AsyncIterator[Message]:
        """Receive protocol messages from the other side.

        Returns an async iterator that yields messages as they arrive.
        Raises StopAsyncIteration when the connection is closed.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the transport gracefully."""

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """Whether the transport has been closed."""
