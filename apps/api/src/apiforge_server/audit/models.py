"""SQLAlchemy models for the audit domain."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apiforge_server.core.db import Base


class AuditLog(Base):
    """Append-only. A database trigger refuses UPDATE and DELETE."""

    __tablename__ = "audit_log"
    # The API filters by action prefix ("user.") newest first: a prefix-capable index
    # (varchar_pattern_ops works under any collation) with the id for the order.
    __table_args__ = (
        Index(
            "ix_audit_log_action_id",
            "action",
            "id",
            postgresql_ops={"action": "varchar_pattern_ops"},
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_email: Mapped[str | None] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
