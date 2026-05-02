"""JSONL delta contract + applier for the per-commit code index.

Producers (ember-server) emit a JSONL file describing what changed
between the parent commit and the new one. Each line is a single JSON
object with an ``op`` field. ``apply_delta`` streams the file and
mutates the local chroma index + SQLite reference table accordingly.

Contract — one object per line:

- ``{"op": "commit", "sha": "...", "parent_sha": "...|null", ...}``
  Always the first line. Carries lineage so the applier can
  ``prepare_commit(sha, parent_sha)`` before any data ops.
- ``{"op": "upsert_item", "id": "...", "type": "file|folder|entity", ...}``
  Insert or replace an item. ``id`` is the producer's stable content
  hash (UUID5 of path+content); unchanged items keep their id across
  commits.
- ``{"op": "delete_item", "id": "..."}`` — remove an item.
- ``{"op": "upsert_reference", "from_id": "...", "to_id": "...", "tags": [], "meta": {}}``
  Insert or replace a reference. References live in the per-project
  SQLite (no commit scope) — they persist until explicitly deleted.
- ``{"op": "delete_reference", "from_id": "...", "to_id": "..."}``

Idempotent: applying the same JSONL twice yields the same state. Safe
to retry on partial failure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ember_code.core.code_index.enums import FileSystemType
from ember_code.core.code_index.schema.items import CodeIndexItem

if TYPE_CHECKING:
    from ember_code.core.code_index.index import CodeIndex
    from ember_code.core.code_index.pg.file_reference import FileReferenceService

logger = logging.getLogger(__name__)


# -- Op schemas ---------------------------------------------------------------


class CommitOp(BaseModel):
    op: Literal["commit"]
    sha: str
    parent_sha: str | None = None
    branches: list[str] = Field(default_factory=list)
    indexed_at: str | None = None


class UpsertItemOp(BaseModel):
    op: Literal["upsert_item"]
    id: str
    type: str  # "file" | "folder" | "entity"
    name: str
    path: str | None = None
    parent_id: str | None = None
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    file_extension: str | None = None
    line_from: int | None = None
    line_to: int | None = None
    repository_id: str | None = None
    parent_ids_hierarchy: list[str] = Field(default_factory=list)
    source_documents_ids: list[str] = Field(default_factory=list)
    token_count: int | None = None


class DeleteItemOp(BaseModel):
    op: Literal["delete_item"]
    id: str


class UpsertReferenceOp(BaseModel):
    op: Literal["upsert_reference"]
    from_id: str
    to_id: str
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class DeleteReferenceOp(BaseModel):
    op: Literal["delete_reference"]
    from_id: str
    to_id: str


_OP_MODELS: dict[str, type[BaseModel]] = {
    "commit": CommitOp,
    "upsert_item": UpsertItemOp,
    "delete_item": DeleteItemOp,
    "upsert_reference": UpsertReferenceOp,
    "delete_reference": DeleteReferenceOp,
}


@dataclass
class DeltaStats:
    items_upserted: int = 0
    items_deleted: int = 0
    references_upserted: int = 0
    references_deleted: int = 0
    skipped_lines: int = 0


class DeltaError(Exception):
    """Raised when the JSONL is malformed in a way the applier can't recover from."""


# -- Parsing ------------------------------------------------------------------


def parse_op(raw: str) -> BaseModel | None:
    """Parse one JSONL line into the matching op model, or ``None`` for blanks."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeltaError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "op" not in payload:
        raise DeltaError(f"missing 'op' field: {raw[:120]}")
    op_name = payload["op"]
    model = _OP_MODELS.get(op_name)
    if model is None:
        raise DeltaError(f"unknown op: {op_name!r}")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise DeltaError(f"validation failed for {op_name}: {exc}") from exc


def iter_ops(jsonl_path: str | Path):
    """Yield parsed ops from a JSONL file, skipping blank lines."""
    path = Path(str(jsonl_path)).expanduser()
    with path.open() as fh:
        for line_no, line in enumerate(fh, start=1):
            try:
                op = parse_op(line)
            except DeltaError as exc:
                raise DeltaError(f"line {line_no}: {exc}") from exc
            if op is not None:
                yield op


# -- Applier ------------------------------------------------------------------


async def apply_delta(
    *,
    index: CodeIndex,
    file_refs: FileReferenceService,
    jsonl_path: str | Path,
) -> DeltaStats:
    """Stream a JSONL file and apply each op to the index + reference table.

    The first line must be a ``commit`` op — it carries lineage so the
    target commit's chroma directory is prepared (copy-on-write from
    parent) before any data lands. ``set_head`` is called at the end so
    a fresh search query hits the new commit.
    """
    stats = DeltaStats()
    ops_iter = iter_ops(jsonl_path)

    # First op must be a commit header.
    try:
        first = next(ops_iter)
    except StopIteration as exc:
        raise DeltaError("empty delta file") from exc
    if not isinstance(first, CommitOp):
        raise DeltaError(f"first line must be a 'commit' op, got {type(first).__name__}")
    sha = first.sha
    await index.prepare_commit(sha, parent_sha=first.parent_sha)

    for op in ops_iter:
        if isinstance(op, CommitOp):
            # Multiple commit headers in one file — surface, don't apply.
            raise DeltaError(f"unexpected second commit header at sha={op.sha}")
        elif isinstance(op, UpsertItemOp):
            await index.add_item(sha, _op_to_item(op))
            stats.items_upserted += 1
        elif isinstance(op, DeleteItemOp):
            await index.remove_item(sha, op.id)
            stats.items_deleted += 1
        elif isinstance(op, UpsertReferenceOp):
            await file_refs.create(
                from_uuid=op.from_id,
                to_uuid=op.to_id,
                tags=op.tags,
                meta=op.meta,
            )
            stats.references_upserted += 1
        elif isinstance(op, DeleteReferenceOp):
            await file_refs.delete(from_uuid=op.from_id, to_uuid=op.to_id)
            stats.references_deleted += 1
        else:  # pragma: no cover — exhaustive over registered ops
            stats.skipped_lines += 1

    await index.set_head(sha)
    return stats


def _op_to_item(op: UpsertItemOp) -> CodeIndexItem:
    """Translate a JSONL ``upsert_item`` payload to a :class:`CodeIndexItem`."""
    item_type = FileSystemType.FILE
    if op.type == "folder":
        item_type = FileSystemType.FOLDER
    elif op.type in ("entity", "file"):
        # Entities reuse the FILE type today — the schema doesn't yet
        # differentiate (entity-ness lives in tags + line_from/to).
        item_type = FileSystemType.FILE

    return CodeIndexItem(
        item_id=op.id,
        name=op.name,
        type=item_type,
        path=op.path,
        parent_id=op.parent_id,
        parent_ids_hierarchy=op.parent_ids_hierarchy,
        content=op.content,
        tags=op.tags,
        file_extension=op.file_extension,
        line_from=op.line_from,
        line_to=op.line_to,
        repository_id=op.repository_id,
        source_documents_ids=op.source_documents_ids,
        token_count=op.token_count,
    )
