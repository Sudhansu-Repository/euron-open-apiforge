# ADR-0006: A lease-based worker on Postgres instead of a queue service

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

Generating a project is CPU work that takes from a fraction of a second to tens of seconds
for a large spec, so it must not run on the API's request path. It needs a queue with a
few properties: a job is run by one worker at a time, a worker that dies does not lose its
job, a job that kills workers does not loop forever, several workers can share the load,
and the user can see the job's status. Throughput is modest (generations are requested by
people and CI, not by traffic), and every generation already has a row users need to see.

## Decision

- The `generations` table is the queue. A request inserts a row with `status = queued`.
- The worker claims rows in one transaction:
  `SELECT ... WHERE status = 'queued' OR (status = 'running' AND lease_until < now)
  ORDER BY created_at LIMIT n FOR UPDATE SKIP LOCKED`, then sets `running`,
  `attempts + 1` and `lease_until = now + GENERATION_TIMEOUT_S + 30 s`, and commits.
- The lease is longer than the timeout, so a healthy worker always records its result
  first. A dead worker's row is claimed again after the lease; at
  `GENERATION_MAX_ATTEMPTS` the row fails with `worker_lost` instead.
- Every outcome (success, generator error, timeout, unexpected exception) is written to
  the row; the worker never raises out of a job.
- An index on `(status, created_at)` serves the claim and the queue-length gauge.

**Update (2026-10-28, same release):** results are fenced. The worker holds no
transaction while the generator runs; it then locks the row and writes the outcome only if
`attempts` still equals the value its claim set. A worker whose lease expired records
nothing (`generation lease lost`), and a generation whose project was deleted meanwhile
deletes its stored archive ([service.md](../service.md#the-worker)).

## Consequences

**Good**
- No extra infrastructure: Postgres is already required, locally and on AWS.
- Exactly one worker runs a row at a time, proven by
  `test_concurrent_workers_never_run_the_same_generation`; crashed workers are recovered,
  proven by `test_a_crashed_workers_job_is_retried_then_failed_with_a_reason`.
- The job's state is the row users read: no second source of truth to reconcile.
- Worker replicas scale horizontally; `SKIP LOCKED` keeps them from blocking each other.

**Bad / caveats**
- Polling: an idle worker looks every `WORKER_POLL_S` (1 s), so a generation queued while
  the worker is idle waits up to that long. While passes find work, the worker runs the
  next pass right away, so a backlog drains back to back.
- Recovery after a crash waits for the lease (150 s with the defaults).
- `asyncio.wait_for` bounds the wait, not the generator thread: a timed-out generation
  keeps a thread busy until it finishes.
- This design is sized for generation volumes, not for millions of small jobs.

## Alternatives considered

- **SQS (Floci locally).** A managed queue with visibility timeouts gives the same
  semantics, but adds a dependency and a second state to keep consistent with the row.
- **Celery or RQ on Redis.** Would make Redis required
  ([ADR-0007](0007-postgres-and-object-storage-redis-optional.md)) and keep job state
  outside the database.
- **Advisory locks.** Fine for singleton jobs; row claims with a lease express per-job
  ownership and recovery directly.
