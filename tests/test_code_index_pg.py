"""Tests for the SQLite layer of code_index (SQLAlchemy ORM + alembic).

Each test gets its own tmp file — file isolation gives us project
scoping without a tenant column.
"""

from __future__ import annotations

import pytest

from ember_code.core.code_index.enums import ReferenceTagOperation
from ember_code.core.code_index.pg.commit_metadata import CommitMetadataService
from ember_code.core.code_index.pg.file_reference import FileReferenceService
from ember_code.core.db.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "state.db")


@pytest.fixture
def file_refs(db):
    return FileReferenceService(db)


@pytest.fixture
def commits(db):
    return CommitMetadataService(db)


# -- file_reference -----------------------------------------------------------


async def test_create_get_exists(file_refs):
    await file_refs.create(from_uuid="a", to_uuid="b", tags=["imports"], meta={"line": 5})
    assert await file_refs.exists(from_uuid="a", to_uuid="b")
    assert not await file_refs.exists(from_uuid="a", to_uuid="missing")
    ref = await file_refs.get(from_uuid="a", to_uuid="b")
    assert ref is not None
    assert ref.tags == ["imports"]
    assert ref.meta == {"line": 5}


async def test_create_is_upsert(file_refs):
    await file_refs.create(from_uuid="a", to_uuid="b", tags=["v1"], meta={})
    await file_refs.create(from_uuid="a", to_uuid="b", tags=["v2"], meta={"x": 1})
    ref = await file_refs.get(from_uuid="a", to_uuid="b")
    assert ref is not None
    assert ref.tags == ["v2"]
    assert ref.meta == {"x": 1}


async def test_get_by_uuids(file_refs):
    await file_refs.create(from_uuid="a", to_uuid="b", tags=[], meta={})
    await file_refs.create(from_uuid="b", to_uuid="c", tags=[], meta={})
    await file_refs.create(from_uuid="x", to_uuid="y", tags=[], meta={})
    refs = await file_refs.get_by_uuids(uuids=["b"])
    pairs = {(r.from_uuid, r.to_uuid) for r in refs}
    assert pairs == {("a", "b"), ("b", "c")}


async def test_query_by_tags_any_and_all(file_refs):
    await file_refs.create(from_uuid="a", to_uuid="b", tags=["imports", "internal"], meta={})
    await file_refs.create(from_uuid="b", to_uuid="c", tags=["calls"], meta={})
    await file_refs.create(from_uuid="c", to_uuid="d", tags=["imports", "external"], meta={})

    any_imports = await file_refs.query_by_tags(tags=["imports"], match_all=False)
    assert {(r.from_uuid, r.to_uuid) for r in any_imports} == {("a", "b"), ("c", "d")}

    all_imports_internal = await file_refs.query_by_tags(
        tags=["imports", "internal"], match_all=True
    )
    assert {(r.from_uuid, r.to_uuid) for r in all_imports_internal} == {("a", "b")}


async def test_update_tags_set_add_remove(file_refs):
    await file_refs.create(from_uuid="a", to_uuid="b", tags=["one"], meta={})

    updated = await file_refs.update_tags(
        from_uuid="a", to_uuid="b", tags=["two"], operation=ReferenceTagOperation.ADD
    )
    assert set(updated.tags) == {"one", "two"}

    updated = await file_refs.update_tags(
        from_uuid="a",
        to_uuid="b",
        tags=["one"],
        operation=ReferenceTagOperation.REMOVE,
    )
    assert updated.tags == ["two"]

    updated = await file_refs.update_tags(
        from_uuid="a",
        to_uuid="b",
        tags=["fresh"],
        operation=ReferenceTagOperation.SET,
    )
    assert updated.tags == ["fresh"]


async def test_delete_by_uuid_drops_both_directions(file_refs):
    await file_refs.create(from_uuid="a", to_uuid="b", tags=[], meta={})
    await file_refs.create(from_uuid="b", to_uuid="c", tags=[], meta={})
    await file_refs.create(from_uuid="x", to_uuid="y", tags=[], meta={})

    removed = await file_refs.delete_by_uuid(uuid="b")
    assert removed == 2
    assert await file_refs.get_by_uuids(uuids=["b"]) == []
    assert len(await file_refs.get_by_uuids(uuids=["x", "y"])) == 1


async def test_project_isolation_via_separate_files(tmp_path):
    """Two ``Database`` instances on different files share nothing."""
    db_a = Database(tmp_path / "proj_a.db")
    db_b = Database(tmp_path / "proj_b.db")
    refs_a = FileReferenceService(db_a)
    refs_b = FileReferenceService(db_b)

    await refs_a.create(from_uuid="a", to_uuid="b", tags=["x"], meta={})
    await refs_b.create(from_uuid="a", to_uuid="b", tags=["y"], meta={})
    assert (await refs_a.get(from_uuid="a", to_uuid="b")).tags == ["x"]
    assert (await refs_b.get(from_uuid="a", to_uuid="b")).tags == ["y"]


# -- commit_metadata ----------------------------------------------------------


async def test_create_or_update_and_fetch(commits):
    await commits.create_or_update(
        item_id="i1",
        commit_sha="sha1",
        key="line_range",
        value={"line_from": 1, "line_to": 30},
    )
    found = await commits.get_by_items_and_commit(
        item_ids=["i1"], commit_sha="sha1", key="line_range"
    )
    assert found == {"i1": {"line_from": 1, "line_to": 30}}


async def test_create_or_update_is_upsert(commits):
    await commits.create_or_update(
        item_id="i1", commit_sha="sha1", key="line_range", value={"v": 1}
    )
    await commits.create_or_update(
        item_id="i1", commit_sha="sha1", key="line_range", value={"v": 2}
    )
    found = await commits.get_by_items_and_commit(
        item_ids=["i1"], commit_sha="sha1", key="line_range"
    )
    assert found == {"i1": {"v": 2}}


async def test_bulk_create_or_update(commits):
    await commits.bulk_create_or_update(
        commit_sha="sha1",
        key="line_range",
        items=[
            {"item_id": "a", "value": {"line_from": 1, "line_to": 10}},
            {"item_id": "b", "value": {"line_from": 11, "line_to": 20}},
            {"item_id": "c", "value": {"line_from": 21, "line_to": 30}},
        ],
    )
    found = await commits.get_by_items_and_commit(
        item_ids=["a", "b", "c"], commit_sha="sha1", key="line_range"
    )
    assert set(found.keys()) == {"a", "b", "c"}
    assert found["b"] == {"line_from": 11, "line_to": 20}


async def test_delete_by_item_and_commit(commits):
    for sha in ("s1", "s2"):
        await commits.create_or_update(item_id="i1", commit_sha=sha, key="k", value={})
        await commits.create_or_update(item_id="i2", commit_sha=sha, key="k", value={})

    await commits.delete_by_item(item_id="i1")
    assert (
        await commits.get_by_items_and_commit(item_ids=["i1", "i2"], commit_sha="s1", key="k")
    ).keys() == {"i2"}

    await commits.delete_by_commit(commit_sha="s1")
    assert (
        await commits.get_by_items_and_commit(item_ids=["i1", "i2"], commit_sha="s1", key="k") == {}
    )
    assert (
        await commits.get_by_items_and_commit(item_ids=["i1", "i2"], commit_sha="s2", key="k")
    ).keys() == {"i2"}
