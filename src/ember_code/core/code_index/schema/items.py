"""Domain models for files, folders, and chunks indexed by code_index.

These are pure data models. Conversion from raw Weaviate objects and
SQLite-backed reference resolution live in the service layer
(``vectordb/files_manager.py`` and ``services/files.py``).

Permission fields (``private``, ``users_with_*``, ``groups_with_*``,
``created_by``, ``unique_identifier``) and the ``starred`` UI flag are
intentionally absent — code_index is single-user/local. ``line_from`` /
``line_to`` are accepted on input but persisted to SQLite commit
metadata, not to Weaviate.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from ember_code.core.code_index.enums import FileSystemType
from ember_code.core.code_index.schema import convert_weaviate_types, now_iso


class CodeIndexItemBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str | None = None
    timestamp: str = Field(default_factory=now_iso)

    _agno_documents: list | None = PrivateAttr(default=None)

    @property
    def content_hash(self) -> str | None:
        if self.content is None:
            return None
        return hashlib.sha256(self.content.encode()).hexdigest()

    def set_agno_documents(self, agno_documents: list) -> None:
        """Attach pre-chunked Agno reader output for downstream vectorization.

        Why: Agno readers (PDF, URL, etc.) chunk semantically with overlap.
        We keep the original full text in ``content`` (for hashing/display)
        and the overlapping chunks in ``content_chunks`` (for retrieval).
        """
        self._agno_documents = agno_documents

    @property
    def content_chunks(self) -> list[CodeIndexFileChunkBase]:
        if not self._agno_documents:
            return []
        return [
            CodeIndexFileChunkBase(index=i, content=doc.content)
            for i, doc in enumerate(self._agno_documents)
        ]


class CodeIndexFileChunkBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    item_id: str = Field(default_factory=lambda: str(uuid4()))
    index: int
    content: str

    @model_validator(mode="before")
    @classmethod
    def _convert_weaviate_types(cls, data):
        if isinstance(data, dict):
            return convert_weaviate_types(data)
        return data

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()

    @property
    def uuid(self) -> str:
        return self.item_id


class CodeIndexItemCreate(CodeIndexItemBase):
    item_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    parent_id: str | None = None
    source_documents_ids: list[str] = Field(default_factory=list)
    type: FileSystemType = FileSystemType.FILE
    tags: list[str] = Field(default_factory=list)
    file_extension: str | None = None
    token_count: int | None = None
    line_from: int | None = None
    line_to: int | None = None
    repository_id: str | None = None
    path: str | None = None

    def to_db_format(self) -> dict:
        """Shape for direct insert into Weaviate (Documents collection).

        ``line_from`` / ``line_to`` are dropped — they live in SQLite
        commit_metadata, scoped per commit SHA.
        """
        dump = self.model_dump()
        dump["name_lowercase"] = self.name.lower() if self.name else None
        dump["path_lowercase"] = self.path.lower() if self.path else None
        dump["content_hash"] = self.content_hash
        dump.pop("line_from", None)
        dump.pop("line_to", None)
        return dump

    def to_item(self) -> CodeIndexItem:
        return CodeIndexItem.model_validate(self.model_dump())


class CodeIndexItemUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tags: list[str] | None = None
    timestamp: str | None = None
    archived: bool | None = None

    def to_non_empty_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Metadata(BaseModel):
    distance: float | None = None
    certainty: float | None = None


class CodeIndexFileChunk(CodeIndexFileChunkBase):
    metadata: Metadata | None = None
    vector: list[float] | None = None
    document: CodeIndexItem | None = None


class Edge(BaseModel):
    """A reference edge between two items, stored in SQLite."""

    meta: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    file: CodeIndexItem


class References(BaseModel):
    parent: CodeIndexItem | None = None
    source_documents: list[CodeIndexItem] = Field(default_factory=list)
    derived_documents: list[CodeIndexItem] = Field(default_factory=list)
    document_references: list[Edge] = Field(default_factory=list)
    referenced_by: list[Edge] = Field(default_factory=list)

    @property
    def safe_to_delete(self) -> bool:
        return not any(
            [
                self.source_documents,
                self.derived_documents,
                self.document_references,
                self.referenced_by,
            ]
        )


class CodeIndexItem(CodeIndexItemCreate):
    parent_ids_hierarchy: list[str] = Field(default_factory=list)
    references: References = Field(default_factory=References)
    archived: bool = False

    _chunks_override: list[CodeIndexFileChunk | CodeIndexFileChunkBase] | None = PrivateAttr(
        default=None
    )

    def __init__(self, **data: Any):
        chunks_data = data.pop("chunks", None)
        super().__init__(**data)
        if chunks_data is not None:
            if chunks_data and isinstance(chunks_data[0], dict):
                self._chunks_override = [
                    CodeIndexFileChunk(**c) if isinstance(c, dict) else c for c in chunks_data
                ]
            else:
                self._chunks_override = chunks_data

    @model_validator(mode="before")
    @classmethod
    def _convert_weaviate_types(cls, data):
        if isinstance(data, dict):
            return convert_weaviate_types(data)
        return data

    @property
    def chunks(self) -> list[CodeIndexFileChunk | CodeIndexFileChunkBase]:
        source = self._chunks_override if self._chunks_override is not None else self.content_chunks
        return sorted(source, key=lambda c: c.index)

    @chunks.setter
    def chunks(self, value: list[CodeIndexFileChunk | CodeIndexFileChunkBase]) -> None:
        self._chunks_override = value

    @property
    def uuid(self) -> str:
        return self.item_id

    @property
    def is_file(self) -> bool:
        return self.type == FileSystemType.FILE

    @property
    def is_folder(self) -> bool:
        return self.type == FileSystemType.FOLDER

    @property
    def has_parent(self) -> bool:
        return bool(self.parent_id)

    def to_db_format(self) -> dict:
        data = self.model_dump()
        for k in ("references", "metadata", "vector", "line_from", "line_to"):
            data.pop(k, None)
        fallback_name = self.name if self.name else self.content_hash
        data["name"] = fallback_name
        data["name_lowercase"] = fallback_name.lower() if fallback_name else None
        data["path_lowercase"] = self.path.lower() if self.path else None
        data["content_hash"] = self.content_hash
        return data


CodeIndexItem.model_rebuild()
CodeIndexFileChunk.model_rebuild()


class FileSystemItemCount(BaseModel):
    files: int
    folders: int


class FileSystemItemArchivedCount(BaseModel):
    files: int
    archived_files: int


class FileSystemItemAggregatedCount(BaseModel):
    items: dict[str, FileSystemItemCount]
