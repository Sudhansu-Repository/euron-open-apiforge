"""Projects and their spec versions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apiforge_server.core.db import Base, TimestampMixin, new_id


class Project(TimestampMixin, Base):
    """An API the team generates from: a name, default options and its spec history."""

    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # GenerateOptions as a dict: what a new generation uses unless told otherwise.
    default_options: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SpecVersion(TimestampMixin, Base):
    """One uploaded spec: stored in object storage, linted once, compared with the previous."""

    __tablename__ = "spec_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_spec_versions_number"),
        UniqueConstraint("project_id", "sha256", name="uq_spec_versions_sha"),
        Index("ix_spec_versions_project_created", "project_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # A single document, or a zip of documents with relative $refs.
    bundle: Mapped[bool] = mapped_column(nullable=False, default=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    api_version: Mapped[str] = mapped_column(String(100), nullable=False)
    openapi_version: Mapped[str] = mapped_column(String(20), nullable=False)
    operations: Mapped[int] = mapped_column(Integer, nullable=False)
    models: Mapped[int] = mapped_column(Integer, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{severity, code, message, pointer}], from apiforge's report.
    report: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    # {"operations": [...], "tags": [...], "schemes": [...]}: what the spec describes.
    summary: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    # Compared with the previous version: {"added": [...], "removed": [...], "changed": [...]}.
    changes: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
