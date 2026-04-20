"""Knowledge manager — sets up ChromaDB + Agno Knowledge for agents.

Creates a project-scoped ChromaDB collection and wraps it in Agno's
``Knowledge`` class so agents can ``search_knowledge=True``.

Collections are automatically scoped per project by hashing the git
remote origin URL (or the project directory path for non-git projects).
"""

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any

from ember_code.core.config.settings import KnowledgeConfig, Settings

logger = logging.getLogger(__name__)


def _resolve_collection_name(base_name: str, project_dir: Path) -> str:
    """Derive a project-scoped collection name.

    Uses the git remote origin URL when available (stable across clones
    of the same repo), falling back to the absolute project directory path.
    The result is ``<base_name>_<8-char hex hash>``.
    """
    project_id = str(project_dir)
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            project_id = result.stdout.strip()
    except Exception:
        pass

    suffix = hashlib.sha256(project_id.encode()).hexdigest()[:8]
    return f"{base_name}_{suffix}"


class KnowledgeManager:
    """Factory for Agno ``Knowledge`` instances backed by ChromaDB.

    Uses the ``EmbedderRegistry`` to resolve embedder names to Agno
    ``Embedder`` instances — supporting BYOM (Bring Your Own Model)
    for embeddings, just like ``ModelRegistry`` does for LLMs.
    """

    def __init__(self, settings: Settings, project_dir: Path | None = None):
        self.settings = settings
        self._project_dir = project_dir or Path.cwd()
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

        # Scope collection per project
        collection = _resolve_collection_name(cfg.collection_name, self._project_dir)
        logger.debug("Knowledge collection: %s", collection)

        vector_db = ChromaDb(
            collection=collection,
            embedder=embedder,
            path=db_path,
            persistent_client=True,
        )

        self._knowledge = Knowledge(
            name=collection,
            vector_db=vector_db,
            max_results=cfg.max_results,
        )
        return self._knowledge

    def _create_embedder(self, cfg: KnowledgeConfig) -> Any | None:
        """Create an embedder via the EmbedderRegistry."""
        from ember_code.core.knowledge.embedder_registry import EmbedderRegistry

        registry = EmbedderRegistry(self.settings)
        return registry.get_embedder(cfg.embedder)
