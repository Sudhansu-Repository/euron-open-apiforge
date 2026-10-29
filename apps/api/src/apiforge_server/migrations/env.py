"""Alembic environment. Run through ``apiforge-server migrate`` (no alembic.ini needed)."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from apiforge_server.core.db import Base, import_all_models

import_all_models()
target_metadata = Base.metadata
config = context.config
# One migrator at a time (two deploys, or a deploy and a manual run), and DDL that waits
# for a table lock gives up instead of queueing every live query on that table behind it.
MIGRATION_LOCK_ID = 0x41504946  # "APIF"
LOCK_TIMEOUT = "10s"


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _online() -> None:
    engine = create_async_engine(
        config.get_main_option("sqlalchemy.url") or "", poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.execute(text(f"SET lock_timeout = '{LOCK_TIMEOUT}'"))
        await connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        await connection.commit()
        try:
            await connection.run_sync(_run)
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID}
            )
            await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_online())
