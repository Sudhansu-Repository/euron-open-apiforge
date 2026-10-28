"""Process-wide services, built once in the app lifespan and shared by every request.

Holding them in one object (on ``app.state``) instead of module globals keeps the app
factory re-entrant and lets tests build an isolated container per app. There is no
outbound HTTP client: APIForge never calls anything on a spec's behalf.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from apiforge_server.core.aws import aws_client
from apiforge_server.core.cache import ConfigCache
from apiforge_server.core.config import Settings
from apiforge_server.core.db import Database
from apiforge_server.core.kv import KV, create_kv
from apiforge_server.core.storage import LocalStorage, ObjectStorage, S3Storage


@dataclass
class Container:
    settings: Settings
    db: Database
    kv: KV
    config_cache: ConfigCache
    storage: ObjectStorage
    # token id -> when this process last wrote its last_used_at (bounded by the token count).
    key_touched: dict[uuid.UUID, datetime] = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings) -> Container:
        kv = create_kv(settings.redis_url)
        storage: ObjectStorage = (
            S3Storage(aws_client(settings, "s3"), settings.artifacts_bucket)
            if settings.storage == "s3"
            else LocalStorage(settings.local_storage_dir)
        )
        return cls(
            settings=settings,
            db=Database(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            ),
            kv=kv,
            config_cache=ConfigCache(kv),
            storage=storage,
        )

    async def close(self) -> None:
        await self.kv.close()
        await self.db.dispose()
