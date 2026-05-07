"""Tests for the JSONL delta contract + applier."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ember_code.core.code_index.delta import (
    CommitOp,
    DeltaError,
    UpsertItemOp,
    apply_delta,
    iter_ops,
    parse_op,
)
from ember_code.core.code_index.index import CodeIndex
from ember_code.core.code_index.paths import state_db_path
from ember_code.core.code_index.pg.file_reference import FileReferenceService
from ember_code.core.db.database import Database


@pytest.fixture
async def index(tmp_path):
    idx = CodeIndex(project=tmp_path / "proj_a", data_dir=str(tmp_path / "data"))
    yield idx
    await idx.close()


@pytest.fixture
def file_refs(tmp_path):
    db = Database(state_db_path(tmp_path / "proj_a", data_dir=str(tmp_path / "data")))
    return FileReferenceService(db)


def _write_jsonl(path: Path, lines: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


# -- Parsing ------------------------------------------------------------------


class TestParseOp:
    def test_blank_line_returns_none(self):
        assert parse_op("") is None
        assert parse_op("   ") is None

    def test_invalid_json_raises(self):
        with pytest.raises(DeltaError, match="invalid JSON"):
            parse_op("{not json}")

    def test_missing_op_field_raises(self):
        with pytest.raises(DeltaError, match="missing 'op'"):
            parse_op(json.dumps({"id": "x"}))

    def test_unknown_op_raises(self):
        with pytest.raises(DeltaError, match="unknown op"):
            parse_op(json.dumps({"op": "rename"}))

    def test_validation_error_on_bad_payload(self):
        with pytest.raises(DeltaError, match="validation failed"):
            parse_op(json.dumps({"op": "upsert_item"}))

    def test_commit_op_parses(self):
        op = parse_op(
            json.dumps({"op": "commit", "sha": "abc", "parent_sha": None, "branches": []})
        )
        assert isinstance(op, CommitOp)
        assert op.sha == "abc"

    def test_upsert_item_parses(self):
        op = parse_op(
            json.dumps(
                {
                    "op": "upsert_item",
                    "id": "a",
                    "type": "file",
                    "name": "x.py",
                    "path": "src/x.py",
                    "content": "...",
                    "tags": ["type:file"],
                }
            )
        )
        assert isinstance(op, UpsertItemOp)
        assert op.path == "src/x.py"

    def test_iter_ops_skips_blanks(self, tmp_path):
        path = tmp_path / "delta.jsonl"
        path.write_text(
            "\n".join(
                [
                    json.dumps({"op": "commit", "sha": "abc"}),
                    "",
                    json.dumps({"op": "delete_item", "id": "a"}),
                ]
            )
        )
        ops = list(iter_ops(path))
        assert [type(o).__name__ for o in ops] == ["CommitOp", "DeleteItemOp"]


# -- Apply --------------------------------------------------------------------


class TestApplyDelta:
    @pytest.mark.asyncio
    async def test_first_line_must_be_commit(self, index, file_refs, tmp_path):
        path = _write_jsonl(tmp_path / "delta.jsonl", [{"op": "delete_item", "id": "x"}])
        with pytest.raises(DeltaError, match="first line"):
            await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)

    @pytest.mark.asyncio
    async def test_empty_file_raises(self, index, file_refs, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        with pytest.raises(DeltaError, match="empty"):
            await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)

    @pytest.mark.asyncio
    async def test_full_round_trip(self, index, file_refs, tmp_path):
        path = _write_jsonl(
            tmp_path / "delta.jsonl",
            [
                {"op": "commit", "sha": "head_sha", "parent_sha": None},
                {
                    "op": "upsert_item",
                    "id": "auth-uuid",
                    "type": "file",
                    "name": "auth.py",
                    "path": "src/auth.py",
                    "content": "JWT authentication issues access tokens.",
                    "kind": "code",
                    "file_extension": "py",
                },
                {
                    "op": "upsert_item",
                    "id": "user-uuid",
                    "type": "file",
                    "name": "user.py",
                    "path": "src/user.py",
                    "content": "User profile management.",
                    "kind": "code",
                    "file_extension": "py",
                },
                {
                    "op": "upsert_reference",
                    "from_id": "auth-uuid",
                    "to_id": "user-uuid",
                    "relation": "imports",
                    "meta": {"line": 5},
                },
            ],
        )
        stats = await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)
        assert stats.items_upserted == 2
        assert stats.references_upserted == 1
        assert stats.items_deleted == 0

        # Items landed in the chroma file for the named commit.
        item = await index.get_item("auth-uuid")
        assert item is not None and item.name == "auth.py"

        # head pointer set.
        assert index.head() == "head_sha"

        # Reference landed in SQLite.
        ref = await file_refs.get(from_uuid="auth-uuid", to_uuid="user-uuid", relation="imports")
        assert ref is not None
        assert ref.relation == "imports"

    @pytest.mark.asyncio
    async def test_idempotent_when_replayed(self, index, file_refs, tmp_path):
        path = _write_jsonl(
            tmp_path / "delta.jsonl",
            [
                {"op": "commit", "sha": "s1"},
                {
                    "op": "upsert_item",
                    "id": "i1",
                    "type": "file",
                    "name": "a.py",
                    "path": "a.py",
                    "content": "alpha",
                },
            ],
        )
        await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)
        await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)

        # Replays don't double-up — same item is upserted in place.
        results = await index.search(query="alpha", limit=10)
        # Filter to the item we just added (chunk hits are deduped to the parent).
        matches = [r for r in results if r.item_id == "i1"]
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_delete_item_drops_from_index(self, index, file_refs, tmp_path):
        path = _write_jsonl(
            tmp_path / "delta.jsonl",
            [
                {"op": "commit", "sha": "s1"},
                {
                    "op": "upsert_item",
                    "id": "i1",
                    "type": "file",
                    "name": "a.py",
                    "path": "a.py",
                    "content": "alpha",
                },
                {"op": "delete_item", "id": "i1"},
            ],
        )
        stats = await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)
        assert stats.items_upserted == 1
        assert stats.items_deleted == 1
        assert await index.get_item("i1") is None

    @pytest.mark.asyncio
    async def test_delete_reference(self, index, file_refs, tmp_path):
        path = _write_jsonl(
            tmp_path / "delta.jsonl",
            [
                {"op": "commit", "sha": "s1"},
                {
                    "op": "upsert_reference",
                    "from_id": "a",
                    "to_id": "b",
                    "relation": "calls",
                    "meta": {},
                },
                {"op": "delete_reference", "from_id": "a", "to_id": "b"},
            ],
        )
        stats = await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)
        assert stats.references_upserted == 1
        assert stats.references_deleted == 1
        assert await file_refs.get(from_uuid="a", to_uuid="b", relation="calls") is None

    @pytest.mark.asyncio
    async def test_copy_on_write_from_parent(self, index, file_refs, tmp_path):
        # First commit: seed an item.
        first = _write_jsonl(
            tmp_path / "first.jsonl",
            [
                {"op": "commit", "sha": "parent"},
                {
                    "op": "upsert_item",
                    "id": "shared",
                    "type": "file",
                    "name": "shared.py",
                    "path": "shared.py",
                    "content": "carried over from parent",
                },
            ],
        )
        await apply_delta(index=index, file_refs=file_refs, jsonl_path=first)

        # Second commit: empty, but declares parent. The shared item must
        # still be queryable in the child commit thanks to copy-on-write.
        second = _write_jsonl(
            tmp_path / "second.jsonl",
            [{"op": "commit", "sha": "child", "parent_sha": "parent"}],
        )
        await apply_delta(index=index, file_refs=file_refs, jsonl_path=second)
        assert index.head() == "child"
        item = await index.get_item("shared", commit="child")
        assert item is not None and item.name == "shared.py"

    @pytest.mark.asyncio
    async def test_second_commit_header_in_file_raises(self, index, file_refs, tmp_path):
        path = _write_jsonl(
            tmp_path / "delta.jsonl",
            [
                {"op": "commit", "sha": "s1"},
                {"op": "commit", "sha": "s2"},
            ],
        )
        with pytest.raises(DeltaError, match="second commit header"):
            await apply_delta(index=index, file_refs=file_refs, jsonl_path=path)
