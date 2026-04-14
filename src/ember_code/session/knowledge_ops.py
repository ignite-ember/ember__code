"""Session knowledge operations — add, search, sync, and status."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from ember_code.config.settings import Settings
from ember_code.knowledge.models import (
    KnowledgeAddResult,
    KnowledgeFilter,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeStatus,
    KnowledgeSyncResult,
)
from ember_code.knowledge.sync import KnowledgeSyncer

logger = logging.getLogger(__name__)


class SessionKnowledgeManager:
    """Manages knowledge base operations for a session."""

    def __init__(self, knowledge: Any, settings: Settings, project_dir: Path):
        self.knowledge = knowledge
        self.settings = settings
        self.project_dir = project_dir

    def share_enabled(self) -> bool:
        """Check if knowledge sharing is enabled and knowledge base is active."""
        return (
            self.settings.knowledge.enabled
            and self.settings.knowledge.share
            and self.knowledge is not None
        )

    def file_path(self) -> Path:
        """Resolve the knowledge file path relative to project root."""
        return self.project_dir / self.settings.knowledge.share_file

    async def add(
        self,
        *,
        url: str | None = None,
        path: str | None = None,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> KnowledgeAddResult:
        """Add content to the knowledge base."""
        if self.knowledge is None:
            return KnowledgeAddResult.fail(
                "Knowledge base is not enabled. Set knowledge.enabled=true in config."
            )

        if not any([url, path, text]):
            return KnowledgeAddResult.fail("Provide a url, path, or text to add.")

        try:
            # Run in thread to avoid blocking the event loop during embedding
            await asyncio.to_thread(
                self.knowledge.insert,
                url=url,
                path=path,
                text_content=text,
                metadata=metadata,
            )
            source = url or path or f"text ({len(text)} chars)"

            if self.share_enabled() and text:
                syncer = KnowledgeSyncer(self.file_path())
                entry = KnowledgeSyncer.make_entry(content=text, source=source)
                entries = syncer.load_file()
                existing_ids = {e["id"] for e in entries if "id" in e}
                if entry["id"] not in existing_ids:
                    entries.append(entry)
                    syncer.save_file(entries)

            return KnowledgeAddResult.ok(f"Added to knowledge base: {source}")
        except Exception as e:
            return KnowledgeAddResult.fail(f"Failed to add content: {e}")

    async def search(
        self,
        query: str,
        limit: int = 5,
        filters: KnowledgeFilter | None = None,
        cross_project: bool = True,
    ) -> KnowledgeSearchResponse:
        """Search the knowledge base with optional metadata filters.

        By default, searches across all project collections in the shared
        ChromaDB instance. Set ``cross_project=False`` to search only the
        current project's collection.
        """
        if self.knowledge is None:
            return KnowledgeSearchResponse(query=query)
        try:
            chroma_filters = filters.where if filters and filters.where else None

            if cross_project:
                results = await self._search_all_collections(query, limit, chroma_filters)
            else:
                results = await self._search_single(query, limit, chroma_filters)

            return KnowledgeSearchResponse(
                query=query,
                results=results,
                total=len(results),
            )
        except Exception as exc:
            logger.debug("Knowledge search failed: %s", exc)
            return KnowledgeSearchResponse(query=query)

    async def _search_single(
        self, query: str, limit: int, filters: dict | None
    ) -> list[KnowledgeSearchResult]:
        """Search the current project's collection only."""
        # Run in thread to avoid blocking during embedding
        docs = await asyncio.to_thread(
            self.knowledge.search,
            query=query,
            max_results=limit,
            filters=filters,
        )
        results = []
        for d in docs:
            meta = d.meta_data or {}
            # Resolve a readable name: prefer source URL or source field over hash
            name = (
                meta.get("_agno.source_url")
                or meta.get("url")
                or meta.get("source")
                or d.name
                or ""
            )
            content = d.content or ""
            truncated = content[:1000] + "..." if len(content) > 1000 else content
            results.append(
                KnowledgeSearchResult(
                    content=truncated,
                    name=name,
                    score=d.reranking_score,
                    metadata={k: str(v) for k, v in meta.items()},
                )
            )
        return results

    async def _search_all_collections(
        self, query: str, limit: int, filters: dict | None
    ) -> list[KnowledgeSearchResult]:
        """Search all ember_knowledge_* collections in the shared ChromaDB."""
        try:
            client = self.knowledge.vector_db.client
            collections = client.list_collections()
        except Exception:
            logger.debug("Could not list collections — falling back to single search")
            return await self._search_single(query, limit, filters)

        base_name = self.settings.knowledge.collection_name
        matching = [c for c in collections if c.name.startswith(f"{base_name}_")]

        if not matching:
            return await self._search_single(query, limit, filters)

        all_results: list[KnowledgeSearchResult] = []
        embedder = self.knowledge.vector_db.embedder

        for collection in matching:
            try:
                # Get embedding for query (in thread to avoid blocking)
                embedding = await asyncio.to_thread(embedder.get_embedding, query)
                if not embedding:
                    continue

                raw = await asyncio.to_thread(
                    collection.query,
                    query_embeddings=[embedding],
                    n_results=limit,
                    include=["documents", "metadatas", "distances"],
                )
                if not raw or not raw.get("ids") or not raw["ids"][0]:
                    continue

                for i, _doc_id in enumerate(raw["ids"][0]):
                    content = raw["documents"][0][i] if raw.get("documents") else ""
                    meta = raw["metadatas"][0][i] if raw.get("metadatas") else {}
                    distance = raw["distances"][0][i] if raw.get("distances") else None
                    score = 1.0 - distance if distance is not None else None
                    m = meta or {}
                    name = (
                        m.get("_agno.source_url")
                        or m.get("url")
                        or m.get("source")
                        or m.get("name", collection.name)
                    )
                    text = content or ""
                    truncated = text[:1000] + "..." if len(text) > 1000 else text
                    all_results.append(
                        KnowledgeSearchResult(
                            content=truncated,
                            name=name,
                            score=score,
                            metadata={
                                **{k: str(v) for k, v in m.items()},
                                "collection": collection.name,
                            },
                        )
                    )
            except Exception:
                logger.debug("Search failed for collection %s", collection.name, exc_info=True)
                continue

        # Sort by score (highest first) and trim to limit
        all_results.sort(key=lambda r: r.score or 0, reverse=True)
        return all_results[:limit]

    async def sync_from_file(self) -> KnowledgeSyncResult:
        """Sync knowledge file -> ChromaDB."""
        if not self.share_enabled():
            return KnowledgeSyncResult(
                direction="file_to_db",
                message="Knowledge sharing is not enabled.",
            )
        try:
            syncer = KnowledgeSyncer(
                file_path=self.file_path(),
                knowledge=self.knowledge,
                vector_db=self.knowledge.vector_db,
            )
            return await syncer.sync_file_to_db()
        except Exception as e:
            return KnowledgeSyncResult(direction="file_to_db", error=str(e))

    def sync_to_file(self) -> KnowledgeSyncResult:
        """Sync ChromaDB -> knowledge file."""
        if not self.share_enabled():
            return KnowledgeSyncResult(
                direction="db_to_file",
                message="Knowledge sharing is not enabled.",
            )
        try:
            syncer = KnowledgeSyncer(
                file_path=self.file_path(),
                knowledge=self.knowledge,
                vector_db=self.knowledge.vector_db,
            )
            return syncer.sync_db_to_file()
        except Exception as e:
            return KnowledgeSyncResult(direction="db_to_file", error=str(e))

    async def sync_bidirectional(self) -> list[KnowledgeSyncResult]:
        """Full bidirectional sync: file->DB then DB->file."""
        results = []
        results.append(await self.sync_from_file())
        results.append(self.sync_to_file())
        return results

    def status(self) -> KnowledgeStatus:
        """Get the current status of the knowledge base."""
        cfg = self.settings.knowledge
        if self.knowledge is None:
            return KnowledgeStatus(enabled=False)

        count = 0
        try:
            if hasattr(self.knowledge, "vector_db") and self.knowledge.vector_db:
                from ember_code.knowledge.vector_store import VectorStoreAdapter

                adapter = VectorStoreAdapter(self.knowledge.vector_db)
                count = adapter.count()
        except Exception as e:
            logger.warning("Knowledge status count failed: %s", e)

        return KnowledgeStatus(
            enabled=True,
            collection_name=cfg.collection_name,
            document_count=count,
            embedder=cfg.embedder,
            chroma_db_path=cfg.chroma_db_path,
        )
