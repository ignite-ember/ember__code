"""Vector store adapter — thin abstraction over ChromaDB for knowledge sync.

Keeps ``KnowledgeSyncer`` decoupled from Chroma internals so the sync
logic only depends on this adapter interface.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VectorStoreAdapter:
    """Adapter for querying, adding, and deleting entries in ChromaDB.

    Wraps the Agno ``ChromaDb`` object so callers never touch
    ``vector_db._collection`` directly.
    """

    def __init__(self, vector_db: Any) -> None:
        self._vector_db = vector_db

    def _get_collection(self) -> Any | None:
        """Safely access the underlying collection, initializing if needed."""
        try:
            collection = self._vector_db._collection
            if collection is not None:
                return collection
            # Lazily initialize — ChromaDb doesn't create _collection until first use
            if hasattr(self._vector_db, "client") and hasattr(self._vector_db, "collection_name"):
                collection = self._vector_db.client.get_collection(
                    name=self._vector_db.collection_name
                )
                self._vector_db._collection = collection
                return collection
        except (AttributeError, Exception):
            pass
        return None

    def count(self) -> int:
        """Return the number of documents stored in the vector DB."""
        collection = self._get_collection()
        if collection is None:
            return 0
        try:
            return collection.count()
        except Exception:
            logger.debug("Could not get vector DB document count")
            return 0

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
                m = meta or {}
                # Resolve source from Agno's metadata fields
                source = (
                    m.get("source")
                    or m.get("_agno.source_url")
                    or m.get("url")
                    or m.get("name")
                    or ""
                )
                entries.append(
                    {
                        "id": doc_id,
                        "content": content or "",
                        "source": source,
                        "added_at": m.get("added_at", ""),
                    }
                )
            return entries
        except Exception:
            logger.debug("Could not read vector DB entries")
            return []

    def get_entries_metadata(self) -> list[dict[str, Any]]:
        """Return metadata dicts for all entries in the vector DB."""
        collection = self._get_collection()
        if collection is None:
            return []
        try:
            result = collection.get(include=["metadatas"])
            return result.get("metadatas", []) if result else []
        except Exception:
            logger.debug("Could not read vector DB metadata")
            return []

    def delete(self, ids: list[str]) -> int:
        """Delete documents by ID. Returns the number of IDs requested for deletion."""
        collection = self._get_collection()
        if collection is None:
            return 0
        try:
            collection.delete(ids=ids)
            return len(ids)
        except Exception:
            logger.debug("Could not delete vector DB entries")
            return 0
