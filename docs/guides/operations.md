# Operations

Running APIForge day to day: the processes, the worker and its retries, stuck
generations, metrics, alarms, logs, backups, archive retention and secrets. Deployment is
in [deploy-aws.md](deploy-aws.md); settings in [configuration.md](configuration.md).

- [Processes](#processes)
- [The worker](#the-worker)
- [Retries and failures](#retries-and-failures)
- [Stuck generations](#stuck-generations)
- [Health checks](#health-checks)
- [Metrics](#metrics)
- [Alarms](#alarms)
- [Logs](#logs)
- [Backups and restore](#backups-and-restore)
- [Archive retention](#archive-retention)
- [Scaling](#scaling)
- [Rotating secrets](#rotating-secrets)
- [Users, owners and API keys](#users-owners-and-api-keys)
- [Upgrading the generator](#upgrading-the-generator)

## Processes

| Process | Command | Replicas | Notes |
| ------- | ------- | -------- | ----- |
| api | `apiforge-server serve` | 1 or more | Stateless; one uvicorn process per container (`WEB_CONCURRENCY=1`) |
| worker | `apiforge-server worker` | 1 or more | Runs queued generations; its own `/metrics` on 9464 |
| web | Next.js standalone server | 1 or more | Proxies `/api` to the API |
| migrate | `apiforge-server migrate` | one-off | Before a new version starts (Compose: a one-shot service; AWS: `make aws-migrate`) |

## The worker

The worker claims up to `WORKER_CONCURRENCY` (2) queued generations per pass and runs them
at once, each in its own thread. While passes find work it starts the next pass right away,
so a backlog drains back to back; an idle worker looks again every `WORKER_POLL_S` (1 s)
([service.md](../architecture/service.md#the-worker)). A generation goes
`queued` to `running` to `succeeded` or `failed`.

- **Several workers are safe.** Claims use `FOR UPDATE SKIP LOCKED`, so each queued
  generation goes to exactly one worker. Add replicas for throughput.
- **Shutdown.** `SIGTERM` finishes the generations in hand, then exits. On ECS the worker
  has 120 s (the ECS maximum) before `SIGKILL`; a generation cut off there is claimed
  again after its lease.
- **No worker, no generations.** Requests are accepted (202) and stay `queued`. The
  overview shows the queue, and `apiforge_generation_queue` is above 0.

## Retries and failures

A generation is retried only when its worker disappeared. Errors the worker can see are
recorded once and not retried, because generation is deterministic: the same input fails
the same way.

| Situation | What happens | What to do |
| --------- | ------------ | ---------- |
| The spec's report has errors | The request is refused (422 `report_has_errors`) unless `accept_report` is true | Fix the spec, or accept the report |
| The generator refuses the input | `failed` with the generator's code and message | Read the message; it says what to change |
| Longer than `GENERATION_TIMEOUT_S` (120 s) | `failed`, `generation_timeout` | Raise `GENERATION_TIMEOUT_S`, or split the spec |
| An unexpected exception (a bug, storage down) | `failed`, `internal_error`; traceback in the worker log under `generation raised` | Check storage; otherwise report it with the spec |
| The worker died mid-generation | The row stays `running`; after its lease (`GENERATION_TIMEOUT_S` + 30 s) another claim takes it, `attempts` goes up | Nothing: it recovers on its own |
| The worker died `GENERATION_MAX_ATTEMPTS` (3) times on it | `failed`, `worker_lost` | Look for OOM kills or crashes in the worker's logs around the attempts; report it with the spec if the spec is the cause |

Every failed generation, whatever the cause, writes one `generation failed` WARNING line
with `generation_id`, `error_code` and `attempts`.

To retry a failed generation, request a new one (the web app's Generate button, or
`POST /api/v1/projects/{slug}/generations`). Same spec and options give the same archive.

## Stuck generations

**Queued for a long time.** No worker is running or it cannot reach Postgres.

```bash
make logs SERVICE=worker                   # local
docker compose ... ps worker               # is it up?
```

On AWS, check the worker service's running count and its log group. Once a worker runs,
the queue drains oldest first.

**Running for a long time.** Normal up to `GENERATION_TIMEOUT_S`. Past the lease, the next
claim picks it up. To see it in the database:

```sql
SELECT p.slug, g.number, g.status, g.attempts, g.started_at, g.lease_until
FROM generations g JOIN projects p ON p.id = g.project_id
WHERE g.status IN ('queued', 'running')
ORDER BY g.created_at;
```

A `running` row with `lease_until` in the past is waiting for the next claim (within a
second when a worker is up). A `running` row with `lease_until` null should not exist; the
service has an operations helper, `requeue_stuck()` in
[`generations/service.py`](../../apps/api/src/apiforge_server/generations/service.py), that
puts such rows back in the queue. There is no CLI command for it; run the equivalent SQL
yourself if you ever see one:

```sql
UPDATE generations SET status = 'queued' WHERE status = 'running' AND lease_until IS NULL;
```

Never delete generation rows by hand while a worker may be running them.

## Health checks

| Endpoint | Meaning | Used by |
| -------- | ------- | ------- |
| `GET /healthz` | The process answers | Container health checks |
| `GET /health` | The same, with the version | People |
| `GET /readyz` | Postgres answers within 2 s (Redis is probed when configured and reported, but never decides) | The ALB target group |

`/readyz` returns 200 `{"status": "ready"}`, 200 `{"status": "degraded"}` when Redis is
down, or 503 when Postgres is down. `GET /api/v1/system` (any signed-in user) shows the
versions of the service and the generator, the environment, the storage and cache
backends, the worker settings and the active API key count.

## Metrics

The API serves `/metrics` (with `Authorization: Bearer <METRICS_TOKEN>` when the token is
set). The worker serves its own on `WORKER_METRICS_PORT` (9464). Scrape both.

| Metric | Type | Labels | Served by | Meaning |
| ------ | ---- | ------ | --------- | ------- |
| `apiforge_specs_uploaded_total` | counter | `outcome`: `stored`, `unchanged`, `rejected` | api | Spec uploads by result (`unchanged`: the same bytes were already a version) |
| `apiforge_lint_seconds` | histogram | | api | Time to load, validate and normalize a spec (cache misses only) |
| `apiforge_lint_cache_total` | counter | `result`: `hit`, `miss` | api | Lint cache effectiveness |
| `apiforge_archive_downloads_total` | counter | | api | Archive downloads (including 304s) |
| `apiforge_dependency_errors_total` | counter | `dependency`, `operation` | api, worker | Absorbed failures of optional dependencies (`kv` lint cache, `redis` rate limit, `storage` delete) |
| `apiforge_generations_total` | counter | `status`: `succeeded`, `failed` | worker | Finished generations |
| `apiforge_generation_seconds` | histogram | | worker | Time to generate and store one project |
| `apiforge_generation_queue` | gauge | | worker | Generations waiting for a worker, updated on every claim |
| `apiforge_job_seconds` | histogram | `job` | worker | Duration of each worker pass |
| `apiforge_job_failures_total` | counter | `job` | worker | Worker passes that raised (not failed generations) |

Useful queries:

```promql
sum(rate(apiforge_generations_total{status="failed"}[15m]))
  / sum(rate(apiforge_generations_total[15m]))                     # failure ratio
histogram_quantile(0.95, sum by (le) (rate(apiforge_generation_seconds_bucket[1h])))
max(apiforge_generation_queue)                                      # backlog
sum(rate(apiforge_lint_cache_total{result="hit"}[1h]))
  / sum(rate(apiforge_lint_cache_total[1h]))                        # lint cache hit ratio
```

## Alarms

The `observability` module creates CloudWatch alarms that notify the SNS topic (and
`alarm_email` when set):

| Alarm | Fires when |
| ----- | ---------- |
| `<prefix>-api-5xx`, `<prefix>-web-5xx` | Targets return 5xx |
| `<prefix>-alb-5xx` | The load balancer itself returns 5xx (no healthy target, timeouts) |
| `<prefix>-api-unhealthy`, `<prefix>-web-unhealthy` | Tasks fail load balancer health checks |
| `<prefix>-api-latency-p95` | api p95 response time above `api_p95_latency_seconds` (1.5 s) |
| `<prefix>-<service>-cpu`, `<prefix>-<service>-memory` | A service's CPU or memory sustained above 85% |
| `<prefix>-db-cpu`, `-db-storage`, `-db-connections` | Database CPU above 80%, free storage below 5 GiB, connections above 80% of the ceiling |
| `<prefix>-cache-node-N-memory`, `-cpu` | A cache node above 80% memory (evictions drop cached reads and rate limit windows) or engine CPU |
| `<prefix>-worker-job-failures` | Worker log lines `job failed`: the generation loop itself raised (for example Postgres unreachable during a claim). The worker has no other jobs |
| `<prefix>-generation-failures` | Worker log lines `generation failed`: one per failed generation, whatever the cause |

The `generation-failures` alarm counts every failed generation: generator refusals,
`generation_timeout`, `internal_error` and `worker_lost` each write one `generation failed`
line. Its Prometheus counterpart is `apiforge_generations_total{status="failed"}`.

## Logs

Every process writes one JSON object per line to stdout: `ts`, `level`, `logger`, `msg`,
`request_id` (on the API), and any extra fields. The API logs one `request` line per
request (method, path, status, ms), except `/healthz`, `/readyz` and `/metrics` below
status 400. Credentials in log fields are redacted. On AWS the lines go to CloudWatch log
groups per service.

| Logger | Lines worth knowing |
| ------ | ------------------- |
| `apiforge_server.http` | `request` |
| `apiforge_server.worker` | `worker started` (cache backend, concurrency), `job failed`, `worker stopped` |
| `apiforge_server.generations` | `generation lease lost` (WARNING: a worker finished after another took over its expired lease; its result was discarded), `generation deleted while running` (the project was deleted mid-generation; the archive was removed), `generation failed` (WARNING, one per failed generation: `generation_id`, `error_code`, `attempts`), `generation raised` (the traceback of an unexpected exception) |
| `apiforge_server.errors` | `unhandled error`, `integrity conflict` (the constraint name, never values) |
| `apiforge_server.keys` | `could not record key usage` |
| `apiforge_server.cache` | `could not bump config version` (Redis down; other instances refresh on the 5 s TTL) |

Send `X-Request-Id` with a request to find its log line; the response always carries the
id it used.

## Backups and restore

| Data | Where | Backup |
| ---- | ----- | ------ |
| Users, keys, projects, spec metadata, generations, audit log | Postgres | RDS automated backups (3 days dev, 14 prod) and snapshots; locally `pg_dump` |
| Uploaded specs | S3 `specs/` | Bucket versioning (noncurrent versions kept 30 days); add replication or AWS Backup if you need more |
| Archives | S3 `archives/` | Not needed: any archive can be regenerated from its spec and options, byte for byte |
| Redis | ElastiCache | Not needed: rebuildable caches and counters |

Restore Postgres and the `specs/` prefix to the same point in time. A spec row whose
object is missing answers 410 `content_expired` on read and fails to generate; an object
without a row is ignored.

Locally:

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  exec -T postgres pg_dump -U apiforge apiforge > apiforge.sql
```

## Archive retention

Archives under `archives/` expire after `archive_expiration_days` (90 by default) through
the bucket lifecycle rule; specs under `specs/` are kept. After expiry the generation row
still says `succeeded`, and the download and file view answer 410 `content_expired`.
Request a new generation of the same spec version and options: the archive has the same
bytes and SHA-256 as before.

With `STORAGE=local` (development) nothing expires; `make down` deletes the volume.

Deleting a project deletes its rows and then its stored objects, best effort: a failed
delete increments `apiforge_dependency_errors_total{dependency="storage"}` and leaves an
orphan object (archives still expire on their own).

## Scaling

- **API:** add tasks (`api_min_count`/`api_max_count`); configure Redis when there is more
  than one, so rate limits, the lint cache and config invalidation are shared.
- **Worker:** add replicas or raise `WORKER_CONCURRENCY`. Each generation uses one CPU
  core while it renders and formats; size `WORKER_CONCURRENCY` to the task's vCPUs.
- **Database connections:** keep
  `(api tasks + workers + migrate) x (DB_POOL_SIZE + DB_MAX_OVERFLOW)` under the server's
  `max_connections`.

## Rotating secrets

| Secret | Effect of rotating | How |
| ------ | ------------------ | --- |
| `SESSION_SECRET` | Everyone is signed out | Update `<prefix>/app` in Secrets Manager, then force a new deployment of api and worker |
| `API_KEY_PEPPER` | Every API key stops working; create new keys | Same secret, then recreate keys |
| `METRICS_TOKEN` | Scrapers need the new token | Update `<prefix>/metrics`, redeploy, update Prometheus |
| Database password | Managed by RDS and the `connections` secret | Rotate through RDS, then re-apply Terraform to refresh `DATABASE_URL` |

Locally, delete `deploy/compose/.env` and run `make env` (then `make down && make up`).

## Users, owners and API keys

- `apiforge-server create-owner --email ...` creates an owner or resets an existing user
  to owner with a new password (and ends their sessions). Locally `make admin
  EMAIL=...`; on AWS `make aws-admin ENV=... EMAIL=...`.
- Keep at least two owners. The API refuses to demote or disable the last one.
- Disabling a user or changing their role ends their sessions immediately.
- Revoke an API key from the web app (API keys, Revoke): it is refused on its next
  request (within a second on every replica with Redis, within 5 s without).
  `last_used_at` shows whether a key is still in use.

## Upgrading the generator

The generator ships inside the API image, so upgrading APIForge upgrades it for every
project. New archives may differ from old ones for the same spec (the lock file records
the generator version); existing archives are untouched. The lint cache key includes the
generator version, so an upgrade never serves the previous version's lint results.
