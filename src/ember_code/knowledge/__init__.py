"""Knowledge management — ChromaDB-backed vector knowledge for agents."""

from ember_code.knowledge.embedder_registry import EmbedderRegistry
from ember_code.knowledge.manager import KnowledgeManager, setup_knowledge
from ember_code.knowledge.models import (
    KnowledgeAddResult,
    KnowledgeFilter,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeStatus,
    KnowledgeSyncResult,
)
from ember_code.knowledge.sync import KnowledgeSyncer
from ember_code.knowledge.vector_store import VectorStoreAdapter

__all__ = [
    "EmbedderRegistry",
    "KnowledgeManager",
    "setup_knowledge",
    "KnowledgeAddResult",
    "KnowledgeFilter",
    "KnowledgeSearchResponse",
    "KnowledgeSearchResult",
    "KnowledgeStatus",
    "KnowledgeSyncResult",
    "KnowledgeSyncer",
    "VectorStoreAdapter",
]
