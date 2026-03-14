"""Knowledge manager — sets up ChromaDB + Agno Knowledge for agents.

Creates a project-scoped ChromaDB collection and wraps it in Agno's
``Knowledge`` class so agents can ``search_knowledge=True``.
"""

import logging
from pathlib import Path
from typing import Any

from ember_code.config.settings import KnowledgeConfig, Settings

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """Factory for Agno ``Knowledge`` instances backed by ChromaDB.

    Uses the ``EmbedderRegistry`` to resolve embedder names to Agno
    ``Embedder`` instances — supporting BYOM (Bring Your Own Model)
    for embeddings, just like ``ModelRegistry`` does for LLMs.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._knowledge: Any | None = None

    def create_knowledge(self) -> Any | None:
        """Create an Agno ``Knowledge`` with ChromaDB vector store.

        Returns ``None`` if chromadb is not installed or config is disabled.
        """
        cfg = self.settings.knowledge
        if not cfg.enabled:
            return None

        try:
            from agno.knowledge.knowledge import Knowledge
            from agno.vectordb.chroma import ChromaDb
        except ImportError:
            logger.debug("agno.knowledge or agno.vectordb.chroma not available")
            return None

        embedder = self._create_embedder(cfg)
        if embedder is None:
            logger.warning("No embedder available — knowledge disabled")
            return None

        # Resolve ChromaDB path
        db_path = str(Path(cfg.chroma_db_path).expanduser())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        vector_db = ChromaDb(
            collection=cfg.collection_name,
            embedder=embedder,
            path=db_path,
            persistent_client=True,
        )

        self._knowledge = Knowledge(
            name=cfg.collection_name,
            vector_db=vector_db,
            max_results=cfg.max_results,
        )
        return self._knowledge

    def _create_embedder(self, cfg: KnowledgeConfig) -> Any | None:
        """Create an embedder via the EmbedderRegistry."""
        from ember_code.knowledge.embedder_registry import EmbedderRegistry

        registry = EmbedderRegistry(self.settings)
        return registry.get_embedder(cfg.embedder)


def setup_knowledge(settings: Settings) -> Any | None:
    """Convenience function to create a Knowledge instance."""
    return KnowledgeManager(settings).create_knowledge()
