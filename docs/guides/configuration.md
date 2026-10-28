# Configuration

Every API and worker setting is an environment variable, validated once at boot by
[`core/config.py`](../../apps/api/src/apiforge_server/core/config.py) (pydantic-settings,
case-insensitive names, unknown variables ignored). Security-relevant settings are
enforced by [production boot guards](#production-boot-guards). The API and the worker read
the same settings; the generator (CLI) has no settings beyond its flags
([cli.md](cli.md)).

- [Core](#core)
- [Database and cache](#database-and-cache)
- [Sessions and keys](#sessions-and-keys)
- [AWS and storage](#aws-and-storage)
- [Request limits](#request-limits)
- [Worker and generations](#worker-and-generations)
- [Observability](#observability)
- [Process and CLI variables](#process-and-cli-variables)
- [Web app](#web-app)
- [Local stack](#local-stack)
- [Test suite](#test-suite)
- [The generated project's settings](#the-generated-projects-settings)
- [Production boot guards](#production-boot-guards)

## Core

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `ENVIRONMENT` | `development` | `development`, `test` or `production`. Production turns on the boot guards |
| `APIFORGE_CLOUD` | `local` | `local`, `floci` or `aws`: where the deployment runs. With `aws`, `AWS_ENDPOINT_URL` must be unset in production. Reported by `/api/v1/system` |
| `LOG_LEVEL` | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, ...) |
| `CORS_ORIGINS` | `http://localhost:4610` | Comma-separated origins allowed to call the API from a browser with credentials. The web app proxies `/api` on its own origin, so this matters only for other browser clients |

## Database and cache

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `DATABASE_URL` | `postgresql+asyncpg://apiforge:apiforge@localhost:4642/apiforge` | SQLAlchemy async URL. Postgres 16 is the supported database |
| `DB_POOL_SIZE` | `10` | Connections kept per process |
| `DB_MAX_OVERFLOW` | `20` | Extra connections per process under load. Size `(api tasks + workers + migrate) x (pool + overflow)` below the server's `max_connections` |
| `REDIS_URL` | empty | Redis or Valkey URL (`redis://` or `rediss://` for TLS). Empty means no Redis: rate limits, the lint cache and config invalidation run in process, which is exact for one single-process API replica. Use Redis for several replicas or `WEB_CONCURRENCY` above 1 |

## Sessions and keys

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `SESSION_SECRET` | a development value | HS256 key that signs web app sessions. At least 32 random characters in production; changing it signs everyone out |
| `API_KEY_PEPPER` | a development value | HMAC key for API key secrets. At least 32 random characters in production, different from `SESSION_SECRET`. Changing it invalidates every API key |
| `SESSION_TTL_HOURS` | `12` | Session lifetime |
| `COOKIE_SECURE` | `false` | Send the session cookie only over HTTPS. Must be `true` in production |
| `DEFAULT_RPM_LIMIT` | `600` | Requests a minute for an API key without its own `rpm_limit` |

Sign-in is limited to 20 attempts a minute per client address and locks an account for 15
minutes after 5 consecutive failures. These are constants in code, not settings.

## AWS and storage

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `STORAGE` | `local` | `local` (a directory) or `s3`. Production requires `s3` |
| `LOCAL_STORAGE_DIR` | `./.data/artifacts` | The directory for `STORAGE=local` (`/data/artifacts`, a named volume, in Compose) |
| `ARTIFACTS_BUCKET` | `apiforge-local-artifacts` | The bucket for `STORAGE=s3`: uploaded specs under `specs/`, archives under `archives/` |
| `AWS_REGION` | `us-east-1` | Region for the S3 client |
| `AWS_ENDPOINT_URL` | unset | An S3-compatible endpoint (Floci locally: `http://floci:4566`). Unset on AWS |
| `S3_FORCE_PATH_STYLE` | `false` | Path-style bucket addressing (needed by Floci) |

Credentials come from the standard AWS chain (task role on ECS, a profile locally, or
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`); never put them in the app's settings.
Objects are written with `ServerSideEncryption=aws:kms`: S3 uses the bucket's default KMS
key, and the app never calls KMS itself. Archive retention is a bucket lifecycle rule
(`archive_expiration_days` in Terraform, 90 by default), not an app setting.

## Request limits

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `MAX_BODY_BYTES` | `25000000` | Any request body over this is refused with 413 `payload_too_large` (chunked bodies are counted as they arrive) |
| `MAX_SPEC_BYTES` | `5242880` (5 MiB), at least 1024 | A spec over this is refused with 413 `spec_too_large`, whether uploaded as a file, sent as text (`POST .../specs/text`) or linted in the playground (`POST /api/v1/lint`); the message names `MAX_SPEC_BYTES`. The generator's own per-document limit is also 5 MiB, so raising this does not let a single document past 5 MiB; it can let a larger zip bundle through (up to the generator's 20 MiB bundle limit) |

## Worker and generations

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `WORKER_CONCURRENCY` | `2` (1 to 32) | Generations one worker runs at once, each in a thread |
| `WORKER_POLL_S` | `1.0` (above 0) | How long an idle worker waits before looking for queued generations again. While passes find work, the next pass runs right away |
| `GENERATION_TIMEOUT_S` | `120` (at least 10) | How long the worker waits for one generation before recording `generation_timeout`. The lease is this plus 30 s |
| `GENERATION_MAX_ATTEMPTS` | `3` (1 to 10) | How many times a generation may be claimed (a crashed worker's job is retried after its lease) before it fails with `worker_lost` |
| `WORKER_METRICS_PORT` | `9464` (0 to 65535) | Port of the worker's own Prometheus endpoint; `0` turns it off |

## Observability

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `METRICS_TOKEN` | unset | When set, the API's `/metrics` requires `Authorization: Bearer <token>`. Always set on a public deployment |
| `OTEL_ENABLED` | `false` | Install the OpenTelemetry SDK with an OTLP exporter. Configure it with the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` |

## Process and CLI variables

Read by `apiforge-server` itself, outside `Settings`:

| Variable | Default | Used by | Meaning |
| -------- | ------- | ------- | ------- |
| `PORT` | `4630` | `serve` | Listening port (`--port` overrides it; Compose and ECS use 8080 inside the container) |
| `WEB_CONCURRENCY` | `1` | `serve` | uvicorn worker processes. Keep 1 and scale with more containers, so Prometheus counters and in-process caches stay exact |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | `serve` | Addresses whose `X-Forwarded-For` is trusted (the load balancer's network; the VPC CIDR on AWS). Never `*` on a host reachable without a proxy |
| `APIFORGE_OWNER_PASSWORD` | prompt | `create-owner` | The owner's password, instead of an interactive prompt |
| `DEMO_PASSWORD` (or `AF_DEMO_PASSWORD`) | required | `seed-demo` | Password of the three demo users. `seed-demo` refuses `ENVIRONMENT=production` |

`bench.py` reads `API_URL` (`http://localhost:4630`), `BENCH_EMAIL`
(`admin@apiforge.local`), `DEMO_PASSWORD` and `BENCH_GENERATIONS` (20).

## Web app

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `API_INTERNAL_URL` | `http://localhost:4630` | Where the Next.js server forwards `/api/*` (server side only; `http://api:8080` in Compose, the ALB URL on AWS) |
| `PORT` | `8080` in the container | Listening port |

## Local stack

`make env` writes `deploy/compose/.env` once (it never overwrites it) with
`SESSION_SECRET`, `API_KEY_PEPPER` (64 random characters each, distinct) and
`AF_DEMO_PASSWORD`. Optional overrides in the same file:

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `AF_WEB_PORT` | `4610` | Web app |
| `AF_API_PORT` | `4630` | API |
| `AF_PG_PORT` | `4642` | Postgres |
| `AF_REDIS_PORT` | `4679` | Redis |
| `AF_FLOCI_PORT` | `4666` | Floci |
| `AF_LOG_LEVEL` | `INFO` | `LOG_LEVEL` for api, worker and migrate |
| `AF_REDIS_URL` | `redis://redis:6379/0` | Set it empty to run the stack without Redis |

`make tf-aws-on-floci` starts its throwaway Floci on `TF_FLOCI_PORT` (4696).

## Test suite

Read by `apps/api/tests/integration/conftest.py` and `scripts/test-matrix.sh`:

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `TEST_DATABASE_URL` | the local `apiforge_test` database on port 4642 | Must name a database containing `test` on a local host (`localhost`, `127.0.0.1`, `postgres`) |
| `ALLOW_REMOTE_TEST_DB` | unset | `true` allows a non-local test database host |
| `TEST_REDIS_URL` | `redis://localhost:4679/15` | Redis for the suite |
| `TEST_CACHE` | `redis` | `redis` or `memory` (no Redis at all) |
| `TEST_STORAGE` | `local` | `local` or `s3` |
| `TEST_AWS_ENDPOINT` | unset | The S3 endpoint for `TEST_STORAGE=s3` (Floci) |
| `TEST_ARTIFACTS_BUCKET` | `apiforge-local-artifacts` | The bucket for `TEST_STORAGE=s3` |
| `AF_TEST_DB` | `apiforge_test` | The database `scripts/test-db.sh` creates |

## The generated project's settings

A project generated by APIForge reads its own settings from environment variables (and a
`.env` file in development) through its `app/config.py`, which is yours to change. Only
the settings the spec needs are generated: the JWT settings appear when the spec has a
bearer, OAuth2 or OpenID Connect scheme, `API_KEYS` with an API key scheme,
`BASIC_USERS` with HTTP basic, and `DATABASE_URL` with `--db`.

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `APP_ENV` | `development` | `development`, `test` or `production`. Production refuses the unsafe values listed below |
| `CORS_ORIGINS` | `[]` | JSON list of browser origins allowed to call the API (`["https://app.example.com"]`). Empty adds no CORS middleware; `*` is refused in production |
| `JWT_SECRET` | empty | HS256 secret that verifies bearer tokens. Empty accepts no token (fail closed). At least 32 characters in production |
| `JWT_ALGORITHM` | `HS256` | Algorithm passed to PyJWT |
| `JWT_AUDIENCE` | unset | When set, tokens must carry this `aud` |
| `API_KEYS` | `[]` | JSON list of accepted API keys (`["key-one", "key-two"]`), compared in constant time. Each at least 24 characters in production |
| `BASIC_USERS` | `{}` | JSON object of HTTP basic users and passwords (`{"admin": "a-long-password"}`). Each password at least 16 characters in production |
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | SQLAlchemy async URL; the generated Compose file sets a Postgres URL |

Tokens must carry `sub` and `exp`; scopes are read from a space-separated `scope` claim or
a `scopes` list. How to change any of this is in
[generated-project.md](generated-project.md#authentication).

## Production boot guards

With `ENVIRONMENT=production` the API, the worker, `migrate`, `revision`, `create-owner`
and `seed-demo` refuse to start when (`openapi` builds the app with default settings and
skips the guards):

| Problem | Message |
| ------- | ------- |
| `SESSION_SECRET` or `API_KEY_PEPPER` is empty, a placeholder (`change-me`, `dev`, `secret`, `replace-with-output-of-make-env`), contains `not-for-production` or is shorter than 32 characters | `<NAME> must be a random value of at least 32 chars` |
| `SESSION_SECRET` equals `API_KEY_PEPPER` | `SESSION_SECRET and API_KEY_PEPPER must differ` |
| `APIFORGE_CLOUD=aws` with `AWS_ENDPOINT_URL` set | `AWS_ENDPOINT_URL must be unset when APIFORGE_CLOUD=aws` |
| `COOKIE_SECURE=false` | `COOKIE_SECURE must be true in production` |
| `STORAGE=local` | `STORAGE must be s3 in production (local disk is per container)` |

All problems are reported at once, in one `unsafe production configuration: ...` error.
The AWS environments set `ENVIRONMENT=production`, `STORAGE=s3`, `COOKIE_SECURE=true` and
generate both secrets; the local stack runs with `ENVIRONMENT=development`.
