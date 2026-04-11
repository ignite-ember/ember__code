"""Embedder registry — resolves embedder names to Agno Embedder instances.

Default: ``local`` — uses SentenceTransformer (all-MiniLM-L6-v2) for
fully offline, no-API-key-needed embeddings.
"""

import logging

from agno.knowledge.embedder.base import Embedder

from ember_code.config.settings import Settings

logger = logging.getLogger(__name__)


class EmbedderRegistry:
    """Registry that maps embedder names to Agno ``Embedder`` instances."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_embedder(self, name: str | None = None) -> Embedder | None:
        """Get an Agno Embedder instance by name. Returns None if unavailable."""
        if name is None:
            name = self.settings.embeddings.default

        if name == "local":
            return self._create_local_embedder()

        # Check custom registry
        entry = self.settings.embeddings.registry.get(name)
        if entry:
            provider = entry.get("provider", "local")
            if provider == "local":
                return self._create_local_embedder(entry.get("model_id"))

        logger.warning("Unknown embedder: '%s'. Using local default.", name)
        return self._create_local_embedder()

    @staticmethod
    def _create_local_embedder(model_id: str | None = None) -> Embedder | None:
        """Create a local SentenceTransformer embedder."""
        try:
            import os
            import warnings

            # Prevent subprocess/multiprocessing calls that crash inside
            # Textual's restricted fd environment ("bad value(s) in fds_to_keep").
            os.environ.setdefault("TQDM_DISABLE", "1")
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            os.environ.setdefault("OMP_NUM_THREADS", "1")
            # Suppress HuggingFace Hub "unauthenticated requests" warning
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

            from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder

            # Suppress HF Hub and sentence-transformers log noise
            _hf_logger = logging.getLogger("huggingface_hub")
            _st_logger = logging.getLogger("sentence_transformers")
            _prev_hf = _hf_logger.level
            _prev_st = _st_logger.level
            _hf_logger.setLevel(logging.ERROR)
            _st_logger.setLevel(logging.ERROR)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    embedder = SentenceTransformerEmbedder(id=model_id or "all-MiniLM-L6-v2")
            finally:
                _hf_logger.setLevel(_prev_hf)
                _st_logger.setLevel(_prev_st)

            return embedder
        except ImportError:
            logger.warning("sentence-transformers not installed — knowledge disabled")
            return None
