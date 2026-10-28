"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from apiforge_server import __version__
from apiforge_server.audit.router import router as audit_router
from apiforge_server.auth.router import router as auth_router
from apiforge_server.core.config import Settings, get_settings
from apiforge_server.core.container import Container
from apiforge_server.core.db import import_all_models
from apiforge_server.core.errors import install_error_handlers
from apiforge_server.core.logs import configure_logging
from apiforge_server.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from apiforge_server.core.tracing import configure_tracing
from apiforge_server.generations.router import router as generations_router
from apiforge_server.keys.router import router as keys_router
from apiforge_server.overview.router import router as overview_router
from apiforge_server.projects.router import router as projects_router
from apiforge_server.system.router import router as system_router
from apiforge_server.users.router import router as users_router

DESCRIPTION = """
Turn OpenAPI specs into FastAPI projects you can run, verify and keep. Upload a spec to a
project (each upload is a version, linted and compared with the previous one), request a
generation, browse the generated files and download the archive. The archive is the same,
byte for byte, as `apiforge generate --zip` produces for the same spec and options.

* `/api/v1/*`: authenticate with a session token (`POST /api/v1/auth/login`) or, for
  read-only automation (for example a CI job downloading the latest archive), an API key
  (`Authorization: Bearer afk_...`).
* `/metrics`: Prometheus metrics.
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    import_all_models()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        try:
            yield
        finally:
            if container is None:
                await app.state.container.close()

    app = FastAPI(
        title="Euron Open APIForge",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        separate_input_output_schemas=False,
    )
    install_error_handlers(app)
    for router in (
        auth_router,
        users_router,
        keys_router,
        overview_router,
        projects_router,
        generations_router,
        audit_router,
        system_router,
    ):
        app.include_router(router)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["authorization", "content-type", "x-apiforge-csrf", "x-request-id"],
        expose_headers=["x-request-id", "retry-after", "content-disposition"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    return app
