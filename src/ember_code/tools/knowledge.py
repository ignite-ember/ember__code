"""KnowledgeTools — lets agents search, add, and delete knowledge entries."""

import logging
from typing import TYPE_CHECKING

from agno.tools import Toolkit

if TYPE_CHECKING:
    from ember_code.session.knowledge_ops import SessionKnowledgeManager

logger = logging.getLogger(__name__)


class KnowledgeTools(Toolkit):
    """Agent-facing tools for interacting with the knowledge base.

    Agents can search for relevant context, store new knowledge,
    and remove outdated entries.
    """

    def __init__(self, knowledge_mgr: "SessionKnowledgeManager"):
        super().__init__(name="ember_knowledge")
        self._mgr = knowledge_mgr
        self.register(self.knowledge_search)
        self.register(self.knowledge_add)
        self.register(self.knowledge_delete)
        self.register(self.knowledge_status)

    def knowledge_search(self, query: str, limit: int = 5) -> str:
        """Search the knowledge base for relevant information.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return (default 5).

        Returns:
            Formatted search results, or a message if none found.
        """
        import asyncio

        async def _search():
            return await self._mgr.search(query, limit=limit)

        try:
            response = asyncio.run(_search())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(_search())

        if not response.results:
            return f"No knowledge found for: {query}"

        lines = [f"Found {response.total} result(s):"]
        for i, r in enumerate(response.results, 1):
            name = r.name or "untitled"
            lines.append(f"\n{i}. [{name}]\n{r.content}")
        return "\n".join(lines)

    def knowledge_add(
        self,
        content: str,
        source: str = "",
    ) -> str:
        """Store new knowledge in the knowledge base.

        Use this when you discover important information that should be
        remembered for future tasks — patterns, decisions, context, etc.

        Args:
            content: The knowledge content to store.
            source: Optional source description (e.g. file path, URL).

        Returns:
            Confirmation message.
        """
        import asyncio

        metadata = {"source": source} if source else None

        async def _add():
            return await self._mgr.add(text=content, metadata=metadata)

        try:
            result = asyncio.run(_add())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(_add())

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
        import asyncio

        async def _search():
            return await self._mgr.search(query, limit=10)

        try:
            response = asyncio.run(_search())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(_search())

        if not response.results:
            return f"No knowledge entries match: {query}"

        if not confirm:
            lines = [f"Found {response.total} entry/entries matching '{query}':"]
            for i, r in enumerate(response.results, 1):
                name = r.name or "untitled"
                lines.append(f"  {i}. [{name}] {r.content[:100]}")
            lines.append("\nCall knowledge_delete again with confirm=True to delete these.")
            return "\n".join(lines)

        # Actually delete
        if self._mgr.knowledge is None:
            return "Error: Knowledge base not available."

        try:
            from ember_code.knowledge.vector_store import VectorStoreAdapter

            adapter = VectorStoreAdapter(self._mgr.knowledge.vector_db)
            # Get IDs by searching ChromaDB directly
            ids_to_delete = []
            collection = adapter._get_collection()
            if collection is not None:
                results = collection.query(
                    query_texts=[query],
                    n_results=10,
                    include=[],
                )
                if results and results.get("ids"):
                    ids_to_delete = results["ids"][0]

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
