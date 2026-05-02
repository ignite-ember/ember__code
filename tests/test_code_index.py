"""Tests for ``CodeIndex`` — per-commit chroma + manifest + retention."""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ember_code.core.code_index.enums import FileSystemType
from ember_code.core.code_index.index import (
    CodeIndex,
    _branch_heads,
    _decode_list,
    _encode_list,
    _flatten_item_metadata,
)
from ember_code.core.code_index.manifest import Manifest
from ember_code.core.code_index.paths import commit_chroma_path
from ember_code.core.code_index.schema.items import CodeIndexItem


def _make_item(
    *, name: str, content: str, path: str | None = None, tags: list[str] | None = None
) -> CodeIndexItem:
    return CodeIndexItem(
        item_id=str(uuid.uuid4()),
        name=name,
        content=content,
        type=FileSystemType.FILE,
        path=path or f"src/{name}",
        repository_id="test-repo",
        file_extension=name.rsplit(".", 1)[-1] if "." in name else None,
        tags=tags or ["type:file", "type:code"],
    )


@pytest.fixture
async def index(tmp_path):
    idx = CodeIndex(project=tmp_path / "proj_a", data_dir=str(tmp_path / "data"))
    yield idx
    await idx.close()


# -- Manifest -----------------------------------------------------------------


class TestManifest:
    def test_load_missing_file_returns_empty(self, tmp_path):
        m = Manifest(project=tmp_path / "p", data_dir=str(tmp_path / "data"))
        state = m.load()
        assert state.head is None
        assert state.commits == {}

    def test_set_head_creates_commit_entry(self, tmp_path):
        m = Manifest(project=tmp_path / "p", data_dir=str(tmp_path / "data"))
        m.set_head("abc123")
        state = m.load()
        assert state.head == "abc123"
        assert "abc123" in state.commits

    def test_touch_updates_last_used_at(self, tmp_path):
        m = Manifest(project=tmp_path / "p", data_dir=str(tmp_path / "data"))
        m.upsert_commit("abc")
        original = m.load().commits["abc"].last_used_at
        # Force a fresh ISO timestamp.
        import time

        time.sleep(1.1)
        m.touch("abc")
        assert m.load().commits["abc"].last_used_at != original

    def test_remove_commit_clears_head_when_matching(self, tmp_path):
        m = Manifest(project=tmp_path / "p", data_dir=str(tmp_path / "data"))
        m.set_head("abc")
        m.remove_commit("abc")
        state = m.load()
        assert state.head is None
        assert "abc" not in state.commits

    def test_update_branch_refs(self, tmp_path):
        m = Manifest(project=tmp_path / "p", data_dir=str(tmp_path / "data"))
        m.upsert_commit("abc")
        m.update_branch_refs({"abc": ["main", "develop"]})
        assert m.load().commits["abc"].branch_refs == ["main", "develop"]


# -- Metadata helpers ---------------------------------------------------------


class TestMetadata:
    def test_encode_decode_round_trip(self):
        original = ["alpha", "beta", "gamma"]
        encoded = _encode_list(original)
        assert _decode_list(encoded) == original

    def test_encode_drops_empty_strings(self):
        assert _encode_list(["a", "", "b"]) == "a\x1fb"

    def test_decode_empty(self):
        assert _decode_list("") == []

    def test_flatten_item_keeps_lists_as_strings(self):
        item = _make_item(name="x.py", content="x", tags=["a", "b"])
        meta = _flatten_item_metadata(item)
        # Lists encoded; chromadb only takes scalars.
        assert isinstance(meta["tags"], str)
        assert _decode_list(meta["tags"]) == ["a", "b"]


# -- prepare_commit -----------------------------------------------------------


class TestPrepareCommit:
    @pytest.mark.asyncio
    async def test_creates_empty_chroma_when_no_parent(self, index):
        path = await index.prepare_commit("sha_0")
        assert path.exists()
        state = index.manifest.load()
        assert "sha_0" in state.commits

    @pytest.mark.asyncio
    async def test_idempotent_on_existing_commit(self, index):
        await index.prepare_commit("sha_0")
        first_used = index.manifest.load().commits["sha_0"].last_used_at
        import time

        time.sleep(1.1)
        await index.prepare_commit("sha_0")
        # last_used_at should bump on the second call.
        assert index.manifest.load().commits["sha_0"].last_used_at != first_used

    @pytest.mark.asyncio
    async def test_copy_from_parent(self, index):
        # Seed the parent with one item so we can verify copy worked.
        await index.prepare_commit("parent")
        item = _make_item(name="seed.py", content="seed content")
        await index.add_item("parent", item)

        await index.prepare_commit("child", parent_sha="parent")
        # Child must serve the parent's item without us re-adding it.
        fetched = await index.get_item(item.item_id, commit="child")
        assert fetched is not None
        assert fetched["name"] == "seed.py"


# -- add_item / search / get_item ---------------------------------------------


class TestSearchAndGet:
    @pytest.mark.asyncio
    async def test_search_returns_relevant_first(self, index):
        await index.prepare_commit("head_sha")
        await index.set_head("head_sha")
        await index.add_item(
            "head_sha",
            _make_item(
                name="auth.py",
                content="JWT authentication with HS256 token signing.",
            ),
        )
        await index.add_item(
            "head_sha",
            _make_item(
                name="db.py",
                content="Database connection pooling with retry logic.",
            ),
        )

        results = await index.search(query="JWT signing", limit=5)
        assert results
        assert results[0]["name"] == "auth.py"
        assert results[0]["commit"] == "head_sha"

    @pytest.mark.asyncio
    async def test_search_uses_head_when_no_commit_specified(self, index):
        await index.set_head("a")
        await index.prepare_commit("a")
        await index.add_item("a", _make_item(name="head_only.py", content="head only"))
        results = await index.search(query="head only", limit=3)
        assert results and results[0]["name"] == "head_only.py"

    @pytest.mark.asyncio
    async def test_search_no_head_returns_empty(self, index):
        # No commit set — nothing to query.
        assert await index.search(query="anything") == []

    @pytest.mark.asyncio
    async def test_get_item_round_trip(self, index):
        await index.prepare_commit("c")
        await index.set_head("c")
        item = _make_item(
            name="ref.py",
            content="referenced content",
            tags=["domain:billing", "type:file"],
        )
        await index.add_item("c", item)
        fetched = await index.get_item(item.item_id)
        assert fetched is not None
        assert fetched["name"] == "ref.py"
        assert fetched["tags"] == ["domain:billing", "type:file"]


# -- remove_item --------------------------------------------------------------


class TestRemove:
    @pytest.mark.asyncio
    async def test_remove_drops_item_and_chunks(self, index):
        await index.set_head("c")
        await index.prepare_commit("c")
        item = _make_item(name="trash.py", content="garbage")
        await index.add_item("c", item)
        assert await index.get_item(item.item_id) is not None
        await index.remove_item("c", item.item_id)
        assert await index.get_item(item.item_id) is None


# -- prune --------------------------------------------------------------------


class TestPrune:
    @pytest.mark.asyncio
    async def test_keeps_head(self, index):
        await index.set_head("alpha")
        await index.prepare_commit("alpha")
        dropped = await index.prune(keep_recent_days=0)
        assert "alpha" not in dropped

    @pytest.mark.asyncio
    async def test_drops_stale_non_branch_commits(self, index):
        await index.prepare_commit("stale")
        await index.set_head("head")
        await index.prepare_commit("head")

        # Backdate the stale commit past the retention cutoff.
        state = index.manifest.load()
        state.commits["stale"].last_used_at = (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat(timespec="seconds")
        index.manifest.save(state)

        dropped = await index.prune(keep_recent_days=30)
        assert "stale" in dropped
        assert "head" not in dropped
        # Chroma dir for the dropped commit should be gone.
        assert not commit_chroma_path(index.project, "stale", data_dir=index.data_dir).exists()

    @pytest.mark.asyncio
    async def test_keeps_recent_idle_commits(self, index):
        await index.prepare_commit("recent")
        await index.set_head("head")
        await index.prepare_commit("head")
        dropped = await index.prune(keep_recent_days=30)
        assert "recent" not in dropped


# -- branch resolution --------------------------------------------------------


class TestBranchHeads:
    def test_empty_for_non_git(self, tmp_path):
        assert _branch_heads(tmp_path) == {}

    def test_real_git_returns_branches(self, tmp_path):
        # Initialize a tiny repo to verify the helper actually parses output.
        env_args = ["-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "init", "--initial-branch=main"], cwd=tmp_path, check=True)
        (tmp_path / "x.txt").write_text("x")
        subprocess.run(["git", *env_args, "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", *env_args, "commit", "-m", "init"], cwd=tmp_path, check=True)
        subprocess.run(["git", *env_args, "branch", "feature/foo"], cwd=tmp_path, check=True)

        heads = _branch_heads(tmp_path)
        assert set(heads.keys()) == {"main", "feature/foo"}
        # Both branches point at the same commit at this point.
        assert len(set(heads.values())) == 1
