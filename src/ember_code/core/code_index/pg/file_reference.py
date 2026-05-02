"""File-to-file reference service backed by per-project SQLite via SQLAlchemy.

Tags are normalized into a side table; ``query_by_tags`` uses a real
B-tree index lookup, not a JSON-array scan.
"""

from __future__ import annotations

from sqlalchemy import delete, distinct, func, or_, select, tuple_
from sqlalchemy.dialects.sqlite import insert

from ember_code.core.code_index.enums import ReferenceTagOperation
from ember_code.core.code_index.pg.models import (
    FileReferenceModel,
    FileReferenceTagModel,
)
from ember_code.core.code_index.schema.file_reference import FileReference
from ember_code.core.db.database import Database


class FileReferenceService:
    def __init__(self, db: Database):
        self.db = db

    # -- Reads -----------------------------------------------------------------

    async def get(self, from_uuid: str, to_uuid: str) -> FileReference | None:
        async with self.db.session() as session:
            row = await session.get(FileReferenceModel, (from_uuid, to_uuid))
            if row is None:
                return None
            tags = await _load_tags(session, [(from_uuid, to_uuid)])
            return _row_to_reference(row, tags.get((from_uuid, to_uuid), []))

    async def exists(self, from_uuid: str, to_uuid: str) -> bool:
        async with self.db.session() as session:
            result = await session.execute(
                select(FileReferenceModel.from_uuid).where(
                    FileReferenceModel.from_uuid == from_uuid,
                    FileReferenceModel.to_uuid == to_uuid,
                )
            )
        return result.first() is not None

    async def get_by_uuids(self, uuids: list[str]) -> list[FileReference]:
        if not uuids:
            return []
        async with self.db.session() as session:
            result = await session.execute(
                select(FileReferenceModel).where(
                    or_(
                        FileReferenceModel.from_uuid.in_(uuids),
                        FileReferenceModel.to_uuid.in_(uuids),
                    ),
                )
            )
            rows = result.scalars().all()
            keys = [(r.from_uuid, r.to_uuid) for r in rows]
            tags = await _load_tags(session, keys)
        return [_row_to_reference(r, tags.get((r.from_uuid, r.to_uuid), [])) for r in rows]

    async def query_by_tags(self, tags: list[str], match_all: bool = False) -> list[FileReference]:
        """Find references with any/all of ``tags`` — index lookup on the tag side table."""
        if not tags:
            return []
        wanted = list(dict.fromkeys(tags))

        async with self.db.session() as session:
            if match_all:
                # Group by reference, keep only those that hit every wanted tag.
                pair_q = (
                    select(
                        FileReferenceTagModel.from_uuid,
                        FileReferenceTagModel.to_uuid,
                    )
                    .where(FileReferenceTagModel.tag.in_(wanted))
                    .group_by(
                        FileReferenceTagModel.from_uuid,
                        FileReferenceTagModel.to_uuid,
                    )
                    .having(func.count(distinct(FileReferenceTagModel.tag)) == len(wanted))
                )
            else:
                pair_q = (
                    select(
                        FileReferenceTagModel.from_uuid,
                        FileReferenceTagModel.to_uuid,
                    )
                    .where(FileReferenceTagModel.tag.in_(wanted))
                    .distinct()
                )
            pairs = (await session.execute(pair_q)).all()
            if not pairs:
                return []

            keys = [(p[0], p[1]) for p in pairs]
            result = await session.execute(
                select(FileReferenceModel).where(
                    tuple_(FileReferenceModel.from_uuid, FileReferenceModel.to_uuid).in_(keys)
                )
            )
            rows = result.scalars().all()
            tag_map = await _load_tags(session, keys)
        return [_row_to_reference(r, tag_map.get((r.from_uuid, r.to_uuid), [])) for r in rows]

    # -- Writes ----------------------------------------------------------------

    async def create(
        self,
        from_uuid: str,
        to_uuid: str,
        tags: list[str],
        meta: dict,
    ) -> FileReference:
        """Upsert a reference. Tags fully replaced; meta replaced."""
        unique_tags = list(dict.fromkeys(tags))
        ref_stmt = insert(FileReferenceModel).values(
            from_uuid=from_uuid, to_uuid=to_uuid, meta=meta
        )
        ref_stmt = ref_stmt.on_conflict_do_update(
            index_elements=["from_uuid", "to_uuid"],
            set_={"meta": ref_stmt.excluded.meta},
        )
        async with self.db.session() as session, session.begin():
            await session.execute(ref_stmt)
            await _replace_tags(session, from_uuid, to_uuid, unique_tags)
        return FileReference(from_uuid=from_uuid, to_uuid=to_uuid, tags=unique_tags, meta=meta)

    async def update_tags(
        self,
        from_uuid: str,
        to_uuid: str,
        tags: list[str],
        operation: ReferenceTagOperation | str,
    ) -> FileReference:
        op = ReferenceTagOperation(operation) if isinstance(operation, str) else operation
        async with self.db.session() as session, session.begin():
            row = await session.get(FileReferenceModel, (from_uuid, to_uuid))
            if row is None:
                raise ValueError(f"Reference not found: {from_uuid}->{to_uuid}")

            if op is ReferenceTagOperation.SET:
                new_tags = list(dict.fromkeys(tags))
                await _replace_tags(session, from_uuid, to_uuid, new_tags)
            elif op is ReferenceTagOperation.ADD:
                # ``ON CONFLICT DO NOTHING`` makes this idempotent.
                if tags:
                    add_stmt = (
                        insert(FileReferenceTagModel)
                        .values(
                            [
                                {"from_uuid": from_uuid, "to_uuid": to_uuid, "tag": t}
                                for t in dict.fromkeys(tags)
                            ]
                        )
                        .on_conflict_do_nothing()
                    )
                    await session.execute(add_stmt)
                new_tags = await _fetch_tags(session, from_uuid, to_uuid)
            elif op is ReferenceTagOperation.REMOVE:
                if tags:
                    await session.execute(
                        delete(FileReferenceTagModel).where(
                            FileReferenceTagModel.from_uuid == from_uuid,
                            FileReferenceTagModel.to_uuid == to_uuid,
                            FileReferenceTagModel.tag.in_(tags),
                        )
                    )
                new_tags = await _fetch_tags(session, from_uuid, to_uuid)
            else:
                raise ValueError(f"Unknown tag operation: {operation}")

            return FileReference(
                from_uuid=row.from_uuid,
                to_uuid=row.to_uuid,
                tags=new_tags,
                meta=dict(row.meta or {}),
            )

    async def delete(self, from_uuid: str, to_uuid: str) -> None:
        # Explicit two-step delete keeps us independent of SQLite's
        # ``PRAGMA foreign_keys=ON`` per-connection setting.
        async with self.db.session() as session, session.begin():
            await session.execute(
                delete(FileReferenceTagModel).where(
                    FileReferenceTagModel.from_uuid == from_uuid,
                    FileReferenceTagModel.to_uuid == to_uuid,
                )
            )
            await session.execute(
                delete(FileReferenceModel).where(
                    FileReferenceModel.from_uuid == from_uuid,
                    FileReferenceModel.to_uuid == to_uuid,
                )
            )

    async def delete_by_uuid(self, uuid: str) -> int:
        """Drop all references involving ``uuid`` (called when an item is deleted)."""
        async with self.db.session() as session, session.begin():
            await session.execute(
                delete(FileReferenceTagModel).where(
                    or_(
                        FileReferenceTagModel.from_uuid == uuid,
                        FileReferenceTagModel.to_uuid == uuid,
                    )
                )
            )
            result = await session.execute(
                delete(FileReferenceModel).where(
                    or_(
                        FileReferenceModel.from_uuid == uuid,
                        FileReferenceModel.to_uuid == uuid,
                    )
                )
            )
            return result.rowcount or 0


# -- Internals ----------------------------------------------------------------


async def _replace_tags(session, from_uuid: str, to_uuid: str, tags: list[str]) -> None:
    await session.execute(
        delete(FileReferenceTagModel).where(
            FileReferenceTagModel.from_uuid == from_uuid,
            FileReferenceTagModel.to_uuid == to_uuid,
        )
    )
    if tags:
        await session.execute(
            insert(FileReferenceTagModel),
            [{"from_uuid": from_uuid, "to_uuid": to_uuid, "tag": t} for t in tags],
        )


async def _fetch_tags(session, from_uuid: str, to_uuid: str) -> list[str]:
    result = await session.execute(
        select(FileReferenceTagModel.tag).where(
            FileReferenceTagModel.from_uuid == from_uuid,
            FileReferenceTagModel.to_uuid == to_uuid,
        )
    )
    return [r[0] for r in result.all()]


async def _load_tags(session, keys: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
    """Bulk-load tags for many references in one query."""
    if not keys:
        return {}
    result = await session.execute(
        select(
            FileReferenceTagModel.from_uuid,
            FileReferenceTagModel.to_uuid,
            FileReferenceTagModel.tag,
        ).where(tuple_(FileReferenceTagModel.from_uuid, FileReferenceTagModel.to_uuid).in_(keys))
    )
    out: dict[tuple[str, str], list[str]] = {}
    for from_uuid, to_uuid, tag in result.all():
        out.setdefault((from_uuid, to_uuid), []).append(tag)
    return out


def _row_to_reference(row: FileReferenceModel, tags: list[str]) -> FileReference:
    return FileReference(
        from_uuid=row.from_uuid,
        to_uuid=row.to_uuid,
        tags=list(tags),
        meta=dict(row.meta or {}),
    )
