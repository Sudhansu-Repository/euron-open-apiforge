"""Signed-out sessions, refused until the token would have expired anyway."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apiforge_server.core.db import Base


class RevokedSession(Base):
    """One row per signed-out session token (its ``jti``).

    Kept in Postgres rather than the cache: cache eviction must never bring a signed-out
    session back. Rows past ``expires_at`` are pruned on later sign-outs.
    """

    __tablename__ = "revoked_sessions"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class LoginFailure(Base):
    """Failed sign-ins per account and client address.

    The lockout is scoped to the address the failures come from, so one client guessing
    (or trying to lock someone out) cannot keep the account closed for everyone else;
    ``users.failed_logins`` keeps a much higher account-wide limit for spread-out guessing.
    """

    __tablename__ = "login_failures"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
