"""OpenAI-compatible embedder using httpx (no openai SDK dependency).

All provider-specific values (URL, model, dimensions) are configured
in the embeddings registry (``defaults.py`` / user config) and passed
as kwargs by ``EmbedderRegistry``.
"""

import logging

import httpx
from agno.knowledge.embedder.base import Embedder

logger = logging.getLogger(__name__)


class EmberEmbedder(Embedder):
    """Embedder that calls an OpenAI-compatible /v1/embeddings endpoint via httpx.

    This avoids requiring the ``openai`` SDK as a hard dependency just for
    embeddings.  All Ember-specific defaults (URL, model, dimensions) live
    in the config registry (``defaults.py``); the ``EmbedderRegistry``
    passes them as kwargs when constructing this class.

    If you *do* have ``openai`` installed and prefer the richer client,
    use ``OpenAIEmbedder(base_url=..., api_key=..., id=model)`` directly.
    """

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    dimensions: int | None = None
    timeout: float = 30.0

    def __init__(self, **kwargs):
        super().__init__()
        # Apply our class-level defaults (base class sets its own via __init__)
        self.base_url = ""
        self.api_key = ""
        self.model = ""
        self.dimensions = None
        self.timeout = 30.0
        # Override with caller-supplied values (from EmbedderRegistry config)
        for key, value in kwargs.items():
            setattr(self, key, value)
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    @property
    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @property
    def _url(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/v1/embeddings"

    @property
    def sync_client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    @property
    def async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

    def _parse_response(self, data: dict) -> tuple[list[float], dict | None]:
        """Parse an OpenAI-compatible embeddings response."""
        embedding = data["data"][0]["embedding"]
        usage = data.get("usage")
        return embedding, usage

    # ── Sync ────────────────────────────────────────────────────────

    def get_embedding(self, text: str) -> list[float]:
        embedding, _ = self.get_embedding_and_usage(text)
        return embedding

    def get_embedding_and_usage(self, text: str) -> tuple[list[float], dict | None]:
        payload = {"input": text, "model": self.model}
        try:
            resp = self.sync_client.post(self._url, json=payload, headers=self._headers)
            resp.raise_for_status()
            return self._parse_response(resp.json())
        except Exception as exc:
            logger.debug("Sync embedding request failed: %s", exc)
            return [], None

    # ── Async ───────────────────────────────────────────────────────

    async def async_get_embedding(self, text: str) -> list[float]:
        embedding, _ = await self.async_get_embedding_and_usage(text)
        return embedding

    async def async_get_embedding_and_usage(self, text: str) -> tuple[list[float], dict | None]:
        payload = {"input": text, "model": self.model}
        try:
            resp = await self.async_client.post(self._url, json=payload, headers=self._headers)
            resp.raise_for_status()
            return self._parse_response(resp.json())
        except Exception as exc:
            logger.debug("Async embedding request failed: %s", exc)
            return [], None
