"""File-to-file reference model — stored in SQLite, not Weaviate.

Used to express custom code relationships (imports, calls, extends, etc.)
between two indexed items. Kept out of Weaviate so tag mutations and
pruning don't require touching the vector store.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_uuid: str
    to_uuid: str
    tags: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
