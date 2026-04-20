"""Tests for knowledge sync — bidirectional sync between YAML files and ChromaDB."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from ember_code.core.config.settings import KnowledgeConfig, Settings
from ember_code.core.knowledge.models import KnowledgeSyncResult
from ember_code.core.knowledge.sync import KnowledgeSyncer
from ember_code.core.knowledge.vector_store import VectorStoreAdapter

# ── Helpers ─────────────────────────────────────────────────────────


class FakeCollection:
    """Minimal fake ChromaDB collection for testing."""

    def __init__(self, ids=None, documents=None, metadatas=None):
        self._ids = ids or []
        self._documents = documents or []
        self._metadatas = metadatas or []

    def get(self, include=None):
        result = {"ids": self._ids}
        if include and "documents" in include:
            result["documents"] = self._documents
        if include and "metadatas" in include:
            result["metadatas"] = self._metadatas
        return result

    def count(self):
        return len(self._ids)


class FakeVectorDb:
    def __init__(self, collection=None):
        self._collection = collection


def _syncer(tmp_path, knowledge=None, vector_db=None):
    """Create a KnowledgeSyncer with a temp file path."""
    return KnowledgeSyncer(
        file_path=tmp_path / "knowledge.yaml",
        knowledge=knowledge,
        vector_db=vector_db,
    )


# ── make_entry ──────────────────────────────────────────────────────


class TestMakeEntry:
    def test_creates_entry_with_id(self):
        entry = KnowledgeSyncer.make_entry("some content", source="test.md")
        assert len(entry["id"]) == 16
        assert entry["content"] == "some content"
        assert entry["source"] == "test.md"
        assert "added_at" in entry

    def test_deterministic_id(self):
        e1 = KnowledgeSyncer.make_entry("hello")
        e2 = KnowledgeSyncer.make_entry("hello")
        assert e1["id"] == e2["id"]

    def test_different_content_different_id(self):
        e1 = KnowledgeSyncer.make_entry("hello")
        e2 = KnowledgeSyncer.make_entry("world")
        assert e1["id"] != e2["id"]

    def test_default_source_empty(self):
        entry = KnowledgeSyncer.make_entry("content")
        assert entry["source"] == ""

    def test_id_is_hex(self):
        entry = KnowledgeSyncer.make_entry("test")
        assert all(c in "0123456789abcdef" for c in entry["id"])


# ── KnowledgeSyncResult ────────────────────────────────────────────


class TestKnowledgeSyncResult:
    def test_summary_in_sync(self):
        r = KnowledgeSyncResult(
            direction="file_to_db",
            new_entries=0,
            existing_entries=5,
            total_entries=5,
        )
        assert "Already in sync" in r.summary
        assert "5" in r.summary

    def test_summary_with_new(self):
        r = KnowledgeSyncResult(
            direction="file_to_db",
            new_entries=3,
            existing_entries=5,
            total_entries=8,
        )
        assert "3 new" in r.summary
        assert "5 existing" in r.summary

    def test_summary_with_error(self):
        r = KnowledgeSyncResult(error="boom")
        assert "boom" in r.summary


# ── VectorStoreAdapter ──────────────────────────────────────────────


class TestVectorStoreAdapter:
    def test_get_entry_ids(self):
        col = FakeCollection(ids=["x", "y", "z"])
        adapter = VectorStoreAdapter(FakeVectorDb(col))
        assert adapter.get_entry_ids() == {"x", "y", "z"}

    def test_get_entry_ids_none_collection(self):
        adapter = VectorStoreAdapter(FakeVectorDb(collection=None))
        assert adapter.get_entry_ids() == set()

    def test_get_entry_ids_empty(self):
        adapter = VectorStoreAdapter(FakeVectorDb(FakeCollection(ids=[])))
        assert adapter.get_entry_ids() == set()

    def test_get_entries(self):
        col = FakeCollection(
            ids=["a", "b"],
            documents=["content a", "content b"],
            metadatas=[{"source": "src_a"}, {"source": "src_b"}],
        )
        adapter = VectorStoreAdapter(FakeVectorDb(col))
        entries = adapter.get_entries()
        assert len(entries) == 2
        assert entries[0]["id"] == "a"
        assert entries[0]["content"] == "content a"
        assert entries[0]["source"] == "src_a"

    def test_get_entries_none_collection(self):
        adapter = VectorStoreAdapter(FakeVectorDb(collection=None))
        assert adapter.get_entries() == []


# ── File I/O ────────────────────────────────────────────────────────


class TestLoadFile:
    def test_nonexistent_file(self, tmp_path):
        syncer = _syncer(tmp_path)
        syncer.file_path = tmp_path / "nope.yaml"
        assert syncer.load_file() == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "knowledge.yaml"
        f.write_text("")
        syncer = _syncer(tmp_path)
        assert syncer.load_file() == []

    def test_valid_file(self, tmp_path):
        f = tmp_path / "knowledge.yaml"
        data = {
            "version": 1,
            "entries": [
                {"id": "abc123", "content": "hello", "source": "test", "added_at": "2026-01-01"},
            ],
        }
        f.write_text(yaml.dump(data))
        syncer = _syncer(tmp_path)
        result = syncer.load_file()
        assert len(result) == 1
        assert result[0]["id"] == "abc123"
        assert result[0]["content"] == "hello"

    def test_invalid_yaml(self, tmp_path):
        f = tmp_path / "knowledge.yaml"
        f.write_text(":::invalid:::")
        syncer = _syncer(tmp_path)
        assert syncer.load_file() == []

    def test_non_dict_yaml(self, tmp_path):
        f = tmp_path / "knowledge.yaml"
        f.write_text("- item1\n- item2\n")
        syncer = _syncer(tmp_path)
        assert syncer.load_file() == []


class TestSaveFile:
    def test_creates_file(self, tmp_path):
        syncer = KnowledgeSyncer(file_path=tmp_path / "sub" / "knowledge.yaml")
        syncer.save_file([{"id": "abc", "content": "hello"}])
        assert syncer.file_path.exists()

        data = yaml.safe_load(syncer.file_path.read_text())
        assert data["version"] == 1
        assert "synced_at" in data
        assert len(data["entries"]) == 1
        assert data["entries"][0]["id"] == "abc"

    def test_overwrites_existing(self, tmp_path):
        syncer = _syncer(tmp_path)
        syncer.save_file([{"id": "a"}])
        syncer.save_file([{"id": "b"}])
        data = yaml.safe_load(syncer.file_path.read_text())
        assert len(data["entries"]) == 1
        assert data["entries"][0]["id"] == "b"


class TestRoundTrip:
    def test_save_and_load(self, tmp_path):
        syncer = _syncer(tmp_path)
        entries = [
            KnowledgeSyncer.make_entry("first entry", source="a.md"),
            KnowledgeSyncer.make_entry("second entry", source="b.md"),
        ]
        syncer.save_file(entries)
        loaded = syncer.load_file()
        assert len(loaded) == 2
        assert loaded[0]["content"] == "first entry"
        assert loaded[1]["source"] == "b.md"


# ── sync_file_to_db ────────────────────────────────────────────────


class TestSyncFileToDb:
    @pytest.mark.asyncio
    async def test_empty_file(self, tmp_path):
        syncer = _syncer(tmp_path, knowledge=MagicMock(), vector_db=FakeVectorDb(FakeCollection()))
        result = await syncer.sync_file_to_db()
        assert result.new_entries == 0
        assert result.total_entries == 0

    @pytest.mark.asyncio
    async def test_all_new(self, tmp_path):
        entries = [KnowledgeSyncer.make_entry("hello"), KnowledgeSyncer.make_entry("world")]
        knowledge = AsyncMock()
        syncer = _syncer(
            tmp_path, knowledge=knowledge, vector_db=FakeVectorDb(FakeCollection(ids=[]))
        )
        syncer.save_file(entries)

        result = await syncer.sync_file_to_db()
        assert result.new_entries == 2
        assert result.existing_entries == 0
        assert result.total_entries == 2
        assert knowledge.insert.call_count == 2

    @pytest.mark.asyncio
    async def test_some_existing(self, tmp_path):
        e1 = KnowledgeSyncer.make_entry("hello")
        e2 = KnowledgeSyncer.make_entry("world")
        knowledge = AsyncMock()
        # Simulate e1 already synced (entry_id in metadata)
        syncer = _syncer(
            tmp_path,
            knowledge=knowledge,
            vector_db=FakeVectorDb(
                FakeCollection(
                    ids=["agno-uuid-1"],
                    metadatas=[{"entry_id": e1["id"]}],
                )
            ),
        )
        syncer.save_file([e1, e2])

        result = await syncer.sync_file_to_db()
        assert result.new_entries == 1
        assert result.existing_entries == 1
        assert knowledge.insert.call_count == 1

    @pytest.mark.asyncio
    async def test_all_existing(self, tmp_path):
        e1 = KnowledgeSyncer.make_entry("hello")
        knowledge = AsyncMock()
        syncer = _syncer(
            tmp_path,
            knowledge=knowledge,
            vector_db=FakeVectorDb(
                FakeCollection(
                    ids=["agno-uuid-1"],
                    metadatas=[{"entry_id": e1["id"]}],
                )
            ),
        )
        syncer.save_file([e1])

        result = await syncer.sync_file_to_db()
        assert result.new_entries == 0
        assert result.existing_entries == 1
        assert knowledge.insert.call_count == 0


# ── sync_db_to_file ────────────────────────────────────────────────


class TestSyncDbToFile:
    def test_no_new_entries(self, tmp_path):
        e1 = KnowledgeSyncer.make_entry("hello")
        col = FakeCollection(ids=[e1["id"]], documents=["hello"], metadatas=[{"source": ""}])
        syncer = _syncer(tmp_path, vector_db=FakeVectorDb(col))
        syncer.save_file([e1])

        result = syncer.sync_db_to_file()
        assert result.new_entries == 0

    def test_new_entries_appended(self, tmp_path):
        e1 = KnowledgeSyncer.make_entry("hello")
        new_id = "new_entry_id"
        col = FakeCollection(
            ids=[e1["id"], new_id],
            documents=["hello", "new content"],
            metadatas=[{"source": ""}, {"source": "agent"}],
        )
        syncer = _syncer(tmp_path, vector_db=FakeVectorDb(col))
        syncer.save_file([e1])

        result = syncer.sync_db_to_file()
        assert result.new_entries == 1
        assert result.total_entries == 2

        loaded = syncer.load_file()
        assert len(loaded) == 2
        assert loaded[1]["id"] == new_id

    def test_creates_file_if_missing(self, tmp_path):
        col = FakeCollection(ids=["a"], documents=["content"], metadatas=[{"source": "test"}])
        syncer = _syncer(tmp_path, vector_db=FakeVectorDb(col))

        result = syncer.sync_db_to_file()
        assert result.new_entries == 1
        assert syncer.file_path.exists()

    def test_empty_db_no_file(self, tmp_path):
        syncer = _syncer(tmp_path, vector_db=FakeVectorDb(FakeCollection()))

        result = syncer.sync_db_to_file()
        assert result.new_entries == 0
        assert result.total_entries == 0


# ── KnowledgeConfig share fields ────────────────────────────────────


class TestKnowledgeConfigShare:
    def test_share_defaults(self):
        cfg = KnowledgeConfig()
        assert cfg.share is True
        assert cfg.share_file == ".ember/knowledge.yaml"
        assert cfg.auto_sync is True

    def test_share_enabled(self):
        cfg = KnowledgeConfig(share=True)
        assert cfg.share is True

    def test_custom_share_file(self):
        cfg = KnowledgeConfig(share=True, share_file=".ember/team-knowledge.yaml")
        assert cfg.share_file == ".ember/team-knowledge.yaml"

    def test_auto_sync_disabled(self):
        cfg = KnowledgeConfig(share=True, auto_sync=False)
        assert cfg.auto_sync is False

    def test_settings_includes_share_fields(self):
        s = Settings(knowledge=KnowledgeConfig(share=True, auto_sync=False))
        assert s.knowledge.share is True
        assert s.knowledge.auto_sync is False
