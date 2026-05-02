"""Tests for ``CodeIndexTools`` — the agent toolkit over the local code index."""

from __future__ import annotations

import json
import uuid

import pytest

from ember_code.core.code_index.enums import FileSystemType
from ember_code.core.code_index.index import CodeIndex
from ember_code.core.code_index.schema.items import CodeIndexItem
from ember_code.core.tools.codeindex import CodeIndexTools


def _make_item(name: str, content: str) -> CodeIndexItem:
    return CodeIndexItem(
        item_id=str(uuid.uuid4()),
        name=name,
        content=content,
        type=FileSystemType.FILE,
        path=f"src/{name}",
        repository_id="test-repo",
    )


@pytest.fixture
async def index(tmp_path):
    idx = CodeIndex(project=tmp_path / "proj", data_dir=str(tmp_path / "data"))
    await idx.set_head("c1")
    await idx.prepare_commit("c1")
    yield idx
    await idx.close()


@pytest.fixture
def tools(index):
    return CodeIndexTools(index=index)


class TestRegistration:
    def test_registers_all_tools(self, tools):
        names = set()
        for f in tools.functions.values():
            names.add(f.name)
        for f in tools.async_functions.values():
            names.add(f.name)
        assert {
            "codeindex_search",
            "codeindex_item",
            "codeindex_references",
            "codeindex_commits",
        }.issubset(names)


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_relevant_results(self, tools, index):
        await index.add_item(
            "c1",
            _make_item("auth.py", "JWT authentication and access tokens."),
        )
        await index.add_item(
            "c1",
            _make_item("db.py", "Database pool with retries."),
        )
        result = json.loads(await tools.codeindex_search(query="JWT", limit=5))
        assert "items" in result
        assert any(i["name"] == "auth.py" for i in result["items"])

    @pytest.mark.asyncio
    async def test_empty_when_no_matches(self, tools):
        result = json.loads(await tools.codeindex_search(query="anything"))
        assert result == {"items": [], "limit": 20}

    @pytest.mark.asyncio
    async def test_returns_error_json_on_exception(self, tools, monkeypatch):
        async def boom(*_a, **_kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(tools._explicit_index, "search", boom)
        result = json.loads(await tools.codeindex_search(query="x"))
        assert "error" in result


class TestItem:
    @pytest.mark.asyncio
    async def test_returns_item(self, tools, index):
        item = _make_item("seed.py", "seed content")
        await index.add_item("c1", item)
        result = json.loads(await tools.codeindex_item(item_id=item.item_id))
        assert result["item_id"] == item.item_id
        assert result["name"] == "seed.py"

    @pytest.mark.asyncio
    async def test_returns_error_for_missing(self, tools):
        result = json.loads(await tools.codeindex_item(item_id="not-there"))
        assert "error" in result


class TestReferences:
    @pytest.mark.asyncio
    async def test_returns_inbound_and_outbound(self, tools, index):
        file_refs = index._file_reference_service()
        await file_refs.create(from_uuid="a", to_uuid="b", tags=["imports"], meta={})
        await file_refs.create(from_uuid="x", to_uuid="a", tags=["calls"], meta={})

        result = json.loads(await tools.codeindex_references(item_id="a"))
        assert {e["to_id"] for e in result["document_references"]} == {"b"}
        assert {e["from_id"] for e in result["referenced_by"]} == {"x"}


class TestCommits:
    @pytest.mark.asyncio
    async def test_lists_indexed_commits(self, tools, index):
        await index.prepare_commit("c2", parent_sha="c1")
        result = json.loads(await tools.codeindex_commits())
        assert result["head"] == "c1"
        shas = {c["sha"] for c in result["commits"]}
        assert {"c1", "c2"}.issubset(shas)
        head_entry = [c for c in result["commits"] if c["sha"] == "c1"][0]
        assert head_entry["is_head"] is True
