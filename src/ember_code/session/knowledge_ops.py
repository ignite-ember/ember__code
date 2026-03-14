"""Session knowledge operations — add, search, sync, and status."""

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
            await self.knowledge.ainsert(
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
    ) -> KnowledgeSearchResponse:
        """Search the knowledge base with optional metadata filters."""
        if self.knowledge is None:
            return KnowledgeSearchResponse(query=query)
        try:
            chroma_filters = filters.where if filters and filters.where else None
            docs = await self.knowledge.asearch(
                query=query,
                limit=limit,
                filters=chroma_filters,
            )
            results = [
                KnowledgeSearchResult(
                    content=d.content[:200] if d.content else "",
                    name=d.name or "",
                    score=d.reranking_score,
                    metadata={k: str(v) for k, v in (d.meta_data or {}).items()},
                )
                for d in docs
            ]
            return KnowledgeSearchResponse(
                query=query,
                results=results,
                total=len(results),
            )
        except Exception:
            return KnowledgeSearchResponse(query=query)

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
                col = self.knowledge.vector_db._collection
                if col:
                    count = col.count()
        except Exception:
            pass

        return KnowledgeStatus(
            enabled=True,
            collection_name=cfg.collection_name,
            document_count=count,
            embedder=cfg.embedder,
            chroma_db_path=cfg.chroma_db_path,
        )
