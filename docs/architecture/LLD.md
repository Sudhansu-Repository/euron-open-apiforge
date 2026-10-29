# Low-Level Design

How the code is laid out and how the important parts work, with pointers to the files.
The system view is in [HLD.md](HLD.md); the tables are in [data-model.md](data-model.md);
the generator's pipeline is in [generator.md](generator.md).

- [Repository layout](#repository-layout)
- [Generator package layout](#generator-package-layout)
- [Service package layout](#service-package-layout)
- [Request handling](#request-handling)
- [Domains](#domains)
- [The worker](#the-worker)
- [Interfaces at the edges](#interfaces-at-the-edges)
- [The web app](#the-web-app)
- [Important algorithms at a glance](#important-algorithms-at-a-glance)

## Repository layout

```
apps/forge/    the generator: package euron-apiforge (import apiforge, CLI apiforge), the FastAPI
               target and its templates, the bundled spec corpus; tests/
apps/api/      FastAPI service, worker and CLI: package apiforge_server (CLI apiforge-server),
               tests/unit, tests/integration; depends on apps/forge as a path dependency
apps/web/      Next.js 15 web app (src/app routes, src/features/<domain>, src/lib)
e2e/           Playwright suites against make up && make demo
infra/         Dockerfiles (api, web) and Terraform (modules, envs/local-floci, aws-dev, aws-prod)
deploy/compose compose.yaml plus the floci and aws overlays
scripts/       sanitization, env generation, test database, test matrix, tf-aws-on-floci, AWS deploy, qa/
docs/          architecture, guides, api/openapi.yaml (drift tested)
examples/      a CI download script, a GitHub Actions workflow, a tiny spec
```

The service imports the generator as a library (`euron-apiforge = { path = "../forge",
editable = true }` in `apps/api/pyproject.toml`), and the API image installs both. That is
what makes a web download byte-identical to `apiforge generate --zip`
([ADR-0005](adr/0005-generator-as-a-shared-library.md)).

## Generator package layout

```
apps/forge/src/apiforge/
  loader.py       bytes to plain JSON values: safe YAML, size, depth, alias and value budgets,
                  Bundle (root document plus sibling files), local $ref resolution
  bundles.py      read_zip: a multi-file spec in a zip, sizes checked before decompression
  normalize.py    validate (Swagger 2.0 refused, openapi-spec-validator) and build the IR
                  (operations, parameters, bodies, responses, security); most lint findings
  schemas.py      JSON Schema to models: objects, enums, aliases, unions, constraints
  ir.py           the intermediate representation (ApiDef, OperationDef, ModelDef, ...)
  naming.py       safe identifiers, py_literal, docstring and comment escaping, words()
  report.py       Finding, Report (error, warning, info with a JSON pointer)
  crud.py         with --db: which operations form collection resources, SQL column types
  examples.py     schema-valid examples (the mocks), pattern sampling
  fidelity.py     the canonical form of an OpenAPI document and the comparison
  options.py      GenerateOptions (project_name, db, docker, ci)
  render.py       the sandboxed Jinja environment, filters, ruff formatting
  generator.py    lint() and generate(): the one entry point the CLI and the service use
  archive.py      build_zip: a deterministic zip
  writer.py       plan_write and write: the generation gap on disk
  verify.py       install a generated project and run its gates (uv)
  cli.py          apiforge lint | generate | diff | verify | examples
  errors.py       ForgeError and its subclasses (each with a code)
  targets/fastapi/plan.py        every signature, decorator and import, computed in Python;
                                 the file list
  targets/fastapi/templates/     one Jinja template per generated file
  corpus/         bundled example specs (petstore, bookstore, inventory, secure-notes, edge-cases,
                  team-tasks)
```

The flow and each step's contract are in [generator.md](generator.md). Two rules hold
everywhere after `normalize`: code reads only the IR (never the raw spec), and spec text
reaches a template only through the `lit`, `doc` and `comment` filters.

## Service package layout

Package by domain. Each domain owns its `router.py` (HTTP only), `schemas.py` (the public
contract), `service.py` (rules) and `models.py` (tables). A domain calls another domain's
service, never its router.

```
apps/api/src/apiforge_server/
  core/           config.py (Settings and boot guards), db.py (engine, Base), kv.py (Redis or
                  memory KV), cache.py (ConfigCache), security.py (passwords, sessions, API keys),
                  storage.py (ObjectStorage: local or S3), aws.py (boto3 from config only),
                  middleware.py (request id, security headers, body limit), errors.py (one error
                  envelope), logs.py, tracing.py, schemas.py, container.py, deps.py
  projects/       models.py (projects, spec_versions), analysis.py (the bridge to the generator:
                  lint, fingerprints, the lint cache, changes), service.py (projects, uploads,
                  diffs, playground, examples), router.py, schemas.py
  generations/    models.py (generations), service.py (queue, claim, run, archives, files),
                  router.py, schemas.py
  auth/           dependencies.py (session, CSRF, API key, roles), service.py (sign-in, lockout,
                  password change), models.py (revoked_sessions), router.py
  users/ keys/ audit/    users, read-only API keys, the append-only audit log
  overview/       the home screen in one call
  system/         /healthz, /health, /readyz, /metrics, /api/v1/system
  observability/  metrics.py (Prometheus counters, histograms, gauge)
  limits/         limiter.py (sliding-window rate limiter in Redis)
  demo/seed.py    demo users, an API key, projects from the bundled specs with history
  migrations/     Alembic env, runner, versions/0001_initial_schema.py
  main.py         create_app(): routers, middleware, lifespan
  worker.py       the job loop
  cli.py          apiforge-server serve | worker | migrate | revision | openapi | create-owner |
                  hash-password | seed-demo
  bench.py        make bench
  openapi.py      the exported document (docs/api/openapi.yaml)
```

## Request handling

Middleware order (outermost first), from [`main.py`](../../apps/api/src/apiforge_server/main.py):

1. `RequestContextMiddleware`
   ([`core/middleware.py`](../../apps/api/src/apiforge_server/core/middleware.py)):
   accepts an alphanumeric `X-Request-Id` (at most 64 characters) or generates one, adds
   the security headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
   no-referrer`, `Cross-Origin-Opener-Policy`, `Permissions-Policy`), logs one line per
   request (quiet for `/healthz`, `/readyz` and `/metrics` unless the status is 400 or
   more).
2. `BodySizeLimitMiddleware`: refuses `POST`, `PUT` and `PATCH` bodies over the route's
   limit with 413 (`MAX_BODY_BYTES`, 8 MiB, on `/api/v1/lint` and the two spec upload
   routes; `MAX_SMALL_BODY_BYTES`, 64 KiB, everywhere else), checking `Content-Length` first and counting chunked bodies
   as they arrive; parses JSON bodies with orjson and refuses invalid UTF-8 or a lone
   surrogate with 422 `invalid_json`; then replays the body to the app unchanged.
3. `CORSMiddleware` with the `CORS_ORIGINS` allowlist and credentials.
4. `GZipMiddleware` for responses over 2 KB.

Both custom middlewares are pure ASGI (not `BaseHTTPMiddleware`), so streaming responses
are not buffered.

Dependencies ([`core/deps.py`](../../apps/api/src/apiforge_server/core/deps.py)):
`ContainerDep` (the process-wide services on `app.state`), `SessionDep` (one
`AsyncSession` per request), and the role dependencies `Viewer`, `Admin`, `Owner` from
[`auth/dependencies.py`](../../apps/api/src/apiforge_server/auth/dependencies.py):

- `current_actor` reads `Authorization: Bearer ...` first, then the `af_session` cookie.
  A token starting with `afk_` is an API key: only safe methods, then
  `authenticate_key` (config cache, constant-time HMAC compare, revoked and expired checks,
  per-key rate limit, `last_used_at` at most once a minute). Anything else is a session
  token: signature and audience checked, `jti` not in `revoked_sessions`, the user exists,
  is not disabled and has the same `session_version`. A cookie on a non-safe method must
  carry `X-APIForge-CSRF: 1`.
- `require_role(role)` compares the actor's role rank (viewer 0, admin 1, owner 2).

Errors ([`core/errors.py`](../../apps/api/src/apiforge_server/core/errors.py)): services
raise `AppError` subclasses (`NotFoundError` 404, `ConflictError` 409,
`AuthenticationError` 401, `PermissionDeniedError` 403, `GoneError` 410,
`RateLimitedError` 429) or domain errors (`SpecRejectedError`, `SpecTooLargeError`,
`ReportHasErrorsError`). One handler maps each to the envelope; request validation errors
become 422 `validation_error`; an `IntegrityError` that slipped past a service check
becomes 409 `conflict` (the constraint name is logged, never the values);
`ObjectNotFoundError` from storage becomes 410 `content_expired`; anything else is 500
`internal_error` with the traceback only in the log.

## Domains

### projects

- `analysis.analyze(kv, data, filename)`: SHA-256, lint cache lookup, otherwise
  `_analyze` in a thread: `spec_inputs` (single document or zip bundle), `loader.load`,
  `normalize.normalize`, `fidelity.canonical_operations(bundled_document(...))` for the
  fingerprints, and a summary of operations, tags, schemes and models. Generator errors
  become `SpecRejectedError` with the generator's code.
- `analysis.changes_between(old_summary, new_analysis)`: added, removed and changed
  operations from the fingerprints.
- `service.upload_spec`: size, file name, analyze, deduplicate by SHA-256, store, insert,
  audit, all described in [service.md](service.md#spec-versions).
- `service._projects_out`: projects with counts and their latest spec and generation in
  four queries, whatever the number of projects.

### generations

- `create_generation`: the report gate, options, the next number, audit.
- `claim(container, limit)`, `run(container, id)`, `process(container)`: the worker side
  ([service.md](service.md#the-worker)).
- `archive(...)` and `file_content(...)`: downloads and the file browser over the
  in-process `_ArchiveCache` (16 archives and 64 MiB, LRU, the newest entry always kept, keyed by SHA-256). Both routes answer 304 to a matching `If-None-Match` before reading storage (`etag()` builds `"<sha>"` and `"<sha>:<path>"`). `_unpack` strips the
  archive's top-level folder so manifest paths and archive paths match.

### auth, users, keys, audit

- `auth/service.authenticate`: lockout check (this address for this account, and the
  account as a whole), Argon2 verify in a thread (a dummy hash for unknown emails),
  failures counted atomically in SQL (an upsert into `login_failures` and
  `UPDATE ... RETURNING` on `users`): 5 from one address lock that address out of the
  account for 15 minutes, 50 from anywhere lock the account; audit rows for success and
  failure.
- `auth/router.login`: 20 attempts a minute per client address (KV limiter; passes if the
  KV store is down), session token in the response and the httpOnly cookie,
  `Cache-Control: no-store`.
- `users/service`: owner guards (never the last active owner; owners locked `FOR UPDATE`
  while counting), a role or access change bumps `session_version`.
- `keys/service`: `afk_<12 hex>_<secret>`, stored as `HMAC-SHA256(pepper, secret)`, the
  plaintext returned once.
- `audit/service.audit`: adds an `audit_log` row to the caller's session, so it commits
  with the change it describes; `list_entries` is keyset-paginated on `id` with an
  optional action prefix filter.

### overview and system

- `overview`: counts (projects, spec versions, operations across each project's latest
  version, generations in total and in the last 7 days by status, queued), the median
  duration of the week's successful generations (`percentile_cont`), and the latest
  generations and spec uploads.
- `system`: `/healthz` and `/health` (liveness), `/readyz` (Postgres within 2 s, Redis
  probed when configured but never decisive), `/metrics` (optional bearer token), and
  `/api/v1/system` (versions of the service and the generator, environment, cloud,
  storage, cache backend, worker settings, active key count, checks).

## The worker

[`worker.py`](../../apps/api/src/apiforge_server/worker.py) builds its own `Container`,
starts the Prometheus HTTP server on `WORKER_METRICS_PORT`, installs `SIGTERM` and
`SIGINT` handlers and loops: `run_due` runs every job whose interval elapsed or whose last
pass found work (today only `generations`), catching and counting any exception per job.
A pass that returns a positive count marks the job `busy`; while any job is busy the loop
starts the next pass at once, otherwise it waits up to `WORKER_POLL_S` for the stop flag. Job duration goes to
`apiforge_job_seconds{job}`.

## Interfaces at the edges

| Protocol | Implementations | Chosen by |
| -------- | --------------- | --------- |
| `ObjectStorage` ([`core/storage.py`](../../apps/api/src/apiforge_server/core/storage.py)): `put`, `get`, `delete` | `LocalStorage` (a directory; keys that resolve outside it are refused), `S3Storage` (boto3 in a thread, `ServerSideEncryption=aws:kms`, a missing key is `ObjectNotFoundError`) | `STORAGE=local\|s3` |
| `KV` ([`core/kv.py`](../../apps/api/src/apiforge_server/core/kv.py)): `get`, `mget`, `set`, `incr`, `hit`, `ping` | `RedisKV` (2 s socket timeouts, the sliding-window limiter), `MemoryKV` (LRU bounded by 20,000 entries and 64 MB, fixed-window counters) | `REDIS_URL` set or empty |

boto3 clients are built only from configuration
([`core/aws.py`](../../apps/api/src/apiforge_server/core/aws.py): region, optional
`AWS_ENDPOINT_URL`, path-style addressing when `S3_FORCE_PATH_STYLE`, 3 retries, 3 s
connect and 10 s read timeouts). There is no emulator branch anywhere in the code, and no
outbound HTTP client in the container.

## The web app

`apps/web` is a Next.js 15 App Router app (React 19, TypeScript strict, Tailwind v4,
shadcn/ui, TanStack Query v5). Routes in `src/app` stay thin; each screen lives in
`src/features/<domain>` (overview, projects, specs, generations, playground, keys, users,
audit, settings, auth) with its query hooks in `api.ts`; query keys and `staleTime`
classes are in `src/lib/query-keys.ts`. API types are generated from
`docs/api/openapi.yaml` (`pnpm gen:api`), never written by hand. In production the
Next.js server rewrites `/api/*` to the API (`API_INTERNAL_URL`), so the browser talks to
one origin and the session cookie stays first-party.

Screens, from the API's point of view:

| Screen | Reads | Writes |
| ------ | ----- | ------ |
| Overview | `GET /api/v1/overview` | |
| Projects | `GET /api/v1/projects`, `GET /api/v1/examples` | `POST /api/v1/projects`, `POST /api/v1/projects/from-example` |
| Spec versions | `GET .../specs`, `GET .../specs/{n}` (report, operations), `GET .../specs/{n}/content`, `GET .../diff` | `POST .../specs`, `POST .../specs/text` |
| Generations | `GET .../generations`, `GET .../generations/{n}`, `GET .../file?path=`, `GET .../archive` | `POST .../generations` |
| Playground | `GET /api/v1/examples`, `GET /api/v1/examples/{name}` (the Load menu) | `POST /api/v1/lint` (stores nothing) |
| API keys | `GET /api/v1/keys` | `POST`, `PATCH`, `POST .../revoke` |
| Users | `GET /api/v1/users` | `POST`, `PATCH` (owner) |
| Audit log | `GET /api/v1/audit` | |
| Settings | `GET /api/v1/system`, `GET /api/v1/auth/me` | `POST /api/v1/auth/password` |

## Important algorithms at a glance

| What | Where | In one line |
| ---- | ----- | ----------- |
| Safe YAML | `loader._SafeLoader` | `SafeLoader` without the timestamp resolver, with an alias budget (10,000) and a value budget (2,000,000) after loading |
| Local `$ref` resolution | `loader.Bundle.resolve` | URLs refused, paths normalized and kept inside the spec's folder, RFC 6901 pointers |
| Escaping | `naming.py_literal`, `docstring`, `comment` | Spec text becomes a Python literal, an escaped docstring or a comment line, never code |
| Deterministic zip | `archive.build_zip` | Sorted entries, fixed time and mode, pinned compression level |
| Generation gap | `writer.plan_write` | Hash each generated file on disk against the lock; append stubs for new operations; report removed ones |
| Fidelity | `fidelity.canonical_operations`, `compare` | Canonical form per operation, refs inlined, `allOf` merged, nullability unified |
| Version diff | `projects/analysis.changes_between` | Per-part fingerprints of the canonical form |
| Job claim | `generations/service.claim` | `FOR UPDATE SKIP LOCKED` plus a lease and an attempt counter |
| Config cache | `core/cache.ConfigCache` | Per-process TTL cache, single flight per key, invalidated cluster-wide by a version stamp |
| Rate limit | `limits/limiter.Limiter` | Sliding-window counter in one Lua script |
