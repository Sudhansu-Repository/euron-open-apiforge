"""Sign-in with lockout, and password changes that end every other session."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from apiforge_server.audit.service import Actor, audit
from apiforge_server.auth.models import LoginFailure
from apiforge_server.core.errors import AppError, AuthenticationError
from apiforge_server.core.security import hash_password, password_problems, verify_password
from apiforge_server.users.models import User

# Failures from one address lock that address out of the account; the account itself
# locks only after many failures from anywhere (guessing spread over many addresses).
MAX_FAILURES = 5
MAX_ACCOUNT_FAILURES = 50
LOCKOUT = timedelta(minutes=15)


async def authenticate(session: AsyncSession, email: str, password: str, ip: str | None) -> User:
    user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
    now = datetime.now(UTC)
    if user is not None:
        address_lock = await session.scalar(
            select(LoginFailure.locked_until).where(
                LoginFailure.user_id == user.id, LoginFailure.ip == (ip or "")
            )
        )
        if (user.locked_until and user.locked_until > now) or (address_lock and address_lock > now):
            raise AuthenticationError(
                "Too many failed attempts. Try again in a few minutes", code="account_locked"
            )
    # Argon2 is deliberately slow: run it off the event loop.
    ok = await asyncio.to_thread(verify_password, password, user.password_hash if user else None)
    if not ok or user is None:
        if user is not None:
            await _record_failure(session, user, now, ip)
        raise AuthenticationError("Email or password is incorrect", code="invalid_credentials")
    if user.disabled:
        raise AuthenticationError("This account is disabled", code="account_disabled")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    await session.execute(
        delete(LoginFailure).where(LoginFailure.user_id == user.id, LoginFailure.ip == (ip or ""))
    )
    audit(session, Actor(user.id, user.email, user.role, ip), "auth.login", "user", user.id)
    await session.commit()
    return user


async def _record_failure(session: AsyncSession, user: User, now: datetime, ip: str | None) -> None:
    """Count a failure atomically in SQL, so parallel attempts cannot share one count."""
    upsert = insert(LoginFailure).values(user_id=user.id, ip=ip or "", failures=1)
    from_address = await session.scalar(
        upsert.on_conflict_do_update(
            index_elements=[LoginFailure.user_id, LoginFailure.ip],
            set_={"failures": LoginFailure.failures + 1},
        ).returning(LoginFailure.failures)
    )
    address_locked = from_address is not None and from_address >= MAX_FAILURES
    if address_locked:
        await session.execute(
            update(LoginFailure)
            .where(LoginFailure.user_id == user.id, LoginFailure.ip == (ip or ""))
            .values(locked_until=now + LOCKOUT, failures=0)
        )
    failures = await session.scalar(
        update(User)
        .where(User.id == user.id)
        .values(failed_logins=User.failed_logins + 1)
        .returning(User.failed_logins)
    )
    account_locked = failures is not None and failures >= MAX_ACCOUNT_FAILURES
    if account_locked:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(locked_until=now + LOCKOUT, failed_logins=0)
        )
    locked = address_locked or account_locked
    actor = Actor(user.id, user.email, user.role, ip)
    audit(session, actor, "auth.login_failed", "user", user.id, locked=locked)
    await session.commit()


async def change_password(
    session: AsyncSession, user: User, current: str, new: str, actor: Actor
) -> User:
    if not await asyncio.to_thread(verify_password, current, user.password_hash):
        raise AuthenticationError("Current password is incorrect", code="invalid_credentials")
    if problems := password_problems(new):
        raise AppError(
            "Password needs " + ", ".join(problems),
            code="weak_password",
            details={"problems": problems},
        )
    user.password_hash = await asyncio.to_thread(hash_password, new)
    user.session_version += 1
    audit(session, actor, "auth.password_changed", "user", user.id)
    await session.commit()
    return user
