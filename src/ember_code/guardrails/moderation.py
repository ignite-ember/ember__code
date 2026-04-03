"""Moderation guardrail stub (placeholder for OpenAI moderation API)."""

from __future__ import annotations

from ember_code.guardrails.base import Guardrail, GuardrailResult


class ModerationGuardrail(Guardrail):
    """Placeholder moderation guardrail.

    Always passes through.  Replace with an actual call to the
    OpenAI Moderation API (or similar) when ready.
    """

    name: str = "moderation"

    def check(self, text: str) -> GuardrailResult:
        return GuardrailResult(
            passed=True,
            guardrail=self.name,
            message="Moderation check passed (stub).",
            findings=[],
        )
