"""Pydantic schemas for the hooks system."""

from pydantic import BaseModel, Field


class HookDefinition(BaseModel):
    """A single hook definition."""

    type: str  # "command" or "http"
    command: str = ""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    matcher: str = ""
    timeout: int = 10000
    background: bool = False  # fire-and-forget, don't block the agent


class HookResult(BaseModel):
    """Result from a hook execution."""

    should_continue: bool = True
    message: str = ""
