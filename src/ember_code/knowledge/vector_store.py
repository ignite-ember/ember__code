"""Vector store adapter — thin abstraction over ChromaDB for knowledge sync.

Keeps ``KnowledgeSyncer`` decoupled from Chroma internals so the sync
logic only depends on this adapter interface.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VectorStoreAdapter:
    """Read-only adapter for querying entry IDs and full entries from ChromaDB.

    Wraps the Agno ``ChromaDb`` object so callers never touch
    ``vector_db._collection`` directly.
    """

    def __init__(self, vector_db: Any) -> None:
        self._vector_db = vector_db

    def _get_collection(self) -> Any | None:
        """Safely access the underlying collection."""
        try:
            collection = self._vector_db._collection
            return collection if collection is not None else None
        except AttributeError:
            return None

    def get_entry_ids(self) -> set[str]:
        """Return the set of document IDs stored in the vector DB."""
        collection = self._get_collection()
        if collection is None:
            return set()
        try:
            result = collection.get(include=[])
            return set(result["ids"]) if result and "ids" in result else set()
        except Exception:
            logger.debug("Could not read vector DB entry IDs")
            return set()

    def get_entries(self) -> list[dict[str, Any]]:
        """Return all entries with their content and metadata."""
        collection = self._get_collection()
        if collection is None:
            return []
        try:
            result = collection.get(include=["documents", "metadatas"])
            if not result or not result.get("ids"):
                return []
            entries: list[dict[str, Any]] = []
            for i, doc_id in enumerate(result["ids"]):
                meta = result["metadatas"][i] if result.get("metadatas") else {}
                content = result["documents"][i] if result.get("documents") else ""
                entries.append(
                    {
                        "id": doc_id,
                        "content": content or "",
                        "source": (meta or {}).get("source", ""),
                        "added_at": (meta or {}).get("added_at", ""),
                    }
                )
            return entries
        except Exception:
            logger.debug("Could not read vector DB entries")
            return []
