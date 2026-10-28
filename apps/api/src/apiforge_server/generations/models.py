"""Generations: a spec version plus options, turned into a project archive by the worker."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apiforge_server.core.db import Base, TimestampMixin, new_id

STATUSES = ("queued", "running", "succeeded", "failed")


class Generation(TimestampMixin, Base):
    __tablename__ = "generations"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_generations_number"),
        Index("ix_generations_queue", "status", "created_at"),
        Index("ix_generations_project_created", "project_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    spec_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spec_versions.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    accept_report: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A running job whose worker died is picked up again after its lease expires.
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    archive_key: Mapped[str | None] = mapped_column(String(512))
    archive_sha256: Mapped[str | None] = mapped_column(String(64))
    archive_bytes: Mapped[int | None] = mapped_column(Integer)
    file_count: Mapped[int | None] = mapped_column(Integer)
    # [{path, owner, bytes}]: what is inside the archive, for the file browser.
    files: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    # {"resources": [...], "operations": n, "models": n} from the generation.
    summary: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
