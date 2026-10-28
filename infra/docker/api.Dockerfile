# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# API: the REST API (`apiforge-server serve`), the generation worker
# (`apiforge-server worker`) and the one-off CLI (`migrate`, `seed-demo`,
# `create-owner`, `openapi`). Same image, different command.
#
# Built from the repository root, because the service (apps/api) depends on the
# generator package (apps/forge) as a uv path dependency:
#   docker build -f infra/docker/api.Dockerfile -t apiforge-api .
# ─────────────────────────────────────────────────────────────────────────────
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.9.17 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /uvx /bin/
# Bytecode is compiled here because the runtime root filesystem is read-only.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
# The same relative layout as the repository, so the path dependency ../forge resolves.
WORKDIR /src/api
# Third-party dependencies first, from the lockfile only, so source edits reuse this
# layer. The generator's pyproject is mounted so uv can read the path dependency.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=apps/api/uv.lock,target=/src/api/uv.lock \
    --mount=type=bind,source=apps/api/pyproject.toml,target=/src/api/pyproject.toml \
    --mount=type=bind,source=apps/forge,target=/src/forge \
    uv sync --frozen --no-dev --no-install-project --no-install-package euron-apiforge
COPY apps/forge /src/forge
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
COPY apps/api/src src
# Both packages installed as wheels (not editable): the runtime stage copies only
# /opt/venv. The generator's ruff dependency ships the ruff binary into /opt/venv/bin,
# which the generator runs to format generated code.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
# HOME points at the /tmp mount: the root filesystem is read-only, and tools the worker
# runs on a generated project (ruff) may look for a cache directory there.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC PORT=8080 HOME=/tmp
# tini reaps zombies (the worker runs ruff as a subprocess) and forwards SIGTERM so
# uvicorn drains in-flight requests and the worker finishes its current generation.
# /data/artifacts holds specs and archives with STORAGE=local; a named volume mounted
# there inherits its ownership.
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 apiforge \
 && useradd --system --uid 10001 --gid apiforge --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin apiforge \
 && mkdir -p /data/artifacts && chown apiforge:apiforge /data/artifacts
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# Nothing else to copy: the Alembic migrations ship inside the apiforge_server package
# and `apiforge-server migrate` runs them programmatically; the generator's templates
# ship inside the apiforge package.
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=2).status == 200 else 1)"
ENTRYPOINT ["/usr/bin/tini", "--", "apiforge-server"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
