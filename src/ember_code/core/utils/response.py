"""Response extraction utilities."""

from typing import Any


def extract_response_text(response: Any) -> str:
    """Extract text from an Agno response object.

    Handles RunOutput, RunResponse, plain strings, and other response types
    by checking for ``content`` and ``messages`` attributes.
    """
    if isinstance(response, str):
        return response
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            return content
        return str(content)
    if hasattr(response, "messages"):
        for msg in reversed(response.messages):
            if hasattr(msg, "content") and msg.content:
                return str(msg.content)
    return str(response)
