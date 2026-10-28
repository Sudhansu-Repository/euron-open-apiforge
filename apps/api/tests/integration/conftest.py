"""Integration harness: the real app in-process against real Postgres (and Redis, and S3 on
Floci when the option matrix selects them).

    make test-integration      (starts the Postgres and Redis containers if needed)
    make test-matrix           (reruns everything under every backend combination)

Safety: the suite truncates every table, so it refuses any database whose name does not
contain "test", and any non-local host unless ALLOW_REMOTE_TEST_DB=true.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from apiforge_server.core.config import Settings
from apiforge_server.core.container import Container
from apiforge_server.main import create_app

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://apiforge:apiforge@localhost:4642/apiforge_test",
)
# TEST_CACHE=memory runs the whole suite with no Redis at all.
TEST_CACHE = os.environ.get("TEST_CACHE", "redis")
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:4679/15")
OWNER = {"email": "owner@example.test", "password": "Owner-Pass-123"}
CORPUS = Path(__file__).resolve().parents[3] / "forge" / "src" / "apiforge" / "corpus"


def _guard(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if "test" not in (parsed.path or ""):
        raise RuntimeError(
            f"refusing to run against {parsed.path!r}: database name must contain 'test'"
        )
    if (
        parsed.hostname not in ("localhost", "127.0.0.1", "postgres")
        and os.environ.get("ALLOW_REMOTE_TEST_DB") != "true"
    ):
        raise RuntimeError("refusing a non-local test database (set ALLOW_REMOTE_TEST_DB=true)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    _guard(TEST_DB)
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DB.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    from apiforge_server.migrations.runner import upgrade

    await asyncio.to_thread(upgrade, TEST_DB)
    yield TEST_DB


def make_settings(database: str, tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": database,
        "redis_url": TEST_REDIS if TEST_CACHE == "redis" else "",
        "session_secret": "test-only-session-secret-with-32-plus-bytes",
        "api_key_pepper": "test-only-api-key-pepper-with-32-plus-bytes",
        "local_storage_dir": str(tmp_path / "artifacts"),
        "worker_concurrency": 2,
        # The option matrix (make test-matrix) reruns the suite against S3 on Floci.
        "storage": os.environ.get("TEST_STORAGE", "local"),
        "aws_endpoint_url": os.environ.get("TEST_AWS_ENDPOINT"),
        "s3_force_path_style": True,
        "artifacts_bucket": os.environ.get("TEST_ARTIFACTS_BUCKET", "apiforge-local-artifacts"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(database: str, tmp_path: Path) -> Settings:
    return make_settings(database, tmp_path)


async def reset(settings: Settings) -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
            )
            .scalars()
            .all()
        )
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    if settings.redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        await redis.flushdb()
        await redis.aclose()


async def bootstrap_owner(settings: Settings) -> None:
    from apiforge_server.core.db import Database
    from apiforge_server.core.security import hash_password
    from apiforge_server.users.models import User

    db = Database(settings.database_url, pool_size=1, max_overflow=0)
    async with db.sessionmaker() as session:
        session.add(
            User(
                email=OWNER["email"],
                name="Owner",
                role="owner",
                password_hash=hash_password(OWNER["password"]),
            )
        )
        await session.commit()
    await db.dispose()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    await reset(settings)
    await bootstrap_owner(settings)
    application = create_app(settings)
    async with LifespanManager(application, startup_timeout=60, shutdown_timeout=30):
        yield application


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30
    )


async def login(app: FastAPI, creds: dict[str, str] = OWNER) -> httpx.AsyncClient:
    client = client_for(app)
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    client.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
    return client


# ── helpers ──────────────────────────────────────────────────────────────────


def corpus(name: str) -> bytes:
    return (CORPUS / name).read_bytes()


@dataclass
class Api:
    """A signed-in owner client plus helpers for projects, uploads and worker passes."""

    client: httpx.AsyncClient
    app: FastAPI

    @property
    def container(self) -> Container:
        c: Container = self.app.state.container
        return c

    def anonymous(self) -> httpx.AsyncClient:
        return client_for(self.app)

    async def ok(self, method: str, path: str, json: Any = None, status: int | None = None) -> Any:
        resp = await self.client.request(method, path, json=json)
        expected = status or (201 if method == "POST" and resp.status_code == 201 else 200)
        assert resp.status_code == expected, f"{method} {path}: {resp.status_code} {resp.text}"
        return resp.json() if resp.content else None

    async def project(self, name: str = "Pet Store", **options: Any) -> str:
        body: dict[str, Any] = {"name": name}
        if options:
            body["default_options"] = options
        data = await self.ok("POST", "/api/v1/projects", body)
        return str(data["slug"])

    async def upload(
        self, slug: str, data: bytes, filename: str = "openapi.yaml", note: str = ""
    ) -> httpx.Response:
        return await self.client.post(
            f"/api/v1/projects/{slug}/specs",
            files={"file": (filename, data, "application/octet-stream")},
            data={"note": note},
        )

    async def spec(self, slug: str, data: bytes, filename: str = "openapi.yaml") -> dict[str, Any]:
        resp = await self.upload(slug, data, filename)
        assert resp.status_code in (200, 201), resp.text
        result: dict[str, Any] = resp.json()["spec"]
        return result

    async def work(self) -> int:
        """Run worker passes until the queue is empty; how many generations ran."""
        from apiforge_server.generations import service

        total = 0
        while ran := await service.process(self.container):
            total += ran
        return total

    async def generate(self, slug: str, **body: Any) -> dict[str, Any]:
        queued = await self.ok("POST", f"/api/v1/projects/{slug}/generations", body, status=202)
        await self.work()
        result: dict[str, Any] = await self.ok(
            "GET", f"/api/v1/projects/{slug}/generations/{queued['number']}"
        )
        return result

    async def user(self, role: str, email: str | None = None) -> httpx.AsyncClient:
        email = email or f"{role}@example.test"
        password = f"{role.title()}-Pass-123"
        await self.ok(
            "POST",
            "/api/v1/users",
            {"email": email, "name": role.title(), "password": password, "role": role},
        )
        return await login(self.app, {"email": email, "password": password})


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[Api]:
    client = await login(app)
    try:
        yield Api(client, app)
    finally:
        await client.aclose()
