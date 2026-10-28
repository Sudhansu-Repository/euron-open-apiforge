"""The configured storage and cache backends are the ones actually used.

``make test-matrix`` reruns the whole suite with TEST_STORAGE=s3 against Floci (provisioned
by the local-floci Terraform) and with TEST_CACHE=memory, so every other test also runs on
every backend; these assert the wiring.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from apiforge_server.core.kv import MemoryKV, RedisKV
from apiforge_server.core.storage import LocalStorage, S3Storage
from apiforge_server.generations.models import Generation
from apiforge_server.projects.models import SpecVersion
from tests.integration.conftest import Api, corpus

pytestmark = pytest.mark.integration


async def test_backends_match_the_matrix(api: Api) -> None:
    c = api.container
    storage = os.environ.get("TEST_STORAGE", "local")
    cache = os.environ.get("TEST_CACHE", "redis")
    assert isinstance(c.storage, S3Storage if storage == "s3" else LocalStorage)
    assert isinstance(c.kv, RedisKV if cache == "redis" else MemoryKV)


async def test_specs_and_archives_round_trip_through_the_storage_backend(api: Api) -> None:
    slug = await api.project()
    await api.spec(slug, corpus("petstore.yaml"), "petstore.yaml")
    gen = await api.generate(slug)
    assert gen["status"] == "succeeded", gen
    async with api.container.db.sessionmaker() as session:
        spec_key = await session.scalar(select(SpecVersion.storage_key))
        archive_key = await session.scalar(select(Generation.archive_key))
    assert (
        spec_key
        and spec_key.startswith("specs/")
        and archive_key
        and archive_key.startswith("archives/")
    )
    assert await api.container.storage.get(spec_key) == corpus("petstore.yaml")
    zipped = await api.container.storage.get(archive_key)
    assert zipped[:2] == b"PK" and len(zipped) == gen["archive_bytes"]


async def test_lint_results_are_cached_and_survive_a_cache_outage(api: Api) -> None:
    body = {"content": corpus("petstore.yaml").decode()}
    first = await api.ok("POST", "/api/v1/lint", body)
    second = await api.ok("POST", "/api/v1/lint", body)
    assert first == second

    class Broken:
        backend = "redis"

        async def get(self, key: str) -> bytes | None:
            raise ConnectionError("cache down")

        async def set(self, key: str, value: bytes, ttl_s: int) -> None:
            raise ConnectionError("cache down")

        async def mget(self, keys: list[str]) -> list[bytes | None]:
            raise ConnectionError("cache down")

        async def incr(self, key: str) -> int:
            raise ConnectionError("cache down")

        async def hit(self, name: str, limit: int, amount: int = 1) -> object:
            raise ConnectionError("cache down")

    original = api.container.kv
    api.container.kv = Broken()  # type: ignore[assignment]
    try:
        assert await api.ok("POST", "/api/v1/lint", body) == first
    finally:
        api.container.kv = original
