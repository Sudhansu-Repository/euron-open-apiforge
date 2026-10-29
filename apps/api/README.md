# apiforge_server (API, worker and CLI)

The Python package behind the Euron Open APIForge service: the REST API (`/api/v1`) for
projects, spec versions, generations, the lint playground, users, API keys and the audit
log; Prometheus `/metrics`; the background worker that runs queued generations; the
`apiforge-server` CLI; the demo seed and the benchmark. It imports the generator,
[`apps/forge`](../forge) (`euron-apiforge`), as a path dependency, so its archives are
byte-identical to the `apiforge` CLI's.

```bash
uv sync
uv run apiforge-server --help       # serve, worker, migrate, revision, openapi, create-owner, hash-password, seed-demo
uv run pytest tests/unit            # no database, no network
make -C ../.. test-integration      # real Postgres and Redis (started if needed)
```

| Command | What it does |
| ------- | ------------ |
| `apiforge-server serve [--host --port --workers]` | The API on `PORT` (4630 by default; 8080 in the container), `WEB_CONCURRENCY` processes (1) |
| `apiforge-server worker` | Runs queued generations; serves its own metrics on `WORKER_METRICS_PORT` (9464) |
| `apiforge-server migrate` | Apply the Alembic migrations |
| `apiforge-server revision -m "..."` | Autogenerate a migration against a migrated database (`make migration`) |
| `apiforge-server openapi` | Print the OpenAPI document (`make openapi` writes `docs/api/openapi.yaml`) |
| `apiforge-server create-owner --email ... [--name ...]` | Create an owner, or reset a user to owner with a new password: `APIFORGE_OWNER_PASSWORD_HASH` (an argon2id hash from `hash-password`; anything else is refused), else `APIFORGE_OWNER_PASSWORD`, else a prompt |
| `apiforge-server hash-password` | Print the argon2id hash of `APIFORGE_OWNER_PASSWORD` (or a prompted password), checked against the password policy. `scripts/aws-run-task.sh` runs it locally so an ECS task override carries only the hash |
| `apiforge-server seed-demo` | Demo users, a read-only API key, projects from the bundled specs with spec history and real generations (`DEMO_PASSWORD`; idempotent). Refuses `ENVIRONMENT=production` |
| `python -m apiforge_server.bench` | Lint, upload, generation and download latency against a running stack (`make bench`) |

## Developing

- Run the API against the local stack's Postgres and Redis:

  ```bash
  make -C ../.. up                    # or just: scripts/test-db.sh for postgres and redis
  DATABASE_URL=postgresql+asyncpg://apiforge:apiforge@localhost:4642/apiforge \
  REDIS_URL=redis://localhost:4679/0 \
    uv run apiforge-server serve --port 4631
  ```

  (another port than 4630 if the Compose API is running). Run `uv run apiforge-server worker`
  in a second shell with the same variables, or no generation will finish.
- Changing the generator? `apps/forge` is installed editable, so the service picks up your
  changes on restart.
- Changing an endpoint? `make -C ../.. openapi` (a unit test checks drift), then
  `pnpm gen:api` in `apps/web`.
- Changing a model? `make -C ../.. migration MSG="what changed"` and review the revision.

## Layout

```
src/apiforge_server/
  core/          config (settings and boot guards), db, kv (Redis or memory), cache (ConfigCache),
                 security, storage (local or S3), aws, middleware, errors, logs, tracing
  projects/      projects, spec uploads and versions, diffs, the playground, examples;
                 analysis.py is the bridge to the generator (lint, fingerprints, lint cache)
  generations/   queueing, the worker's claim and run, archives, the file browser
  auth/ users/ keys/ audit/ overview/ system/ observability/ limits/
  demo/seed.py   migrations/   main.py   worker.py   cli.py   bench.py   openapi.py
tests/unit/        core, the OpenAPI drift test
tests/integration/ projects, generations, admin, hardening, backends, worker and CLI
```

The design is in the [LLD](../../docs/architecture/LLD.md) and
[service.md](../../docs/architecture/service.md); every setting is in the
[configuration reference](../../docs/guides/configuration.md); the conventions are in
[CONTRIBUTING.md](../../CONTRIBUTING.md).
