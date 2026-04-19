"""Base guardrail class and result model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GuardrailResult(BaseModel):
    """Result returned by a guardrail check."""

    passed: bool
    guardrail: str
    message: str
    findings: list[str] = Field(default_factory=list)


class Guardrail:
    """Base class for all guardrails.

    Subclasses must override :meth:`check` to inspect the input text
    and return a :class:`GuardrailResult`.
    """

    name: str = "base"

    def check(self, text: str) -> GuardrailResult:
        """Check *text* and return a result.  Override in subclasses."""
        return GuardrailResult(
            passed=True,
            guardrail=self.name,
            message="",
            findings=[],
        )
