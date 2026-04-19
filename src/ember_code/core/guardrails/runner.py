"""GuardrailRunner -- orchestrates enabled guardrails."""

from __future__ import annotations

import logging

from ember_code.core.config.settings import Settings
from ember_code.core.guardrails.base import Guardrail, GuardrailResult

logger = logging.getLogger(__name__)


class GuardrailRunner:
    """Creates and runs guardrails based on the current :class:`Settings`."""

    def __init__(self, settings: Settings) -> None:
        self._guardrails: list[Guardrail] = []
        cfg = settings.guardrails

        if cfg.pii_detection:
            from ember_code.core.guardrails.pii import PIIGuardrail

            self._guardrails.append(PIIGuardrail())

        if cfg.prompt_injection:
            from ember_code.core.guardrails.injection import PromptInjectionGuardrail

            self._guardrails.append(PromptInjectionGuardrail())

        if cfg.moderation:
            from ember_code.core.guardrails.moderation import ModerationGuardrail

            self._guardrails.append(ModerationGuardrail())

    @property
    def enabled(self) -> bool:
        """True when at least one guardrail is active."""
        return len(self._guardrails) > 0

    async def check(self, text: str) -> list[GuardrailResult]:
        """Run all enabled guardrails against *text* and return their results.

        Only results that did **not** pass are included in the returned list.
        An empty list means everything passed.
        """
        results: list[GuardrailResult] = []
        for guardrail in self._guardrails:
            try:
                result = guardrail.check(text)
                if not result.passed:
                    results.append(result)
            except Exception:
                logger.exception("Guardrail %s raised an error", guardrail.name)
        return results
