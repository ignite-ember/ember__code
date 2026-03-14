"""Embedder registry — maps embedder names to Agno Embedder instances.

Follows the same BYOM pattern as ModelRegistry: all embedders (including
Ember defaults) are defined in the config registry. Built-in defaults
ship via ``defaults.py`` and can be overridden by user/project config.

Resolution order:
1. Config registry (defaults + user overrides)
2. ``provider:model_id`` format (e.g., ``openai:text-embedding-3-small``)
"""

import logging
import os
import subprocess
from typing import Any

from agno.knowledge.embedder.base import Embedder

from ember_code.config.settings import Settings

logger = logging.getLogger(__name__)


class EmbedderRegistry:
    """Registry that maps embedder names to Agno ``Embedder`` instances.

    All embedders (including Ember defaults) are defined in the config
    registry. Built-in defaults ship via ``defaults.py``.

    Resolution order:
    1. Config registry (defaults + user overrides)
    2. ``provider:model_id`` format (e.g., ``openai:text-embedding-3-small``)
    """

    PROVIDERS: dict[str, str] = {
        "openai_compatible": "openai_compatible",
        "openai": "openai",
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_embedder(self, name: str | None = None) -> Embedder | None:
        """Get an Agno Embedder instance by registry name.

        Returns ``None`` if the embedder cannot be created.
        """
        if name is None:
            name = self.settings.embeddings.default

        entry = self._resolve_entry(name)
        if entry is None:
            logger.warning(
                "Unknown embedder: '%s'. Add it to embeddings.registry in your "
                "config, or use 'provider:model_id' format.",
                name,
            )
            return None

        provider = entry.get("provider", "openai_compatible")
        api_key = self._resolve_api_key(entry)

        if provider == "openai":
            return self._create_openai_embedder(entry, api_key)

        # Default: openai_compatible — uses EmberEmbedder (httpx-based)
        return self._create_openai_compatible_embedder(entry, api_key)

    def _resolve_entry(self, name: str) -> dict[str, Any] | None:
        """Resolve an embedder name to a registry entry."""
        if name in self.settings.embeddings.registry:
            return self.settings.embeddings.registry[name]
        if ":" in name:
            provider, model_id = name.split(":", 1)
            return {"provider": provider, "model_id": model_id}
        return None

    @staticmethod
    def _resolve_api_key(entry: dict[str, Any]) -> str | None:
        """Resolve API key from env var or command."""
        if "api_key_env" in entry:
            return os.environ.get(entry["api_key_env"])
        if "api_key_cmd" in entry:
            result = subprocess.run(
                entry["api_key_cmd"], shell=True, capture_output=True, text=True
            )
            return result.stdout.strip() if result.returncode == 0 else None
        return None

    def _create_openai_compatible_embedder(
        self, entry: dict[str, Any], api_key: str | None
    ) -> Embedder | None:
        """Create an EmberEmbedder (OpenAI-compatible endpoint via httpx)."""
        from ember_code.knowledge.embedder import EmberEmbedder

        kwargs: dict[str, Any] = {}
        if "url" in entry:
            kwargs["base_url"] = entry["url"]
        if api_key:
            kwargs["api_key"] = api_key
        if "model_id" in entry:
            kwargs["model"] = entry["model_id"]
        if "dimensions" in entry:
            kwargs["dimensions"] = entry["dimensions"]

        return EmberEmbedder(**kwargs)

    def _create_openai_embedder(
        self, entry: dict[str, Any], api_key: str | None
    ) -> Embedder | None:
        """Create an OpenAI native embedder via Agno."""
        try:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            kwargs: dict[str, Any] = {
                "id": entry.get("model_id", "text-embedding-3-small"),
            }
            if api_key:
                kwargs["api_key"] = api_key
            if "dimensions" in entry:
                kwargs["dimensions"] = entry["dimensions"]

            return OpenAIEmbedder(**kwargs)
        except ImportError:
            logger.debug("openai package not available for OpenAIEmbedder")
            return None
