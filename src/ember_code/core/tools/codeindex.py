"""CodeIndexTools — agent-facing semantic search over the local code index.

The toolkit lazy-builds a :class:`CodeIndex` for the active project on
first call. Each tool returns a JSON string so agents can parse
structured results.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agno.tools import Toolkit

from ember_code.core.code_index.index import CodeIndex

logger = logging.getLogger(__name__)


class CodeIndexTools(Toolkit):
    """Semantic code intelligence backed by the per-commit chroma index.

    Args:
        project_dir: project root used to derive the on-disk path.
            Defaults to ``cwd``.
        data_dir: ember root, defaults to ``~/.ember``.
        index: pre-built :class:`CodeIndex` (used by tests / advanced
            callers). When provided, ``project_dir`` and ``data_dir``
            are ignored.
    """

    def __init__(
        self,
        *,
        project_dir: str | Path | None = None,
        data_dir: str | Path = "~/.ember",
        index: CodeIndex | None = None,
        **kwargs: Any,
    ):
        super().__init__(name="codeindex", **kwargs)
        self._explicit_index = index
        self._project_dir = Path(str(project_dir)) if project_dir else Path.cwd()
        self._data_dir = data_dir

        self.register(self.codeindex_search)
        self.register(self.codeindex_item)
        self.register(self.codeindex_references)
        self.register(self.codeindex_commits)

    @staticmethod
    def _json(data: Any) -> str:
        return json.dumps(data, indent=2, default=str)

    def _ensure_index(self) -> CodeIndex:
        if self._explicit_index is None:
            self._explicit_index = CodeIndex(project=self._project_dir, data_dir=self._data_dir)
        return self._explicit_index

    async def close(self) -> None:
        if self._explicit_index is not None:
            await self._explicit_index.close()

    # ── Tools ─────────────────────────────────────────────────────

    async def codeindex_search(
        self,
        query: str,
        limit: int = 20,
        commit: str = "",
    ) -> str:
        """Semantic search across the indexed codebase.

        Args:
            query: Natural-language description of what you're looking for.
            limit: Max results to return (default 20).
            commit: Optional commit SHA to query. Defaults to the indexed head.
        """
        try:
            results = await self._ensure_index().search(
                query=query, limit=limit, commit=commit or None
            )
            return self._json({"items": results, "limit": limit})
        except Exception as exc:
            logger.exception("codeindex_search failed")
            return self._json({"error": f"codeindex_search failed: {exc}"})

    async def codeindex_item(self, item_id: str, commit: str = "") -> str:
        """Get full details for an indexed item.

        Args:
            item_id: UUID of the item (from a previous search).
            commit: Optional commit SHA. Defaults to head.
        """
        try:
            result = await self._ensure_index().get_item(item_id=item_id, commit=commit or None)
            if result is None:
                return self._json({"error": "item not found"})
            return self._json(result)
        except Exception as exc:
            logger.exception("codeindex_item failed")
            return self._json({"error": f"codeindex_item failed: {exc}"})

    async def codeindex_references(self, item_id: str) -> str:
        """Get the reference graph for an item.

        Returns ``document_references`` (outgoing) and ``referenced_by``
        (incoming). References are project-scoped (not commit-scoped).
        """
        try:
            file_refs = self._ensure_index()._file_reference_service()
            edges = await file_refs.get_by_uuids(uuids=[item_id])
            outgoing = [
                {"from_id": r.from_uuid, "to_id": r.to_uuid, "tags": r.tags, "meta": r.meta}
                for r in edges
                if r.from_uuid == item_id
            ]
            incoming = [
                {"from_id": r.from_uuid, "to_id": r.to_uuid, "tags": r.tags, "meta": r.meta}
                for r in edges
                if r.to_uuid == item_id
            ]
            return self._json({"document_references": outgoing, "referenced_by": incoming})
        except Exception as exc:
            logger.exception("codeindex_references failed")
            return self._json({"error": f"codeindex_references failed: {exc}"})

    async def codeindex_commits(self) -> str:
        """List indexed commits with their last-used timestamps.

        Returns the manifest's view of which commits we have chroma
        files for. Useful for debugging the lineage / retention.
        """
        try:
            state = self._ensure_index().manifest.load()
            commits = [
                {
                    "sha": info.sha,
                    "last_used_at": info.last_used_at,
                    "branch_refs": info.branch_refs,
                    "is_head": info.sha == state.head,
                }
                for info in state.commits.values()
            ]
            commits.sort(key=lambda c: c["last_used_at"], reverse=True)
            return self._json({"head": state.head, "commits": commits})
        except Exception as exc:
            logger.exception("codeindex_commits failed")
            return self._json({"error": f"codeindex_commits failed: {exc}"})
