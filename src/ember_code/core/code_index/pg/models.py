"""SQLAlchemy ORM models for code_index relational tables.

Live in the per-project ``state.db`` (one SQLite file per project) — file
isolation gives us project scoping, no tenant column needed.

Tags are normalized into a separate ``code_index_file_reference_tag``
table with an index on ``tag`` so ``query_by_tags`` is a real B-tree
lookup instead of a full scan.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKeyConstraint, Index, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ember_code.core.db.base import Base


class FileReferenceModel(Base):
    __tablename__ = "code_index_file_reference"

    from_uuid: Mapped[str] = mapped_column(nullable=False)
    to_uuid: Mapped[str] = mapped_column(nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("from_uuid", "to_uuid", name="pk_cifr"),
        Index("idx_cifr_to", "to_uuid"),
    )


class FileReferenceTagModel(Base):
    __tablename__ = "code_index_file_reference_tag"

    from_uuid: Mapped[str] = mapped_column(nullable=False)
    to_uuid: Mapped[str] = mapped_column(nullable=False)
    tag: Mapped[str] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("from_uuid", "to_uuid", "tag", name="pk_cifrt"),
        # The B-tree index that makes ``query_by_tags`` actually fast.
        Index("idx_cifrt_tag", "tag"),
        ForeignKeyConstraint(
            ["from_uuid", "to_uuid"],
            [
                "code_index_file_reference.from_uuid",
                "code_index_file_reference.to_uuid",
            ],
            ondelete="CASCADE",
            name="fk_cifrt_to_cifr",
        ),
    )


class CommitMetadataModel(Base):
    __tablename__ = "code_index_commit_metadata"

    item_id: Mapped[str] = mapped_column(nullable=False)
    commit_sha: Mapped[str] = mapped_column(nullable=False)
    key: Mapped[str] = mapped_column(nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("item_id", "commit_sha", "key", name="pk_cicm"),
        Index("idx_cicm_commit", "commit_sha", "key"),
    )
