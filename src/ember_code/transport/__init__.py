"""Pluggable transport layer for BE↔FE communication.

Provides an abstract Transport interface with implementations:
- InProcessTransport: asyncio.Queue pairs (single-process, tests)
- UnixSocketTransport: Unix domain socket (multi-process, production)
"""

from ember_code.transport.base import Transport
from ember_code.transport.in_process import InProcessTransport

__all__ = ["Transport", "InProcessTransport"]
