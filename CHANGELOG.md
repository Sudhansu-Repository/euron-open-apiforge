# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-28

First public release: the generator and its CLI, the API and worker, and the web app.

### Added

- `euron-apiforge` (import `apiforge`): OpenAPI 3.0 and 3.1 in, a FastAPI project out.
  JSON or YAML, one file, a folder or a zip with relative `$ref`s. Deterministic: the same
  spec and options give a byte-identical project and archive.
- Generated projects: Pydantic v2 models with the spec's validation rules (formats, enums,
  lengths, ranges, patterns, `multipleOf`, `additionalProperties`, `allOf` inheritance,
  `oneOf`/`anyOf` with and without a discriminator, nullable fields, recursive models,
  separate input models for `readOnly`/`writeOnly`); routers per tag with path, query,
  header and cookie parameters, JSON, form and multipart bodies, file upload and
  download, every documented response; security for bearer, OAuth2 and OpenID Connect
  (JWT with scopes), API keys in a header, query or cookie, and HTTP basic; settings that
  refuse unsafe production values.
- A mock on day one: every handler starts by returning a schema-valid example from the
  spec's examples or synthesized from the schema, including strings that match patterns.
- `--db`: SQLAlchemy 2 async tables, an Alembic migration and working CRUD (paging, and
  equality filters matched to columns by their wire name; JSON columns are never filters)
  for collection resources, SQLite by default and Postgres in Compose. The generated tests
  pass on both, and the Dockerfile carries `alembic.ini` and `migrations/` so the image can
  run `alembic upgrade head`.
- Generated tests: a contract test per operation, validation tests, auth tests, a CRUD
  round trip per resource, and `test_spec.py`, which compares the OpenAPI document the app
  serves with the spec (approximations listed explicitly in `ACCEPTED`).
- Project files: `pyproject.toml` (uv), ruff and mypy `--strict` configured and passing,
  Dockerfile, Compose, `.env.example`, Makefile, README with the operations table, GitHub
  Actions workflow.
- The generation gap: `app/generated/` and `tests/generated/` are rewritten on every
  generation; handlers, auth, config, main and project files are yours and never
  overwritten; new operations get stubs appended; removed operations are reported;
  `apiforge.lock` detects hand-edited generated files.
- The lint report: every construct APIForge approximates or cannot express, every guess it
  made, and every problem that would change the API, each with a severity, a stable code
  and a JSON pointer; errors block generation until the report is accepted.
- CLI `apiforge lint | generate | diff | verify | examples`, offline, no account. Every
  refusal, including `verify` without uv (`tool_missing`), is a message and exit code 1.
- Six bundled example specs: a pet store, a bookstore (OpenAPI 3.1, polymorphism, files,
  OAuth2 scopes), a CRUD-heavy inventory, a notes API with every security scheme, an
  edge-case spec for the report, and Team Tasks (AND and OR security requirements, an
  unsupported digest scheme, read-only fields a PUT keeps, paging without defaults,
  integer enum parameters, a default-only operation).
- Service (`apiforge_server`): projects with numbered spec versions (linted on upload,
  stored in object storage, idempotent by SHA-256, compared with the previous version by
  operation fingerprints), a diff between any two versions, a lint playground, the
  bundled examples (listed, read one by one with `GET /api/v1/examples/{name}`, loadable in
  the playground, or turned into projects). Uploads, text uploads and the playground share
  one size limit, `MAX_SPEC_BYTES`.
- Generations queued by the API and run by a worker that claims rows with
  `FOR UPDATE SKIP LOCKED` and a lease, retries a crashed worker's job up to
  `GENERATION_MAX_ATTEMPTS`, drains a backlog pass after pass without waiting between
  passes, and records every failure with a code and an explanation plus one
  `generation failed` log line (the CloudWatch alarm counts them); deterministic zip
  archives, byte-identical to the CLI's, served with the SHA-256 as the ETag and revalidated
  on every use (a 304 costs no storage read); a file browser over the archive, with its own
  ETags and 304s and an in-process cache bounded by count and bytes.
- Web app: overview, projects, spec versions with the lint report and changes,
  generations with a file browser and download, playground, API keys, users, audit log
  and settings; light and dark; down to phone width.
- Platform: owner, admin and viewer roles, read-only `afk_` API keys with per-key rate
  limits, CSRF protection, an append-only audit log, Prometheus metrics for the API and the
  worker, JSON logs with request ids, `/healthz`, `/health` and `/readyz`, optional
  OpenTelemetry.
- Redis optional: rate limits, the lint cache (by generator version and spec SHA-256,
  1 hour) and the config cache version stamp fall back to process memory.
- Local stack on Docker Compose with Floci (S3, KMS, Secrets Manager) provisioned by
  Terraform; `make demo` with users, an API key and projects with history (`seed-demo`
  refuses `ENVIRONMENT=production`).
- `make test-corpus` runs every generated `--db` project's tests on SQLite and again on
  Postgres.
- Terraform modules for network, database, cache, storage (one artifacts bucket: specs
  kept, archives expiring after 90 days), KMS, secrets, ECR, service (ECS Fargate api,
  worker and web behind an ALB with WAF) and observability, with `local-floci`, `aws-dev`
  and `aws-prod` environments.

### Security

- Specs are untrusted: safe YAML (no tags), size, depth, alias and value budgets, zip
  sizes checked before decompression, `$ref`s only inside the spec's own files. URL
  `$ref`s are refused; the server has no outbound HTTP client and never executes generated
  code.
- Spec text reaches generated code only through escaping filters in a sandboxed, strict
  template environment; property tests with hostile strings.
- Upload file names sanitized; storage keys built from ids; the file browser serves only
  paths in a generation's manifest.
- argon2id passwords, atomic lockout and per-address throttling, sessions ended on
  sign-out, password change or role change; API keys stored as peppered HMACs; production
  boot guards refuse unsafe configuration.

Hardening from an independent review before release:

- `$ref` fan-out is bounded: inlining stops at 500,000 schema nodes per spec, and a spec
  whose schemas reference each other many times over is refused with `spec_too_complex`
  in a fraction of a second instead of taking gigabytes of memory.
- `apiforge.lock` entries are trusted only for paths under `app/generated/` and
  `tests/generated/` inside the project, so a hostile lock file cannot make
  `apiforge generate` compare or delete files elsewhere, with or without `--force`.
- Zips with encrypted entries, unsupported compression or corrupt members, and specs with
  unpaired UTF-16 surrogates, are refused as `spec_unreadable` (422) with a message instead
  of a 500; a non-ASCII digit in a JSON pointer is a ref error.
- Archive and file-view responses are `Cache-Control: private, no-cache` (revalidated by
  ETag, still a 304 without a storage read), because a deleted project's slug, and so the
  same URL, can be reused.
- Worker results are fenced: no transaction is held while the generator runs, a worker
  whose lease expired records nothing, and a generation whose project was deleted
  mid-run removes the archive it stored.

### Fixed

- Parameter patterns are compiled with Python's `re` (`pattern=re.compile(...)`), so
  look-aheads such as `^(?!admin)` work in query and path parameters, as they already did
  in models.
- A spec with no paths generates a valid project; unused imports are removed only in the
  generated folders; a formatting failure reports ruff's output; DEL is escaped in the
  generated `pyproject.toml`.

### Production readiness

Service and infrastructure:

- `aws-deploy.sh` migrates before it rolls out: the services stay on the running tag while
  the migrate task runs on the new one (`migrate_image_tag`), then the services move.
  Migrations must stay backward compatible with the previous release; they take a Postgres
  advisory lock and run with `lock_timeout = '10s'`.
- Request bodies: `MAX_BODY_BYTES` (now 8 MiB) only on the lint and spec upload routes;
  every other route, sign-in included, is capped at `MAX_SMALL_BODY_BYTES` (64 KiB) before
  parsing.
- The production guard also refuses `*` or non-https CORS origins, the default or a
  localhost `DATABASE_URL`, and an unset `METRICS_TOKEN`.
- Sign-in lockout per account and client address (5 failures, new `login_failures`
  table); the account itself locks only at 50 failures, so one client cannot lock an owner
  out for everyone.
- `make aws-admin` hashes the owner password locally (`apiforge-server hash-password`) and
  the task receives only `APIFORGE_OWNER_PASSWORD_HASH`; RDS logs no bind values.
- Workers autoscale on CPU (1 to 4 in prod); every ECS service has a `not-running` alarm;
  aws-prod warns when `alarm_email` is unset; database pools are sized for a deploy at
  full scale; the ALB routes `/health` to the api; CI actions updated.

Generated projects:

- Security requirements follow OpenAPI: AND inside a requirement, OR across them. A scheme
  APIForge cannot check fails closed through `security.unsupported` (401, overridable).
  Scopes are decided once every credential is seen (403 only when an alternative
  authenticated without the scope), with a challenge matching the route's schemes.
- In production: 501 for handlers that still return mocks, docs off unless
  `DOCS_ENABLED`, an explicit non-SQLite `DATABASE_URL` with `--db`, HS256 to HS512 only.
- New settings `DOCS_ENABLED`, `MAX_BODY_BYTES`, `JWT_ISSUER`, `JWT_LEEWAY_SECONDS`,
  `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_STATEMENT_TIMEOUT_MS`; tokens accept `scope`,
  `scp` or `scopes`. Alembic reads only the database settings.
- JSON error bodies that never echo input or SQL (409, 413, 422 without `input`, a bare
  500) and security headers on every response (`app/generated/middleware.py`).
- `--db` paging defaults and bounds, and a PUT that keeps the id and read-only columns.
- `uv.lock` is used when committed (`uv sync --locked` in the Dockerfile and CI).
- Default-only operations answer 200 with the default body; number and boolean enums in
  parameters accept their text (`app/generated/wire.py`).
- The formatter's ruff calls time out after 120 s.

[Unreleased]: https://github.com/euron-sde-team/euron-open-apiforge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/euron-sde-team/euron-open-apiforge/releases/tag/v0.1.0
