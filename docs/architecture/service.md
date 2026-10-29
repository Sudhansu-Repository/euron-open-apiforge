# The service: projects, spec versions, generations and the worker

The service (`apps/api`, package `apiforge_server`) wraps the generator for a team: specs
are uploaded into projects, each upload becomes a numbered, linted version, generations
are queued and run by a worker, and the resulting archives are browsed and downloaded. The
generator itself is described in [generator.md](generator.md); this document covers what
the service adds around it. The tables are in [data-model.md](data-model.md).

- [Projects](#projects)
- [Spec versions](#spec-versions)
- [Comparing versions](#comparing-versions)
- [The playground and the examples](#the-playground-and-the-examples)
- [Generations](#generations)
- [The worker](#the-worker)
- [Archives and the file browser](#archives-and-the-file-browser)
- [Roles per route](#roles-per-route)
- [Error codes](#error-codes)

## Projects

A project is an API the team generates from: a name, a URL slug, a description, default
generation options and its history of spec versions and generations
([`projects/service.py`](../../apps/api/src/apiforge_server/projects/service.py)).

- **Slugs** are derived from the name (`Pet Store` becomes `pet-store`, at most 60
  characters). A taken slug gets `-2`, `-3`, ...; two people creating the same name at
  once both get a slug (the insert is retried up to three times on a unique-constraint
  race).
- **Default options** are the `GenerationOptions` a new generation uses unless the request
  overrides them: `project_name` (package name; default from the spec title), `db`
  (SQLAlchemy, Alembic and CRUD), `docker` (Dockerfile and Compose, on by default) and
  `ci` (GitHub Actions workflow, on by default). They are exactly the CLI's
  `--name`, `--db`, `--no-docker` and `--no-ci`.
- **Deleting a project** deletes its rows (spec versions and generations cascade), writes
  an audit row, commits, and then deletes the stored specs and archives best effort: a
  failed object delete is counted in `apiforge_dependency_errors_total` and leaves an
  orphan object, never an orphan row.
- `POST /api/v1/projects/from-example` creates a project from one of the bundled example
  specs, with that spec as version 1.

## Spec versions

`POST /api/v1/projects/{slug}/specs` takes a multipart upload (`file`, optional `note`);
`POST /api/v1/projects/{slug}/specs/text` takes JSON `{content, filename}` (what the web
app's editor sends). Both go through `upload_spec`:

1. **Size.** At most `MAX_SPEC_BYTES` (5 MiB by default) is accepted, for the file
   upload and the text route alike; more is 413 `spec_too_large`, and the message names
   `MAX_SPEC_BYTES`. The whole request body is separately bounded by `MAX_BODY_BYTES` (8 MiB
   on these routes; every other route is held to `MAX_SMALL_BODY_BYTES`, 64 KiB).
2. **File name.** Reduced to its last path component, characters outside
   `[A-Za-z0-9._-]` replaced with `-`, at most 120 characters, and `.yaml` appended
   unless it ends in `.yaml`, `.yml`, `.json` or `.zip`. A `.zip` is read as a bundle: the
   root `openapi.yaml` or `openapi.json` plus every file a relative `$ref` may name.
3. **Lint.** The bytes are analysed (load, validate, normalize, fingerprint each
   operation) in a worker thread, or served from the lint cache by their SHA-256
   ([HLD.md](HLD.md#caching-layers)). A document that cannot be loaded or is not valid
   OpenAPI 3.0 or 3.1 is refused with 422 and the generator's own error code
   (`spec_unreadable`, `spec_invalid`, `spec_version_unsupported`, `spec_ref_unresolved` or `spec_too_complex`), its message, and for an invalid spec the first validation errors in
   `details`.
4. **Idempotency.** If the project already has a version with the same SHA-256, that
   version is returned with `200 {created: false}`: CI can push the spec on every commit
   without creating duplicates. The unique constraint `(project_id, sha256)` makes this
   hold under concurrency too.
5. **Store.** The bytes go to object storage under
   `specs/<project id>/<version id>/<file name>`; the row keeps the key, the SHA-256, the
   size, the title, the API version, the OpenAPI version, operation and model counts,
   error and warning counts, the full report, a summary (operations, tags, security
   schemes, model names, fingerprints) and the changes against the previous version.
6. **Number.** The previous number plus one. A different spec that races for the same
   number gets 409 (send it again); the stored object of the losing request is deleted.
7. **Audit.** `spec.uploaded` is written in the same transaction.

A version with errors in its report is stored: the report is what the team needs to see.
It cannot be generated from until the report is accepted (below).

`GET /api/v1/projects/{slug}/specs/{n}` returns the version with its report (severity,
code, message, JSON pointer), operation list, tags, schemes and model names.
`GET .../specs/{n}/content` returns the text (for a zip, the root document and the list of
its files).

## Comparing versions

Each operation (`METHOD /path`) is reduced to the canonical form the fidelity check uses
([fidelity.md](fidelity.md#what-is-compared)) and fingerprinted per part: `parameters`,
`request body`, `responses` and `security` (a truncated SHA-256 of the canonical JSON).
Titles, descriptions and examples are not part of the canonical form, so editing them is
not a change.

- On upload, `changes` records operations added, removed and changed (with the parts that
  changed) against the previous version; the first version has `first: true` and every
  operation as added.
- `GET /api/v1/projects/{slug}/diff?base=a&head=b` compares any two versions the same way.

This is a structural comparison, not a breaking-change classifier: adding an optional
query parameter and removing a required one are both "parameters changed".

## The playground and the examples

- `POST /api/v1/lint` lints `{content, filename}` without storing anything (any role,
  including API keys). It is bounded by `MAX_SPEC_BYTES` like an upload and shares the lint
  cache with uploads.
- `GET /api/v1/examples` lists the specs bundled with the generator
  (`apps/forge/src/apiforge/corpus`) with their title, description, operation count and
  the features each one shows.
- `GET /api/v1/examples/{name}` returns one of them as `{name, content}` (any role); an
  unknown name is 404. The web app's playground offers them in its Load menu as
  "Example: <title>".

## Generations

`POST /api/v1/projects/{slug}/generations` with `{spec_number?, options?, accept_report}`
(admin):

- `spec_number` defaults to the latest version; a project with no spec gets 404 with
  "upload one first".
- If the version's report has errors and `accept_report` is false, 422
  `report_has_errors` with the first ten errors in `details`. Accepting the report
  generates without the parts the errors name (the CLI's `--accept-report`).
- `options` default to the project's default options.
- A row is inserted with `status = queued` and the next number for the project (unique
  `(project_id, number)`, retried up to three times on a race), plus a
  `generation.queued` audit row. The response is 202 with the generation.

A generation moves through `queued`, `running`, then `succeeded` or `failed`. Clients poll
`GET .../generations/{n}` (the web app every 1.5 s while it is queued or running).

| Field | Meaning |
| ----- | ------- |
| `attempts` | How many times a worker claimed it (more than 1 after a crashed worker) |
| `error_code`, `error` | Why it failed, in words that say what to do next |
| `archive_sha256`, `archive_bytes`, `file_count` | The archive, once succeeded |
| `duration_ms`, `started_at`, `finished_at` | Timing of the last attempt |
| `files` (detail only) | `[{path, owner, bytes}]`: the manifest, `owner` is `generated` or `user` |
| `resources` (detail only) | Collection resources implemented with `db` |

## The worker

`apiforge-server worker` runs one job, `generations`
([`worker.py`](../../apps/api/src/apiforge_server/worker.py),
[`generations/service.py`](../../apps/api/src/apiforge_server/generations/service.py)). A
pass that claimed work marks the job `busy`, and the next pass runs right away instead of
after `WORKER_POLL_S`, until a pass finds nothing: a queue drains back to back, and an idle
worker looks for work every `WORKER_POLL_S`.

**Claim.** One transaction selects up to `WORKER_CONCURRENCY` rows that are `queued`, or
`running` with `lease_until` in the past, oldest first, `FOR UPDATE SKIP LOCKED`. For each
row:

- if `attempts >= GENERATION_MAX_ATTEMPTS`, it is marked `failed` with
  `error_code = worker_lost` and "The worker stopped N times while generating this.
  Request a new generation; if it happens again, report it with the spec.";
  this also writes the `generation failed` log line (below);
- otherwise it becomes `running`, `attempts` goes up by one, `started_at` is now and
  `lease_until` is now plus `GENERATION_TIMEOUT_S` plus 30 s.

The transaction commits, the queue length is published as `apiforge_generation_queue`, and
the claimed rows run concurrently.

**Run.** For each claimed row:

1. Read what the job needs (spec key, options, the `attempts` value this claim set) and
   end the transaction: no transaction stays open while the generator runs.
2. Read the spec bytes from storage.
3. Run `generate` and `build_zip` in a thread, bounded by `GENERATION_TIMEOUT_S`.
4. Store the zip under `archives/<project id>/<generation id>.zip`.
5. Lock the row (`FOR UPDATE`) and check it is still `running` with the same `attempts`.
   Only then record the outcome: on success the key, SHA-256, size, the file manifest, the
   file count and a summary (resources, operation and model counts), `status =
   succeeded`.

**Fencing.** If the row's `attempts` changed, another worker claimed the job after this
worker's lease expired; this worker records nothing and logs `generation lease lost`
(WARNING), and the other worker's result stands. If the row is gone because the project
was deleted while the generator ran, the worker deletes the archive it stored and logs
`generation deleted while running`. Proven by
`test_a_worker_that_lost_its_lease_records_nothing` and
`test_a_project_deleted_mid_generation_leaves_no_archive_behind`.

Every failure is recorded on the row (subject to the fencing check), never raised out of
the worker:

| `error_code` | Cause | What the message says |
| ------------ | ----- | --------------------- |
| A generator code (`spec_invalid`, `report_has_errors`, `spec_ref_unresolved`, ...) | The generator refused the input | The generator's own explanation |
| `generation_timeout` | Longer than `GENERATION_TIMEOUT_S` | The spec may be very large; raise the timeout or split the spec |
| `internal_error` | Any other exception (a bug, storage down) | The exception type and a request to report it with the spec; the traceback is in the worker log (`generation raised`) |
| `worker_lost` | The lease expired `GENERATION_MAX_ATTEMPTS` times | Request a new generation |

Whenever the outcome is recorded, `lease_until` is cleared and `finished_at` and
`duration_ms` are written.
Every failed generation, whatever the cause (including `worker_lost` at claim time), writes
one `generation failed` WARNING log line with `generation_id`, `error_code` and `attempts`;
the CloudWatch `GenerationFailures` alarm counts these lines. An unexpected exception also
logs its traceback separately as `generation raised`.
`apiforge_generations_total{status}` and `apiforge_generation_seconds` are updated after
the commit.

**Why the lease is safe.** The lease is longer than the timeout, so a healthy worker always
records its result before the lease runs out. A worker that dies (OOM, killed task,
crashed host) leaves a `running` row whose lease expires; the next claim picks it up and
the attempt counter makes a spec that kills workers fail permanently instead of looping.
Two workers never run the same row at once: the claim is one transaction and
`SKIP LOCKED` hands each row to one of them. Proven by
`tests/integration/test_generations.py::test_a_crashed_workers_job_is_retried_then_failed_with_a_reason`
and `test_concurrent_workers_never_run_the_same_generation`.

**Determinism across retries.** A retried generation produces the same bytes as the first
attempt would have. The concurrency test queues six generations of one spec on five
claiming workers and asserts a single archive hash.

**Shutdown.** `SIGTERM` or `SIGINT` sets a stop flag; the current pass finishes, then the
worker closes its pools and exits. On ECS the worker's `stopTimeout` is 120 s (the ECS
maximum, equal to the default `GENERATION_TIMEOUT_S`) before `SIGKILL`; a generation cut off
by the kill is not lost, it is claimed again after its lease (`GENERATION_TIMEOUT_S` + 30 s).
If you raise `GENERATION_TIMEOUT_S`, a stop can cut more generations short, and they cost
one extra attempt each.

`requeue_stuck()` in the service module puts `running` rows without a lease back to
`queued`. It is an operations helper (there is no CLI command for it); see
[operations.md](../guides/operations.md#stuck-generations).

## Archives and the file browser

- `GET .../generations/{n}/archive` returns the zip with
  `Content-Disposition: attachment; filename="<slug>-<n>.zip"`,
  `ETag: "<sha256>"` and `Cache-Control: private, no-cache`: caches keep the zip but revalidate on every use, because a deleted project's slug (and so the same URL) can be taken by a new project.
  `If-None-Match` with that ETag gets 304; it is compared after the row is loaded and
  before storage is read, so a 304 costs no storage read. A generation that has not succeeded gets 409
  with its status. Each download counts in `apiforge_archive_downloads_total`.
- The zip is byte-identical to `apiforge generate --zip` for the same spec and options:
  sorted entries under a `<slug>/` folder, fixed 1980-01-01 timestamps, fixed `0644`
  permissions, pinned compression
  ([`archive.py`](../../apps/forge/src/apiforge/archive.py)).
- `GET .../generations/{n}/file?path=...` returns one file as `{path, owner, content,
  language}`. The path must appear in the generation's manifest, so a path like
  `../../etc/passwd` is a 404 before anything is read. The archive is unpacked once per API
  process and kept by its SHA-256 (at most 16 archives and 64 MiB of unpacked files). The
response has `ETag: "<sha256>:<path>"` and the same revalidated caching, and a matching
`If-None-Match` gets 304.
- Archives expire from S3 after `archive_expiration_days` (90 by default; specs are kept).
  An expired archive answers 410 `content_expired`. Because generation is deterministic, a
  new generation of the same version and options gives the same bytes and the same
  SHA-256.

## Roles per route

| Route | viewer / API key | admin | owner |
| ----- | ---------------- | ----- | ----- |
| Read projects, spec versions, content, diffs, generations, files, archives, examples (list and text), overview, system | yes | yes | yes |
| `POST /api/v1/lint` (playground) | yes (API keys too) | yes | yes |
| Create, rename and delete projects; upload specs; create from an example; request generations | no | yes | yes |
| List and manage API keys, list users, read the audit log | no | yes | yes |
| Create users, change roles, disable users | no | no | yes |

API keys act as a viewer and may only use `GET`, `HEAD` and `OPTIONS`; any other method is
403 `read_only_key`, whatever the route.

## Error codes

Every error body is `{"error": {"code", "type", "message", "details"}}`.

| Status | Code | When |
| ------ | ---- | ---- |
| 401 | `not_signed_in`, `session_expired`, `invalid_credentials`, `account_locked`, `account_disabled`, `invalid_api_key`, `revoked_api_key`, `expired_api_key`, `metrics_token` | Authentication |
| 403 | `insufficient_role`, `read_only_key`, `csrf_required`, `forbidden` | Authorization |
| 404 | `not_found` | Unknown project, version, generation, file or example |
| 409 | `conflict` | A race (same number taken), or an archive that is not ready |
| 410 | `content_expired` | The stored spec or archive is gone (bucket lifecycle) |
| 413 | `spec_too_large`, `payload_too_large` | Over `MAX_SPEC_BYTES`, or the body over `MAX_BODY_BYTES` (spec routes) or `MAX_SMALL_BODY_BYTES` (every other route) |
| 422 | `spec_unreadable`, `spec_invalid`, `spec_version_unsupported`, `spec_ref_unresolved`, `spec_too_complex` (a refused spec), `report_has_errors`, `validation_error`, `invalid_json`, `weak_password` | Input |
| 429 | `rate_limited` | Login throttle or an API key's limit (`Retry-After` set) |
| 500 | `internal_error` | A bug (no stack trace in the body) |
