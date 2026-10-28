# Quickstart: run APIForge locally

Two ways to use APIForge: the CLI on its own (no Docker, no account, no network), or the
whole self-hosted service on Docker Compose. Both produce the same archive for the same
spec and options.

- [The CLI in two minutes](#the-cli-in-two-minutes)
- [The service](#the-service)
- [Useful targets](#useful-targets)

## The CLI in two minutes

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd apps/forge
uv sync
uv run apiforge examples --copy ~/specs        # the five bundled example specs
uv run apiforge lint ~/specs/petstore.yaml
uv run apiforge generate --spec ~/specs/petstore.yaml --output ~/pet-store
```

```
Pet Store 1.0.0: 4 operations, 4 models
No findings.
```

Then run the project you just generated:

```bash
cd ~/pet-store
uv sync
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000/docs. Every operation already answers with example data that
matches the spec. `make check` in the project runs ruff, mypy and its tests; from the
APIForge checkout, `uv run apiforge verify ~/pet-store` does the same and prints a
line per step.

Next: [cli.md](cli.md) for every command and flag, and
[generated-project.md](generated-project.md) for what is in the project and how to make it
yours.

## The service

### Prerequisites

| Tool | Version | Used for |
| ---- | ------- | -------- |
| Docker with Compose v2 | recent | The whole stack |
| uv | 0.5 or newer | Running tests outside containers (optional) |
| Node 22 and pnpm 9 | | Web app development and e2e (optional) |

Nothing else is installed on the host: Postgres, Redis, the AWS emulator and Terraform
all run in containers.

### 1. Start the stack

```bash
make up
```

This writes `deploy/compose/.env` with random local secrets (`make env`, once), then
starts, in order:

| Service | What it does | Host port |
| ------- | ------------ | --------- |
| `postgres` | PostgreSQL 16 | 4642 |
| `redis` | Redis 7 (optional at run time) | 4679 |
| `floci` | AWS emulator: S3, KMS, Secrets Manager | 4666 |
| `terraform` | One shot: applies `infra/terraform/envs/local-floci` to Floci (artifacts bucket, KMS key, secrets) | |
| `migrate` | One shot: `apiforge-server migrate` | |
| `api` | The REST API | 4630 |
| `worker` | Runs queued generations | |
| `web` | The web app (proxies `/api` to the API) | 4610 |

When it is up:

```
  dashboard  http://localhost:4610
  api        http://localhost:4630/api/v1
  api docs   http://localhost:4630/docs
```

Every port can be changed in `deploy/compose/.env` (`AF_WEB_PORT`, `AF_API_PORT`,
`AF_PG_PORT`, `AF_REDIS_PORT`, `AF_FLOCI_PORT`).

### 2. Load the demo

```bash
make demo
```

`apiforge-server seed-demo` creates:

- three users, one per role: `owner@apiforge.local`, `admin@apiforge.local`,
  `viewer@apiforge.local`, all with the password printed by `make demo`
  (`AF_DEMO_PASSWORD` in `deploy/compose/.env`);
- a read-only API key named "CI download (read only)", printed once the first time;
- one project per bundled example spec: Pet Store (three spec versions, generations with
  and without `--db`), Bookstore (two versions), Warehouse Inventory (`--db`), Secure Notes
  and Edge Cases (a spec whose lint report has findings);
- real generations, run through the worker's own code path, so every archive can be
  browsed and downloaded.

Running it again changes nothing.

### 3. Look around

Sign in at http://localhost:4610 as the admin.

1. **Overview:** projects, spec versions, operations, generations this week, the queue and
   recent activity.
2. **Projects, Pet Store, Spec versions:** version 3 shows its lint report and what changed
   since version 2 (`DELETE /pets/{petId}` added).
3. **Generations:** open the latest one, browse the files (yours and generated are marked),
   download the zip.
4. **Playground:** paste a spec and see the report without saving anything.
5. **Edge Cases:** a report with warnings and notes, each with a JSON pointer into the spec.

Sign in as the viewer to see what read-only access looks like.

### 4. Try the API

```bash
KEY=afk_...   # printed by make demo
curl -s -H "Authorization: Bearer $KEY" http://localhost:4630/api/v1/projects | python3 -m json.tool
curl -s -H "Authorization: Bearer $KEY" http://localhost:4630/api/v1/projects/pet-store/generations
curl -s -H "Authorization: Bearer $KEY" -o pet-store.zip \
  http://localhost:4630/api/v1/projects/pet-store/generations/2/archive
```

The key reads everything and changes nothing. The interactive API docs are at
http://localhost:4630/docs. [examples/](../../examples/README.md) has a CI script that
downloads the latest archive and checks its hash.

### 5. Stop

```bash
make down
```

This stops every container and deletes the volumes (database, stored specs and archives,
emulator state). `deploy/compose/.env` is kept.

### Without Redis

Set `AF_REDIS_URL=` (empty) in `deploy/compose/.env` and run `make up` again: rate limits,
the lint cache and config invalidation then run in process
([configuration.md](configuration.md#database-and-cache)). The `redis` container still
starts, but nothing uses it.

## Useful targets

| Target | What it does |
| ------ | ------------ |
| `make logs SERVICE=worker` | Follow one service's logs |
| `make ps` | Container status |
| `make admin EMAIL=you@example.com` | Create or reset an owner on the local stack |
| `make test`, `make test-integration`, `make test-matrix` | The test gates ([testing.md](testing.md)) |
| `make bench` | Latency and throughput of the running stack |
| `make openapi` | Regenerate `docs/api/openapi.yaml` |
| `make` | Every target with its description |

Problems starting the stack: [troubleshooting.md](troubleshooting.md#local-stack-problems).
