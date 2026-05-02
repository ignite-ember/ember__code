"""Per-project, per-commit code index backed by ChromaDB.

Each commit gets its own ``<sha>.chroma/`` directory under
``~/.ember/projects/<project_id>/code_index/``. Indexing a new commit
copies the parent commit's directory in place, then applies the diff
on top — so each commit is fully self-contained but only the changed
files re-embed.

Lifecycle:

- :meth:`prepare_commit` — copy parent → child (or create empty), update manifest.
- :meth:`apply_delta` — apply a JSONL of file-level changes (contract pending).
- :meth:`set_head` — point the manifest's ``head`` at a commit.
- :meth:`search` / :meth:`get_item` — query a commit (defaults to head).
- :meth:`prune` — drop commits not referenced by any branch and idle > N days.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document

from ember_code.core.code_index.manifest import Manifest
from ember_code.core.code_index.paths import (
    commit_chroma_path,
)
from ember_code.core.code_index.project import resolve_project_id
from ember_code.core.code_index.schema.items import CodeIndexItem
from ember_code.core.embeddings import EmbeddingFunction

logger = logging.getLogger(__name__)

DOCUMENTS_COLLECTION = "code_index_documents"
CHUNKS_COLLECTION = "code_index_chunks"

# ASCII unit separator — used to encode list metadata (tags, hierarchy)
# into chromadb's flat-scalar metadata model.
_LIST_SEP = "\x1f"


class CommitNotFoundError(Exception):
    """Raised when a commit's chroma directory doesn't exist."""

    def __init__(self, sha: str):
        super().__init__(f"No chroma index found for commit {sha}")
        self.sha = sha


class CodeIndex:
    """Per-project, per-commit code index.

    Args:
        project: project directory (used to derive the on-disk path).
        data_dir: ember root, defaults to ``~/.ember``.
        chunker: how to split file content for chunk-level embeddings.
            Default ``RecursiveChunking(chunk_size=800, overlap=100)`` —
            sized for the 384-dim ``all-MiniLM-L6-v2`` embedder.
    """

    def __init__(
        self,
        *,
        project: str | Path,
        data_dir: str | Path = "~/.ember",
        chunker: ChunkingStrategy | None = None,
    ):
        self.project = project
        self.project_id = resolve_project_id(project)
        self.data_dir = data_dir
        self.chunker = chunker or RecursiveChunking(chunk_size=800, overlap=100)
        self.manifest = Manifest(project=project, data_dir=data_dir)
        # Per-(commit_sha) ChromaDB clients; opened lazily, reused.
        self._clients: dict[str, Any] = {}
        self._file_refs: Any | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Drop all cached chromadb clients. Persistent data stays on disk."""
        async with self._lock:
            self._clients.clear()

    # -- Commit lifecycle ------------------------------------------------------

    async def prepare_commit(
        self,
        sha: str,
        *,
        parent_sha: str | None = None,
    ) -> Path:
        """Ensure ``<sha>.chroma/`` exists; copy from ``parent_sha`` if provided.

        Idempotent — if the target already exists, this just updates the
        manifest's ``last_used_at``. Returns the chroma directory path.
        """
        target = commit_chroma_path(self.project, sha, data_dir=self.data_dir)
        if target.exists():
            self.manifest.touch(sha)
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        if parent_sha:
            parent = commit_chroma_path(self.project, parent_sha, data_dir=self.data_dir)
            if parent.exists():
                await asyncio.to_thread(shutil.copytree, str(parent), str(target))
            else:
                logger.warning(
                    "parent commit %s missing; creating empty chroma for %s",
                    parent_sha,
                    sha,
                )
                target.mkdir()
        else:
            target.mkdir()
        self.manifest.upsert_commit(sha)
        return target

    async def apply_delta(self, jsonl_path: str | Path):
        """Apply a producer-emitted JSONL changeset to this project.

        The JSONL's first line is the ``commit`` header — the applier
        prepares ``<sha>.chroma/`` (copy-on-write from parent if any),
        replays each item/reference op, then sets head. See
        :mod:`ember_code.core.code_index.delta` for the on-the-wire
        contract.
        """
        from ember_code.core.code_index.delta import apply_delta

        return await apply_delta(
            index=self,
            file_refs=self._file_reference_service(),
            jsonl_path=jsonl_path,
        )

    def _file_reference_service(self):
        """Lazily build a ``FileReferenceService`` against the per-project SQLite."""
        if self._file_refs is None:
            from ember_code.core.code_index.paths import state_db_path
            from ember_code.core.code_index.pg.file_reference import FileReferenceService
            from ember_code.core.db.database import Database

            db = Database(state_db_path(self.project, data_dir=self.data_dir))
            self._file_refs = FileReferenceService(db)
        return self._file_refs

    async def set_head(self, sha: str) -> None:
        self.manifest.set_head(sha)

    def head(self) -> str | None:
        return self.manifest.load().head

    # -- Indexing --------------------------------------------------------------

    async def add_item(self, sha: str, item: CodeIndexItem) -> None:
        """Insert/replace an item + its chunks in ``<sha>.chroma/``."""
        await self.prepare_commit(sha)
        docs, chunks = await self._collections(sha)

        document_text = item.content or ""
        doc_metadata = _flatten_item_metadata(item)
        await asyncio.to_thread(
            docs.upsert,
            ids=[item.item_id],
            documents=[document_text],
            metadatas=[doc_metadata],
        )

        # Replace the chunk set for this item.
        await asyncio.to_thread(chunks.delete, where={"parent_doc_id": item.item_id})
        chunk_texts = self._chunk_text(document_text)
        if chunk_texts:
            chunk_ids = [f"{item.item_id}::{i}" for i in range(len(chunk_texts))]
            chunk_metadatas = [
                {
                    "parent_doc_id": item.item_id,
                    "chunk_index": i,
                    "name": item.name or "",
                    "type": item.type.value if hasattr(item.type, "value") else str(item.type),
                    "path": item.path or "",
                    "file_extension": item.file_extension or "",
                    "repository_id": item.repository_id or "",
                }
                for i in range(len(chunk_texts))
            ]
            await asyncio.to_thread(
                chunks.upsert,
                ids=chunk_ids,
                documents=chunk_texts,
                metadatas=chunk_metadatas,
            )
        self.manifest.touch(sha)

    async def remove_item(self, sha: str, item_id: str) -> None:
        """Drop an item and all its chunks from ``<sha>.chroma/``."""
        if not commit_chroma_path(self.project, sha, data_dir=self.data_dir).exists():
            return
        docs, chunks = await self._collections(sha)
        await asyncio.to_thread(docs.delete, ids=[item_id])
        await asyncio.to_thread(chunks.delete, where={"parent_doc_id": item_id})
        self.manifest.touch(sha)

    # -- Reads -----------------------------------------------------------------

    async def search(
        self,
        *,
        query: str,
        limit: int = 20,
        commit: str | None = None,
    ) -> list[dict]:
        """Semantic search inside one commit's index.

        ``commit`` defaults to the manifest's head. Returns parent items
        with the best-matching chunk preview, scored by cosine similarity.
        """
        sha = commit or self.head()
        if sha is None:
            return []
        chroma_dir = commit_chroma_path(self.project, sha, data_dir=self.data_dir)
        if not chroma_dir.exists():
            return []

        docs, chunks = await self._collections(sha)
        if await asyncio.to_thread(chunks.count) == 0:
            return []
        n = max(limit * 4, limit)
        result = await asyncio.to_thread(
            chunks.query,
            query_texts=[query],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        chunk_docs = (result.get("documents") or [[]])[0]
        chunk_metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        if not ids:
            return []

        best: dict[str, dict] = {}
        for chunk_id, doc_text, meta, dist in zip(
            ids, chunk_docs, chunk_metas, dists, strict=False
        ):
            parent_id = (meta or {}).get("parent_doc_id")
            if not parent_id:
                continue
            score = 1.0 - float(dist) if dist is not None else 0.0
            current = best.get(parent_id)
            if current is None or score > current["score"]:
                best[parent_id] = {
                    "score": score,
                    "chunk": doc_text or "",
                    "chunk_id": chunk_id,
                }

        if not best:
            return []

        parent_ids = list(best.keys())
        parents = await asyncio.to_thread(
            docs.get, ids=parent_ids, include=["documents", "metadatas"]
        )
        parent_rows = {
            pid: (text or "", meta or {})
            for pid, text, meta in zip(
                parents.get("ids", []) or [],
                parents.get("documents", []) or [],
                parents.get("metadatas", []) or [],
                strict=False,
            )
        }

        out = []
        for parent_id, entry in best.items():
            content_text, parent_meta = parent_rows.get(parent_id, ("", {}))
            preview = entry["chunk"]
            truncated = preview[:1000] + "..." if len(preview) > 1000 else preview
            out.append(
                {
                    "item_id": parent_id,
                    "name": parent_meta.get("name", ""),
                    "type": parent_meta.get("type", ""),
                    "path": parent_meta.get("path", ""),
                    "file_extension": parent_meta.get("file_extension", ""),
                    "repository_id": parent_meta.get("repository_id", ""),
                    "tags": _decode_list(parent_meta.get("tags", "")),
                    "score": entry["score"],
                    "chunk_preview": truncated,
                    "content": content_text,
                    "commit": sha,
                }
            )
        out.sort(key=lambda r: r["score"], reverse=True)
        self.manifest.touch(sha)
        return out[:limit]

    async def get_item(
        self,
        item_id: str,
        *,
        commit: str | None = None,
    ) -> dict | None:
        sha = commit or self.head()
        if sha is None:
            return None
        chroma_dir = commit_chroma_path(self.project, sha, data_dir=self.data_dir)
        if not chroma_dir.exists():
            return None
        docs, _ = await self._collections(sha)
        page = await asyncio.to_thread(docs.get, ids=[item_id], include=["documents", "metadatas"])
        ids = page.get("ids") or []
        if not ids:
            return None
        text = (page.get("documents") or [""])[0]
        meta = (page.get("metadatas") or [{}])[0]
        self.manifest.touch(sha)
        return {
            "item_id": ids[0],
            "name": meta.get("name", ""),
            "type": meta.get("type", ""),
            "path": meta.get("path", ""),
            "file_extension": meta.get("file_extension", ""),
            "repository_id": meta.get("repository_id", ""),
            "tags": _decode_list(meta.get("tags", "")),
            "parent_id": meta.get("parent_id", ""),
            "parent_ids_hierarchy": _decode_list(meta.get("parent_ids_hierarchy", "")),
            "source_documents_ids": _decode_list(meta.get("source_documents_ids", "")),
            "archived": bool(meta.get("archived", False)),
            "timestamp": meta.get("timestamp", ""),
            "token_count": int(meta.get("token_count", 0) or 0),
            "content": text,
            "commit": sha,
        }

    # -- Retention -------------------------------------------------------------

    async def prune(
        self,
        *,
        keep_recent_days: int = 30,
    ) -> list[str]:
        """Drop commits not on a branch and idle longer than ``keep_recent_days``.

        Returns the list of dropped commit SHAs. The manifest's ``head``
        is always preserved if it still has a chroma dir.
        """
        # Refresh branch_refs from git so retention has fresh data.
        branch_map = _branch_heads(self.project)
        per_commit_branches: dict[str, list[str]] = {}
        for branch, sha in branch_map.items():
            per_commit_branches.setdefault(sha, []).append(branch)
        self.manifest.update_branch_refs(per_commit_branches)

        state = self.manifest.load()
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_recent_days)
        to_drop: list[str] = []
        for sha, info in state.commits.items():
            if sha == state.head:
                continue
            if info.branch_refs:
                continue
            try:
                last_used = datetime.fromisoformat(info.last_used_at)
            except ValueError:
                last_used = datetime.now(timezone.utc)
            if last_used < cutoff:
                to_drop.append(sha)

        for sha in to_drop:
            chroma_dir = commit_chroma_path(self.project, sha, data_dir=self.data_dir)
            if chroma_dir.exists():
                await asyncio.to_thread(shutil.rmtree, str(chroma_dir))
            self._clients.pop(sha, None)
            self.manifest.remove_commit(sha)
        return to_drop

    # -- Internal --------------------------------------------------------------

    async def _collections(self, sha: str) -> tuple[Any, Any]:
        client = await self._client_for(sha)
        docs = await asyncio.to_thread(_get_or_create_collection, client, DOCUMENTS_COLLECTION)
        chunks = await asyncio.to_thread(_get_or_create_collection, client, CHUNKS_COLLECTION)
        return docs, chunks

    async def _client_for(self, sha: str) -> Any:
        if sha in self._clients:
            return self._clients[sha]
        path = commit_chroma_path(self.project, sha, data_dir=self.data_dir)
        path.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            if sha not in self._clients:
                self._clients[sha] = await asyncio.to_thread(_open_client, path)
            return self._clients[sha]

    def _chunk_text(self, content: str) -> list[str]:
        if not content:
            return []
        chunks = self.chunker.chunk(Document(content=content))
        return [c.content for c in chunks if c.content]


# -- Helpers ------------------------------------------------------------------


def _open_client(path: Path) -> Any:
    import chromadb

    return chromadb.PersistentClient(path=str(path))


def _get_or_create_collection(client: Any, name: str) -> Any:
    return client.get_or_create_collection(name=name, embedding_function=EmbeddingFunction())


def _branch_heads(project: str | Path) -> dict[str, str]:
    """Return ``{branch_name: head_sha}`` for every local branch.

    Empty dict when the project isn't a git repo.
    """
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/"],
            capture_output=True,
            text=True,
            cwd=str(project),
            timeout=5,
        )
    except Exception as exc:
        logger.debug("git for-each-ref failed: %s", exc)
        return {}
    if result.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            branch, sha = parts
            out[branch] = sha
    return out


def _flatten_item_metadata(item: CodeIndexItem) -> dict[str, Any]:
    """Pack a :class:`CodeIndexItem`'s fields into chromadb-friendly metadata.

    ChromaDB only allows scalar metadata values, so list fields
    (``tags``, ``parent_ids_hierarchy``, ``source_documents_ids``) are
    encoded with the ASCII unit separator (``\\x1f``) and decoded on
    read via :func:`_decode_list`.
    """
    return {
        "name": item.name or "",
        "type": item.type.value if hasattr(item.type, "value") else str(item.type),
        "parent_id": item.parent_id or "",
        "parent_ids_hierarchy": _encode_list(item.parent_ids_hierarchy or []),
        "tags": _encode_list(item.tags or []),
        "source_documents_ids": _encode_list(item.source_documents_ids or []),
        "file_extension": item.file_extension or "",
        "repository_id": item.repository_id or "",
        "path": item.path or "",
        "archived": bool(getattr(item, "archived", False)),
        "timestamp": item.timestamp or "",
        "token_count": int(item.token_count or 0),
    }


def _encode_list(values: Iterable[str]) -> str:
    return _LIST_SEP.join(str(v) for v in values if v)


def _decode_list(encoded: str) -> list[str]:
    if not encoded:
        return []
    return [part for part in str(encoded).split(_LIST_SEP) if part]
