"""Protocol messages for BE↔FE communication.

All messages are Pydantic models serializable to JSON.
The FE has zero Agno imports — all Agno-specific logic
stays in the BE's serializer.
"""

from ember_code.protocol.messages import *  # noqa: F401,F403
