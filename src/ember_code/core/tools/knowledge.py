"""KnowledgeTools — lets agents search, add, and delete knowledge entries."""

import logging
from typing import TYPE_CHECKING

from agno.tools import Toolkit

if TYPE_CHECKING:
    from ember_code.core.session.knowledge_ops import SessionKnowledgeManager

logger = logging.getLogger(__name__)


class KnowledgeTools(Toolkit):
    """Agent-facing tools for interacting with the knowledge base."""

    def __init__(self, knowledge_mgr: "SessionKnowledgeManager"):
        super().__init__(name="ember_knowledge")
        self._mgr = knowledge_mgr
        self.register(self.knowledge_search)
        self.register(self.knowledge_add)
        self.register(self.knowledge_delete)
        self.register(self.knowledge_status)

    async def knowledge_search(self, query: str, limit: int = 5) -> str:
        """Search the knowledge base for relevant information.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return (default 5).

        Returns:
            Formatted search results, or a message if none found.
        """
        response = await self._mgr.search(query, limit=limit)

        if not response.results:
            return f"No knowledge found for: {query}"

        lines = [f"Found {response.total} result(s):"]
        for i, r in enumerate(response.results, 1):
            name = r.name or "untitled"
            lines.append(f"\n{i}. [{name}]\n{r.content}")
        return "\n".join(lines)

    async def knowledge_add(self, content: str, source: str = "") -> str:
        """Store new knowledge in the knowledge base.

        Use this when you discover important information that should be
        remembered for future tasks — patterns, decisions, context, etc.

        Args:
            content: The knowledge content to store.
            source: Optional source description (e.g. file path, URL).

        Returns:
            Confirmation message.
        """
        metadata = {"source": source} if source else None
        result = await self._mgr.add(text=content, metadata=metadata)

        if not result.success:
            return f"Error: {result.error}"
        return result.message

    def knowledge_delete(self, query: str, confirm: bool = False) -> str:
        """Delete knowledge entries matching a search query.

        First searches for matching entries, then deletes them.
        Set confirm=True to actually delete; without it, returns
        a preview of what would be deleted.

        Args:
            query: Search query to find entries to delete.
            confirm: If True, actually delete. If False, preview only.

        Returns:
            Preview of entries or deletion confirmation.
        """
        # Delete uses sync ChromaDB API — keep sync
        if not confirm:
            return (
                f"Preview mode: to delete entries matching '{query}', "
                f"call knowledge_delete again with confirm=True."
            )

        if self._mgr.knowledge is None:
            return "Error: Knowledge base not available."

        try:
            from ember_code.core.knowledge.vector_store import VectorStoreAdapter

            adapter = VectorStoreAdapter(self._mgr.knowledge.vector_db)
            collection = adapter._get_collection()
            if collection is None:
                return "No entries found to delete."

            results = collection.query(query_texts=[query], n_results=10, include=[])
            ids_to_delete = results["ids"][0] if results and results.get("ids") else []

            if not ids_to_delete:
                return "No entries found to delete."

            deleted = adapter.delete(ids_to_delete)
            return f"Deleted {deleted} knowledge entry/entries matching '{query}'."
        except Exception as e:
            return f"Error deleting entries: {e}"

    def knowledge_status(self) -> str:
        """Check the current state of the knowledge base.

        Returns:
            Status including collection name, document count, and embedder.
        """
        status = self._mgr.status()
        if not status.enabled:
            return "Knowledge base is disabled."
        return (
            f"Knowledge base: {status.collection_name}\n"
            f"Documents: {status.document_count}\n"
            f"Embedder: {status.embedder}"
        )
