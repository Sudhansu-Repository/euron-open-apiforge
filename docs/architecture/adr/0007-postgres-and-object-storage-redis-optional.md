# ADR-0007: Postgres plus object storage; Redis optional with an in-process fallback

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

APIForge stores three kinds of data: relational records (users, keys, projects, spec
version metadata, generations, the audit log), blobs (spec bodies up to megabytes, zip
archives), and short-lived shared state (rate limit windows, the lint cache, the config
cache version stamp). A single-machine install should not need more services than it must,
and a cache outage must never lose data or let a revoked credential back in.

## Decision

- **Postgres** holds every record and is the source of truth, including the job queue
  ([ADR-0006](0006-lease-based-worker-on-postgres.md)) and security state (sessions'
  revocations, lockouts, roles, key hashes).
- **Object storage** holds every blob: `specs/` (kept) and `archives/` (expire after
  `archive_expiration_days` on S3). Rows keep the key, the SHA-256 and the size; no blob is
  ever stored in a row. One `ObjectStorage` Protocol with `LocalStorage` (a directory) and
  `S3Storage` (SSE-KMS), chosen by `STORAGE`.
- **Redis is optional.** Every use goes through one `KV` Protocol
  ([`core/kv.py`](../../../apps/api/src/apiforge_server/core/kv.py)) with `RedisKV`
  (`REDIS_URL` set) and `MemoryKV` (empty: a bounded LRU with expiry, 20,000 entries and
  64 MB, and fixed-window counters, exact for a single process).
- A KV error is a miss or a pass, counted in `apiforge_dependency_errors_total`: linting
  runs uncached, rate limiters pass, the config cache expires on its 5 s TTL.
- `/readyz` requires Postgres only and reports Redis as degraded.
- The integration suite runs under both KV backends and both storage backends
  (`make test-matrix`).

## Consequences

**Good**
- `REDIS_URL=` runs the whole stack without Redis.
- Database rows stay small: listing projects and generations never drags megabytes of
  spec text or zip bytes out of Postgres.
- The S3 lifecycle handles archive retention without a cleanup job.

**Bad / caveats**
- Without Redis, state is per process: with several API replicas (or `WEB_CONCURRENCY`
  above 1), rate limits, the lint cache and config invalidation are per process. Use
  Redis for more than one API process.
- `STORAGE=local` is per container; production refuses it.
- Deleting a project removes rows first and objects best effort afterwards, so a storage
  failure can leave orphan objects (never orphan rows).

## Alternatives considered

- **Specs and archives in Postgres (`bytea`).** Simpler backups, but large rows on every
  list query and a database that grows with every generation.
- **Redis required.** Simpler code, but a heavier install and a hard dependency for data
  Postgres or the content itself can rebuild.
