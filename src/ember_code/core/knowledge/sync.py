"""Knowledge sync — bidirectional sync between git-friendly files and ChromaDB.

The knowledge store file (.ember/knowledge.yaml) is the git-shareable source
of truth.  ChromaDB is the runtime vector index.  This module keeps them in
sync:

    startup  →  diff file vs DB  →  embed only new entries  →  DB is current
    shutdown →  export new DB entries  →  write back to file  →  git gets them

Each entry has a stable ``id`` (content hash) so we can cheaply diff.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ember_code.core.knowledge.models import KnowledgeSyncResult
from ember_code.core.knowledge.vector_store import VectorStoreAdapter

logger = logging.getLogger(__name__)

# Default location inside the project's .ember directory
DEFAULT_KNOWLEDGE_FILE = ".ember/knowledge.yaml"


class KnowledgeSyncer:
    """Bidirectional sync between a YAML knowledge file and ChromaDB.

    Owns the file path, knowledge instance, and vector store adapter.
    All DB access goes through ``VectorStoreAdapter`` — no direct
    ChromaDB coupling.
    """

    def __init__(
        self,
        file_path: Path,
        knowledge: Any = None,
        vector_db: Any = None,
    ) -> None:
        self.file_path = file_path
        self.knowledge = knowledge
        self.store = VectorStoreAdapter(vector_db) if vector_db is not None else None

    # ── Entry factory ───────────────────────────────────────────────

    @staticmethod
    def make_entry(content: str, source: str = "") -> dict[str, Any]:
        """Create a knowledge entry dict with a stable content-hash ID."""
        return {
            "id": hashlib.sha256(content.encode()).hexdigest()[:16],
            "content": content,
            "source": source,
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ── File I/O ────────────────────────────────────────────────────

    def load_file(self) -> list[dict[str, Any]]:
        """Load entries from the knowledge YAML file."""
        if not self.file_path.exists():
            return []
        try:
            with open(self.file_path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return []
            entries = data.get("entries", [])
            return entries if isinstance(entries, list) else []
        except Exception:
            logger.warning("Failed to load knowledge file: %s", self.file_path)
            return []

    def save_file(self, entries: list[dict[str, Any]]) -> None:
        """Write entries to the knowledge YAML file."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data = {"version": 1, "synced_at": now, "entries": entries}
        with open(self.file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _get_synced_entry_ids(self) -> set[str]:
        """Get entry_id values from ChromaDB metadata for dedup."""
        if not self.store:
            return set()
        try:
            entries = self.store.get_entries_metadata()
            return {m.get("entry_id", "") for m in entries if m.get("entry_id")}
        except Exception:
            return set()

    # ── Sync ────────────────────────────────────────────────────────

    async def sync_file_to_db(self) -> KnowledgeSyncResult:
        """Sync knowledge file → ChromaDB (startup direction).

        Only creates embeddings for entries in the file that are NOT yet in the DB.
        """
        file_entries = self.load_file()
        if not file_entries:
            return KnowledgeSyncResult(
                direction="file_to_db",
                new_entries=0,
                existing_entries=0,
                total_entries=0,
            )

        # Check which YAML entries are already in ChromaDB by looking at
        # the entry_id metadata field (Agno generates its own doc IDs).
        synced_entry_ids = self._get_synced_entry_ids() if self.store else set()
        new_entries = [e for e in file_entries if e.get("id") not in synced_entry_ids]
        existing_count = len(file_entries) - len(new_entries)

        inserted = 0
        for entry in new_entries:
            try:
                metadata = {
                    "source": entry.get("source", ""),
                    "added_at": entry.get("added_at", ""),
                    "synced": "true",
                }
                # Run in thread — SentenceTransformer embedding can trigger
                # subprocess calls that crash inside Textual's fd environment.
                entry_id = entry.get(
                    "id", hashlib.sha256(entry["content"].encode()).hexdigest()[:16]
                )
                metadata["entry_id"] = entry_id
                # Name must be unique per entry so Agno generates distinct
                # content hashes (otherwise it upserts/replaces the previous).
                await asyncio.to_thread(
                    self.knowledge.insert,
                    text_content=entry["content"],
                    name=entry_id,
                    metadata=metadata,
                )
                inserted += 1
            except Exception as e:
                logger.warning("Failed to insert entry %s into ChromaDB: %s", entry.get("id"), e)

        return KnowledgeSyncResult(
            direction="file_to_db",
            new_entries=inserted,
            existing_entries=existing_count,
            total_entries=existing_count + inserted,
        )

    def sync_db_to_file(self) -> KnowledgeSyncResult:
        """Sync ChromaDB → knowledge file (shutdown direction).

        Reads all entries from the DB, merges with existing file entries,
        and writes back. New DB entries get appended.
        """
        file_entries = self.load_file()
        file_ids = {e["id"] for e in file_entries if "id" in e}

        db_entries = self.store.get_entries() if self.store else []
        new_from_db = [e for e in db_entries if e["id"] not in file_ids]

        if not new_from_db:
            return KnowledgeSyncResult(
                direction="db_to_file",
                new_entries=0,
                existing_entries=len(file_entries),
                total_entries=len(file_entries),
            )

        merged = file_entries + new_from_db
        self.save_file(merged)

        return KnowledgeSyncResult(
            direction="db_to_file",
            new_entries=len(new_from_db),
            existing_entries=len(file_entries),
            total_entries=len(merged),
        )
