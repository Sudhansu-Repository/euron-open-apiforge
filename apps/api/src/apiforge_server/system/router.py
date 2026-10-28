"""Health, readiness, metrics and deployment info."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from apiforge_server import __version__
from apiforge_server.auth.dependencies import Viewer
from apiforge_server.core.deps import ContainerDep, SessionDep
from apiforge_server.core.errors import AuthenticationError
from apiforge_server.core.schemas import ApiModel
from apiforge_server.core.security import constant_time_equals
from apiforge_server.keys import service as key_service

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", summary="Liveness (alias of /healthz)")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


async def _probe(name: str, coro: Awaitable[Any]) -> tuple[str, dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=2)
        return name, {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        return name, {"ok": False, "error": type(exc).__name__}


@router.get("/readyz", summary="Readiness: Postgres reachable (Redis too, when configured)")
async def readyz(container: ContainerDep, response: Response) -> dict[str, Any]:
    async def pg() -> None:
        async with container.db.engine.connect() as conn:
            await conn.execute(text("select 1"))

    probes = [_probe("postgres", pg())]
    if container.kv.backend == "redis":
        probes.append(_probe("redis", container.kv.ping()))
    checks = dict(await asyncio.gather(*probes))
    # Redis is optional: when it is down every request still works, so only Postgres
    # decides readiness. A Redis failure is reported as degraded but stays ready.
    ok = checks["postgres"]["ok"]
    response.status_code = 200 if ok else 503
    degraded = not all(c["ok"] for c in checks.values())
    return {"status": "degraded" if degraded else "ready", "checks": checks}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics(request: Request, container: ContainerDep) -> Response:
    """APIForge's own metrics (Prometheus text format)."""
    token = container.settings.metrics_token
    if token and not constant_time_equals(
        request.headers.get("authorization", ""), f"Bearer {token}"
    ):
        raise AuthenticationError("Send METRICS_TOKEN as a bearer token", code="metrics_token")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class SystemInfo(ApiModel):
    version: str
    generator_version: str
    environment: str
    cloud: str
    storage: str
    cache_backend: str
    worker_concurrency: int
    generation_timeout_s: int
    max_spec_bytes: int
    active_keys: int
    checks: dict[str, Any]


@router.get("/api/v1/system", response_model=SystemInfo, summary="Deployment configuration")
async def system(_: Viewer, session: SessionDep, container: ContainerDep) -> SystemInfo:
    from apiforge import __version__ as generator_version

    s = container.settings
    keys = await key_service.count_active(session)
    probes = [_probe("postgres", session.execute(text("select 1")))]
    if container.kv.backend == "redis":
        probes.append(_probe("redis", container.kv.ping()))
    checks: dict[str, Any] = dict(await asyncio.gather(*probes))
    return SystemInfo(
        version=__version__,
        generator_version=generator_version,
        environment=s.environment,
        cloud=s.cloud,
        storage=s.storage,
        cache_backend=container.kv.backend,
        worker_concurrency=s.worker_concurrency,
        generation_timeout_s=s.generation_timeout_s,
        max_spec_bytes=s.max_spec_bytes,
        active_keys=int(keys or 0),
        checks=checks,
    )
