# Walkthrough: a code tour for contributors

Follow one spec from the moment it is read to the moment a team downloads the generated
project, and you will have seen every important file in the repository. Read this with
the code open; each stop names the function to look at. The reference documents behind
each stop are [generator.md](../architecture/generator.md),
[regeneration.md](../architecture/regeneration.md),
[fidelity.md](../architecture/fidelity.md), [service.md](../architecture/service.md) and
the [LLD](../architecture/LLD.md).

- [Part 1: the generator](#part-1-the-generator)
- [Part 2: the service](#part-2-the-service)
- [Part 3: around the code](#part-3-around-the-code)
- [Where to start for common changes](#where-to-start-for-common-changes)

Set up once:

```bash
cd apps/forge && uv sync
uv run apiforge examples --copy /tmp/specs
uv run apiforge generate --spec /tmp/specs/petstore.yaml --output /tmp/pet-store --db
```

Keep `/tmp/pet-store` open next to the code: every stop below produced part of it.

## Part 1: the generator

### 1. The command line: `apiforge/cli.py`

`main` parses arguments and maps `ForgeError` to exit code 1. `_read_spec` turns a file, a
folder or a zip into `(root bytes, root name, sibling files)`; every later step works on
that triple. `cmd_generate` calls `generate`, then either `build_zip` (`--zip`) or `write`
(a folder). Nothing here knows about FastAPI.

### 2. Loading: `apiforge/loader.py` and `bundles.py`

`load` parses the root and its siblings with `parse_document`: UTF-8 check, JSON or YAML
through `_SafeLoader` (no tags, no timestamps, an alias budget), then `_check_depth` walks
the result with an explicit stack (depth, value budget, only JSON types). `Bundle.resolve`
is the only place a `$ref` is followed: URLs are refused, paths are normalized and must stay
inside the spec. `read_zip` checks declared sizes before decompressing anything. Tests:
`tests/test_loader.py`.

### 3. Validating and normalizing: `apiforge/normalize.py` and `schemas.py`

`validate` refuses Swagger 2.0 (`detect_version`), checks every `$ref` is local and runs
`openapi-spec-validator`. `normalize(bundle)` returns `(ApiDef, Report)`; the `Normalizer`
class walks paths and operations, derives missing operation ids,
builds `ParamDef`, `BodyDef` and `ResponseDef`, maps security requirements, and asks
`schemas.py` to turn every schema into a `ModelDef` or a type expression. Two things happen
here and nowhere else: names become safe Python identifiers (`naming.py`), and every
construct that cannot be expressed is added to the report with a JSON pointer
(`report.warning("callbacks_not_generated", ..., pointer)`). Tests:
`tests/test_normalize.py`.

### 4. The intermediate representation: `apiforge/ir.py`

Plain dataclasses: `ApiDef` with `OperationDef`s and `ModelDef`s. Everything after this
point reads the IR only. When you need a new fact about the spec in a template, it starts
as a field here.

### 5. CRUD detection: `apiforge/crud.py`

Only with `--db`. `detect(api, report)` looks for collection resources (`/things` plus
`/things/{id}` over one schema with an id field), marks each operation with its CRUD role,
and reports why a candidate was skipped (`crud_no_id`, `crud_no_create`, ...).

### 6. Planning: `apiforge/targets/fastapi/plan.py`

`FastApiTarget` computes every signature, decorator, import list and test case in Python
(one `OpView` per operation in `self.views`, with `router_params`, `handler_params`,
`decorator` and `test`). `files()` is the
complete list of generated files with their owner (`generated` or `user`). Read it top to
bottom once: it is the table of contents of a generated project.

### 7. Rendering: `apiforge/render.py` and the templates

`environment()` builds a sandboxed, strict Jinja environment with the escaping filters:
`lit` (`naming.py_literal`), `doc` (`naming.docstring`), `comment`. Open
`targets/fastapi/templates/router.py.j2` and `handlers.py.j2` next to
`/tmp/pet-store/app/generated/routers/pets.py` and `app/handlers/pets.py`: the templates
contain almost no logic, because `plan.py` already did it. `format_python` runs the pinned
ruff binary over every Python file: it sorts imports everywhere, removes unused imports
only under `app/generated/` and `tests/generated/` (handler modules keep their convenience
imports), and formats, each ruff call bounded at 120 s (`_run_ruff`); a syntax error stops
generation with ruff's output. Tests: `tests/test_hostile.py` proves spec text cannot
escape.

Three templates carry the generated app's runtime behaviour, worth reading together:
`security.py.j2` (`require()` with AND inside a requirement and OR across them, the
401 or 403 decision and its challenge, `unsupported()` for schemes APIForge cannot check),
`middleware.py.j2` (security headers, the body limit) and `app.py.j2` (the JSON error
handlers, the docs switch in production). `mock.py.j2` answers 501 in production.
`tests/test_hardening.py` checks them in the source and, in its corpus test, in a running
team-tasks app.

### 8. Mocks: `apiforge/examples.py`

`ExampleBuilder.value(...)` returns the spec's own example when it fits the schema, otherwise a value
synthesized from type, format, enum and constraints; `sample_pattern` walks a regular
expression to build a matching string. The output is `app/generated/mock.py`. Tests:
`tests/test_examples.py`.

### 9. Generating: `apiforge/generator.py`

`generate` strings it together: `load`, `normalize`, the report gate (`ReportBlockedError`
unless `accept_report`), `crud.detect`, `bundled_document` (the spec with cross-file refs
inlined, saved as `app/generated/openapi.json`), `FastApiTarget.files()`, `format_python`,
then the lock (`apiforge.lock`: version, options, spec hash, operations, file hashes).
Tests: `tests/test_generator.py` (byte-identical output, sockets blocked).

### 10. Writing and archiving: `apiforge/writer.py` and `archive.py`

`plan_write` decides, file by file, what a write would do: create, update, keep (yours),
conflict (a generated file whose hash differs from the old lock), delete, and which stubs
to append to which handler module. `write` applies it or raises `ConflictError`.
`build_zip` writes the same files into a deterministic zip. Tests: `tests/test_writer.py`.

### 11. Proving it: `apiforge/fidelity.py` and `verify.py`

`canonical_operations` reduces an OpenAPI document to a comparable form per operation;
`compare` lists differences. The whole module is copied into every project as
`tests/generated/fidelity.py` and used by `test_spec.py`. `verify` runs `uv sync`, ruff,
mypy and pytest in a project. Tests: `tests/test_fidelity.py`, and the corpus suite
(`tests/test_corpus.py`, `make test-corpus`) which runs `verify` on every bundled spec.

## Part 2: the service

### 12. The app factory: `apiforge_server/main.py`

`create_app` wires the routers, the error handlers and the middleware stack
(`RequestContextMiddleware`, `BodySizeLimitMiddleware`, CORS, gzip). The `lifespan`
builds a `Container` (`core/container.py`): settings, database, KV store, config cache,
storage. Nothing is a module-level global; tests build their own container.

### 13. Settings and guards: `core/config.py`

Every setting with its default; `Settings.guard()` refuses unsafe production values. A new
setting goes here and in [configuration.md](configuration.md).

### 14. Who is calling: `auth/dependencies.py`

`current_actor` resolves a session (bearer or cookie, with the CSRF header rule) or an
`afk_` API key (`keys/dependencies.py::authenticate_key`, through the config cache).
`require_role` gives the `Viewer`, `Admin` and `Owner` dependencies every route uses.
Sign-in itself is `auth/service.py::authenticate`: the lockout per account and client
address (`login_failures`) and the account-wide one at 50 failures.

### 15. Uploading a spec: `projects/router.py` to `projects/service.py` to `projects/analysis.py`

`upload_spec` (router) reads at most `MAX_SPEC_BYTES + 1` bytes and calls
`service.upload_spec`: size check, `_safe_filename`, `analysis.analyze` (lint cache by
SHA-256, otherwise load, normalize and fingerprint in a thread), deduplication by
SHA-256, `storage.put` under `specs/`, the new `SpecVersion` row with
`changes_between(previous, analysis)`, an audit row, commit. Follow the
`IntegrityError` branch to see how two concurrent uploads are resolved. Tests:
`tests/integration/test_projects.py`, `test_hardening.py`.

### 16. Requesting a generation: `generations/service.py::create_generation`

The report gate (`ReportHasErrorsError`), default options from the project, the next number
with a retry on a race, the `generation.queued` audit row. The row is now the job.

### 17. The worker: `worker.py` and `generations/service.py::claim`, `run`

`worker.main` loops over `run_due`; a pass that found work marks the job `busy` and the
next pass starts at once, so a queue drains back to back, while an idle worker waits
`WORKER_POLL_S`. `process` calls `claim` (one transaction,
`FOR UPDATE SKIP LOCKED`, the lease, the `worker_lost` rule) and runs the claimed rows with
`asyncio.gather`. `run` reads the spec, calls `_run_generator` in a thread under
`asyncio.wait_for`, stores the zip under `archives/`, and records success or one of the
failure codes. Tests: `tests/integration/test_generations.py` (crashed workers, concurrent
workers, failures recorded), `test_worker_cli.py`.

### 18. Downloads and the file browser: `generations/router.py`

`download` sets the ETag (the archive SHA-256) and `Cache-Control: private, no-cache`, and answers 304 to a
matching `If-None-Match`, checked after the row loads and before storage is read.
`file_content` checks the path against the manifest, answers 304 to a matching
`"<sha>:<path>"` ETag, then reads from `_ArchiveCache` (unpacked once per process, keyed
by SHA-256, bounded at 16 archives and 64 MiB).

### 19. The edges: `core/storage.py`, `core/kv.py`, `core/cache.py`

`ObjectStorage` (local or S3) and `KV` (Redis or memory) are Protocols with two
implementations each, chosen by configuration. `ConfigCache` is the per-process TTL cache
with cluster-wide invalidation through `af:cfg:version`. The caching table in
[HLD.md](../architecture/HLD.md#caching-layers) lists every cache and its test.

### 20. The rest of the platform

`users/service.py` (owner guards), `keys/service.py` (create, update, revoke),
`audit/service.py` (one row per change, same transaction), `overview/router.py` (the home
screen in one call), `system/router.py` (health, readiness, metrics, system info),
`observability/metrics.py` (every Prometheus metric), `cli.py` (`apiforge-server`),
`demo/seed.py` (the demo data, generated through the worker's own code path).

## Part 3: around the code

- **The web app** (`apps/web`): each screen in `src/features/<domain>`, query keys and
  stale times in `src/lib/query-keys.ts`, API types generated from `docs/api/openapi.yaml`
  with `pnpm gen:api`.
- **The OpenAPI document** (`docs/api/openapi.yaml`): exported by `make openapi`, checked
  by `tests/unit/system/test_openapi_drift.py`.
- **The migration** (`apps/api/src/apiforge_server/migrations/versions/0001_initial_schema.py`):
  every table and index, plus the audit log trigger ([data-model.md](../architecture/data-model.md)).
- **Infrastructure**: `deploy/compose/` for the local stack, `infra/terraform/` for AWS
  ([infra/README.md](../../infra/README.md)), `scripts/` for the gates.

## Where to start for common changes

| You want to | Start at | Then |
| ----------- | -------- | ---- |
| Support a new spec construct | `normalize.py` or `schemas.py` (and an IR field in `ir.py` if templates need it) | A template, a unit test, a corpus spec that uses it ([CONTRIBUTING.md](../../CONTRIBUTING.md#conventions)) |
| Report something new in the lint report | `report.warning(...)` in `normalize.py` or `schemas.py` | A test in `test_normalize.py`; an `ACCEPTED` entry if the generated code approximates it |
| Change a generated file | Its template in `targets/fastapi/templates/` and its context in `plan.py` | `make test-corpus` |
| Add a generation option | `options.py`, the CLI flags in `cli.py`, `GenerationOptions` in `projects/schemas.py` | The templates that use it, the lock, the docs |
| Add an API endpoint | The domain's `router.py`, `schemas.py`, `service.py` | An integration test, `make openapi`, `pnpm gen:api` |
| Add a setting | `core/config.py` | [configuration.md](configuration.md), a guard if it is security relevant |
| Change a table | The domain's `models.py` | `make migration MSG="..."`, [data-model.md](../architecture/data-model.md) |
