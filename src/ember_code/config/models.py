"""Model registry — maps model names to Agno model instances."""

import logging
import os
from typing import Any

import httpx
from agno.models.openai.like import OpenAILike

from ember_code.config.settings import Settings

logger = logging.getLogger(__name__)


DEFAULT_CONTEXT_WINDOW = 128_000


class ContextWindowResolver:
    """Resolves the context window size for a model.

    Resolution order:
    1. Explicit ``context_window`` in the registry entry.
    2. Dynamic fetch from the provider's ``/models`` endpoint.
    3. Fallback to ``DEFAULT_CONTEXT_WINDOW`` (128k).
    """

    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    def resolve(self, model_id: str, entry: dict[str, Any] | None = None) -> int:
        """Return the context window size for *model_id* (synchronous)."""
        if entry and "context_window" in entry:
            return int(entry["context_window"])
        if model_id in self._cache:
            return self._cache[model_id]
        return DEFAULT_CONTEXT_WINDOW

    async def aresolve(self, model_id: str, entry: dict[str, Any] | None = None) -> int:
        """Return the context window size, with async API fallback."""
        if entry and "context_window" in entry:
            return int(entry["context_window"])
        if model_id in self._cache:
            return self._cache[model_id]

        # Try fetching from the provider's /models endpoint
        if entry and "url" in entry:
            fetched = await self._fetch_from_api(
                model_id=model_id,
                base_url=entry["url"],
                api_key=entry.get("api_key") or os.environ.get(entry.get("api_key_env", ""), ""),
            )
            if fetched:
                self._cache[model_id] = fetched
                return fetched

        return DEFAULT_CONTEXT_WINDOW

    async def _fetch_from_api(self, model_id: str, base_url: str, api_key: str = "") -> int | None:
        """Fetch context window from an OpenAI-compatible ``/models/{id}`` endpoint."""
        url = f"{base_url.rstrip('/')}/models/{model_id}"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    for key in ("context_window", "context_length", "max_model_len"):
                        if key in data:
                            return int(data[key])
        except Exception as e:
            logger.debug("Could not fetch context window for %s: %s", model_id, e)
        return None


class ModelRegistry:
    """Registry that maps model names to Agno model instances.

    All models (including Ember defaults) are defined in the config registry
    (``models.registry``). Built-in defaults ship via ``defaults.py`` and can
    be overridden by user/project config files.

    Resolution order:
    1. Config registry (defaults + user overrides)
    2. ``provider:model_id`` format (e.g., ``openai_like:gpt-4o``)
    """

    PROVIDERS: dict[str, type] = {
        "openai_like": OpenAILike,
    }

    @classmethod
    def _load_provider(cls, name: str) -> type | None:
        """Lazy-load provider classes that require optional dependencies."""
        if name == "gemini":
            try:
                from agno.models.google import Gemini

                cls.PROVIDERS["gemini"] = Gemini
                return Gemini
            except ImportError:
                return None
        return None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.context_windows = ContextWindowResolver()

    def get_model(self, name: str | None = None) -> OpenAILike:
        """Get an Agno model instance by registry name."""
        if name is None:
            name = self.settings.models.default

        entry = self._resolve_entry(name)
        if entry is None:
            raise ValueError(
                f"Unknown model: '{name}'. Add it to models.registry in your config, "
                f"or use the 'provider:model_id' format (e.g., 'openai_like:gpt-4o')."
            )

        provider_name = entry.get("provider", "openai_like")
        provider_cls = self.PROVIDERS.get(provider_name) or self._load_provider(provider_name)
        if provider_cls is None:
            raise ValueError(
                f"Unknown provider: '{provider_name}'. Available: {list(self.PROVIDERS.keys())}. "
                f"For Gemini, install: pip install google-genai"
            )

        api_key = self._resolve_api_key(entry)

        # Gemini uses its own SDK — different constructor kwargs
        if provider_name == "gemini":
            kwargs: dict[str, Any] = {"id": entry["model_id"]}
            if api_key:
                kwargs["api_key"] = api_key
            if "temperature" in entry:
                kwargs["temperature"] = entry["temperature"]
            if "max_tokens" in entry:
                kwargs["max_tokens"] = entry["max_tokens"]
            return provider_cls(**kwargs)

        # OpenAI-like providers
        kwargs = {"id": entry["model_id"]}

        if "url" in entry:
            kwargs["api_key"] = api_key or "not-set"
            kwargs["base_url"] = entry["url"]
        elif api_key:
            kwargs["api_key"] = api_key

        if "temperature" in entry:
            kwargs["temperature"] = entry["temperature"]
        if "max_tokens" in entry:
            kwargs["max_tokens"] = entry["max_tokens"]

        return provider_cls(**kwargs)

    def get_context_window(self, name: str | None = None) -> int:
        """Get the context window size for a model (synchronous)."""
        if name is None:
            name = self.settings.models.default
        entry = self._resolve_entry(name)
        model_id = entry["model_id"] if entry else name
        return self.context_windows.resolve(model_id, entry)

    async def aget_context_window(self, name: str | None = None) -> int:
        """Get the context window size, with async API fallback."""
        if name is None:
            name = self.settings.models.default
        entry = self._resolve_entry(name)
        model_id = entry["model_id"] if entry else name
        return await self.context_windows.aresolve(model_id, entry)

    def register_provider(self, name: str, cls: type) -> None:
        """Register a custom provider class."""
        self.PROVIDERS[name] = cls

    def _resolve_entry(self, name: str) -> dict[str, Any] | None:
        """Resolve a model name to a registry entry."""
        if name in self.settings.models.registry:
            return self.settings.models.registry[name]
        if ":" in name:
            provider, model_id = name.split(":", 1)
            return {"provider": provider, "model_id": model_id}
        return None

    @staticmethod
    def _resolve_api_key(entry: dict[str, Any]) -> str | None:
        """Resolve API key: direct value, env var, command, or stored credentials."""
        from ember_code.config.api_keys import resolve_api_key

        key = resolve_api_key(entry)
        if key:
            return key

        # Fall back to stored login credentials for Ember-hosted models
        if "ignite-ember.sh" in entry.get("url", ""):
            from ember_code.auth.credentials import get_access_token

            return get_access_token()

        return None
