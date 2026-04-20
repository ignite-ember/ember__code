"""Knowledge management — ChromaDB-backed vector knowledge for agents."""

from ember_code.core.knowledge.embedder_registry import EmbedderRegistry
from ember_code.core.knowledge.manager import KnowledgeManager
from ember_code.core.knowledge.models import (
    KnowledgeAddResult,
    KnowledgeFilter,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeStatus,
    KnowledgeSyncResult,
)
from ember_code.core.knowledge.sync import KnowledgeSyncer
from ember_code.core.knowledge.vector_store import VectorStoreAdapter

__all__ = [
    "EmbedderRegistry",
    "KnowledgeManager",
    "KnowledgeAddResult",
    "KnowledgeFilter",
    "KnowledgeSearchResponse",
    "KnowledgeSearchResult",
    "KnowledgeStatus",
    "KnowledgeSyncResult",
    "KnowledgeSyncer",
    "VectorStoreAdapter",
]
