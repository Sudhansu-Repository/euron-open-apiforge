# ADR-0010: Python and FastAPI for the generator, API and worker; Next.js for the web app

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

APIForge has a generator (a library and a CLI), an HTTP API, a background worker and a
web app. Every Euron open-source project uses the same stack so contributors can move
between them, and the stack has to suit this product in particular: the generator emits
Python and must format and type check it, and the service must call the generator
in-process to keep archives byte-identical
([ADR-0005](0005-generator-as-a-shared-library.md)).

## Decision

- **Python 3.12** for the generator, the API and the worker, packaged with **uv**, linted
  with **ruff** and type checked with **mypy `--strict`**.
- The generator uses **Jinja2** (sandboxed) for templates, **PyYAML** (safe loading) and
  **openapi-spec-validator**, and ships with the **ruff** binary it formats with.
- The API is **FastAPI** with Pydantic v2 and `pydantic-settings`, **SQLAlchemy 2.0
  async** with asyncpg, **Alembic** migrations, boto3 for S3, `redis` for the optional KV
  store.
- The web app is **Next.js 15** (App Router, React 19, TypeScript strict) with Tailwind v4,
  shadcn/ui and TanStack Query v5; API types are generated from the exported OpenAPI
  document with `openapi-typescript`.

## Consequences

**Good**
- The generator and the service share one language and one process: no subprocess, no
  serialization boundary between them.
- The generated projects use the same stack APIForge itself uses (FastAPI, Pydantic,
  SQLAlchemy, Alembic, uv, ruff, mypy, pytest), so the maintainers know the target well.
- FastAPI serves APIForge's own OpenAPI document, which is exported to
  `docs/api/openapi.yaml`, drift tested, and used to generate the web app's types.

**Bad / caveats**
- Generation is CPU bound and Python is not fast; it runs in worker threads, and large
  specs take seconds rather than milliseconds.
- Two toolchains (uv and pnpm) for contributors who work across the stack.

## Alternatives considered

- **A generator in Java or TypeScript** (as OpenAPI Generator and several SDK tools are).
  Would put a second language between the generator and the Python it emits.
- **A web UI rendered by the API (server templates).** Less tooling, but the references
  and the UI standard call for a full Next.js app with dark and light themes and phone
  layouts.
