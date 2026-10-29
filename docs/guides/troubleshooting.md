# Troubleshooting

Symptoms, causes and fixes, for the CLI, the generated project and the service. Every API
error has a `code` (`{"error": {"code", "message", "details"}}`); search this page for it.

- [The CLI refuses a spec](#the-cli-refuses-a-spec)
- [report_has_errors: generation is blocked](#report_has_errors-generation-is-blocked)
- [generated_file_edited: regeneration refuses to write](#generated_file_edited-regeneration-refuses-to-write)
- [apiforge verify fails](#apiforge-verify-fails)
- [test_spec.py fails in a generated project](#test_specpy-fails-in-a-generated-project)
- [Every request to a secured route gets 401](#every-request-to-a-secured-route-gets-401)
- [501 Not implemented, or /docs is 404, in production](#501-not-implemented-or-docs-is-404-in-production)
- [The app refuses to start: Unsafe production settings](#the-app-refuses-to-start-unsafe-production-settings)
- [A spec is refused on upload (422)](#a-spec-is-refused-on-upload-422)
- [spec_too_large or payload_too_large](#spec_too_large-or-payload_too_large)
- [A generation stays queued](#a-generation-stays-queued)
- [A generation failed](#a-generation-failed)
- [content_expired on download](#content_expired-on-download)
- [Uploading the same spec does not create a version](#uploading-the-same-spec-does-not-create-a-version)
- [read_only_key, insufficient_role, csrf_required](#read_only_key-insufficient_role-csrf_required)
- [rate_limited](#rate_limited)
- [The service refuses to start: unsafe production configuration](#the-service-refuses-to-start-unsafe-production-configuration)
- [Local stack problems](#local-stack-problems)

## The CLI refuses a spec

`apiforge` prints the reason on stderr and exits with 1.

| Message starts with | Cause | Fix |
| ------------------- | ----- | --- |
| `... is not valid JSON or YAML (line L, column C)` | A syntax error | Fix it at that line |
| `... is not UTF-8 text` | Another encoding | Save the file as UTF-8 |
| `... is NNN KiB; the limit is 5 MiB` | One document over 5 MiB | Split it into files with relative `$ref`s and pass a folder or zip |
| `The YAML uses more than 10000 aliases` / `expands to more than 2,000,000 values` | Heavy YAML anchors (or a "billion laughs" document) | Expand the anchors, or split the document |
| `... is nested more than 64 levels deep` | Very deep nesting | Flatten with `$ref`s |
| `External $ref ... points to a URL` | A `$ref` to `http://...` | Download the file and pass the spec as a folder or zip with it; APIForge never fetches URLs |
| `$ref ... leaves the spec's folder` | `../` outside the spec | Move the referenced file inside the spec's folder |
| `$ref ... points to '...', which is not part of the spec` | A missing file | Pass the whole folder (or a zip), not the single file |
| A Swagger 2.0 message | `swagger: "2.0"` | Convert to OpenAPI 3 first (for example with swagger2openapi), then lint again |
| `The spec is not a valid OpenAPI ...` with a list | Structural validation failed | Fix the listed problems (pointers show where) |
| `Inlining the spec's $refs would produce more than 500,000 schema nodes` (`spec_too_complex`) | Schemas that reference each other many times over (fan-out) | Reduce the fan-out (fewer properties pointing back at the same schema), or split the spec |
| `... contains an unpaired UTF-16 surrogate` | A `\ud800` to `\udfff` escape without its pair | Replace it with the character it was meant to be |
| `... is encrypted` / `... could not be read from the zip` | An encrypted zip, an unsupported compression method or a corrupt member | Upload a plain zip (stored or deflated) |
| `$ref ... has a fragment that is not a JSON pointer` | An anchor ref such as `#foo` | Use a JSON pointer (`#/components/schemas/Foo`); anchor refs are not supported |
| `External $ref ... points to a URL` for a `$ref` inside an `example` | Every `$ref` key anywhere in the spec is checked to be local before validation, including inside example data | Rename the key in the example, or move the example out of the spec; this is a known limitation |

## report_has_errors: generation is blocked

The lint report has errors: constructs whose meaning would change if APIForge generated
around them (two routes with the same shape, a duplicate operation id, an undeclared path
parameter, a `$ref` that is not a schema). Run `apiforge lint SPEC` and fix them. If you
want the project anyway, `--accept-report` on the CLI (or "accept the report" in the web
app, `accept_report: true` in the API) generates without the parts the errors name.

## generated_file_edited: regeneration refuses to write

A file under `app/generated/` or `tests/generated/` differs from the hash in
`apiforge.lock`, so someone edited it. Nothing was written. Either move the change into a
file you own (`app/handlers/`, `app/auth.py`, `app/main.py`, a new module), or change the
spec, then regenerate; or pass `--force` to overwrite the edited files.
`apiforge diff ... --json` lists the conflicts without writing.

## apiforge verify fails

`verify` stops at the first failing step and prints the end of its output.

| Step | Typical cause | Fix |
| ---- | ------------- | --- |
| (before any step) `apiforge: apiforge verify needs uv ...`, exit 1 | uv is not installed | Install [uv](https://docs.astral.sh/uv/) |
| install | No access to the package index | Run with network access once, or a warm uv cache |
| install (`uv sync --locked` in Docker or CI) | `uv.lock` is out of date with `pyproject.toml` | Run `uv sync` locally and commit the updated `uv.lock` |
| lint, format | You edited a handler | `uv run ruff check --fix . && uv run ruff format .` |
| types | A handler's signature no longer matches the router after a spec change | Update the handler to the new parameters and return type |
| tests | A handler returns data that does not match the response schema, or `test_spec.py` found a difference | See the next section for `test_spec.py`; otherwise fix the handler |

A failure in a freshly generated, unedited project is an APIForge bug: please report it
with the spec.

## test_spec.py fails in a generated project

The app no longer serves the API in its spec. The assertion message names the operation
and the part (parameters, request body, responses, security). Usually a route, a model or
a dependency was changed by hand. The spec is the source of truth: change the spec and
regenerate, or revert the hand change. If the lint report announced an approximation for
that exact operation and part, it is already in `ACCEPTED`; anything else is a real
difference.

## Every request to a secured route gets 401

In the generated project, `app/auth.py` fails closed:

- Bearer, OAuth2, OpenID Connect: `JWT_SECRET` is empty, the token is signed with another
  secret or algorithm, it lacks `sub` or `exp`, it is expired (beyond
  `JWT_LEEWAY_SECONDS`), `JWT_AUDIENCE` is set and the token's `aud` differs, or
  `JWT_ISSUER` is set and its `iss` is missing or differs. Tokens are checked with the
  secret only; keys from a JWKS endpoint are not fetched.
- API key: the key is not in `API_KEYS` (a JSON list: `API_KEYS='["key-one"]'`), or it
  is sent in the wrong place (header, query or cookie, as the spec says).
- Basic: the user is not in `BASIC_USERS` (a JSON object), or the `Authorization` header
  is malformed (it counts as no credential).
- The requirement needs several schemes at once (an AND requirement such as
  `{apiKey: [], bearer: []}`): every one of them must be sent.
- The route's only scheme is one APIForge cannot check (HTTP digest, mutual TLS): it
  depends on `security.unsupported`, which always answers 401. Check the credential
  yourself and set `app.dependency_overrides[security.unsupported] = your_check` in
  `app/main.py`.

A 403 means an alternative authenticated but lacked a scope the operation requires, and no
other alternative succeeded.

## 501 Not implemented, or /docs is 404, in production

With `APP_ENV=production`, an operation whose handler still returns the mock answers 501
`{"detail": "Not implemented"}` (and logs a warning the first time it is called): write
the handler. `/docs`, `/redoc` and `/openapi.json` are off in production; set
`DOCS_ENABLED=true` to turn them on.

## The app refuses to start: Unsafe production settings

The generated project's `app/config.py` refuses `APP_ENV=production` with a `JWT_SECRET`
under 32 characters, a `JWT_ALGORITHM` other than HS256, HS384 or HS512, an API key under
24, a basic password under 16, `*` in `CORS_ORIGINS`, or (with `--db`) a `DATABASE_URL`
that is unset or SQLite. Set real values (`openssl rand -hex 32`), or use `APP_ENV=development`
locally.

## A spec is refused on upload (422)

The service could not load or validate the spec. The error code is the generator's
(`spec_unreadable`, `spec_invalid`, `spec_version_unsupported`, `spec_ref_unresolved` or `spec_too_complex`), and for invalid specs `details` lists the first errors. The causes and fixes are the same as for the CLI
([above](#the-cli-refuses-a-spec)). For a multi-file spec, upload a zip with
`openapi.yaml` (or `.json`) at its top and the referenced files beside it. Nothing was
stored.

## spec_too_large or payload_too_large

`spec_too_large` (413): the spec (a file upload, pasted text or a playground lint) is over
`MAX_SPEC_BYTES` (5 MiB); the message says so. `payload_too_large`
(413): the whole request body is over its route's limit: `MAX_BODY_BYTES` (8 MiB) for
`/api/v1/lint` and the spec uploads, `MAX_SMALL_BODY_BYTES` (64 KiB) for every other route
(the message names the setting that applies). Raising `MAX_SPEC_BYTES`
helps zip bundles (up to 20 MiB in total) but not a single document over 5 MiB, which the
generator refuses anyway; split such a document.

## A generation stays queued

No worker is running, or it cannot reach Postgres.

- Locally: `make ps` (is `worker` up?), `make logs SERVICE=worker`.
- On AWS: the worker service's running count and its CloudWatch log group.
- `apiforge_generation_queue` on the worker's metrics, or the overview's queue count.

Details in [operations.md](operations.md#stuck-generations).

## A generation failed

Open it: `error_code` and `error` say why.

| `error_code` | Meaning | What to do |
| ------------ | ------- | ---------- |
| A generator code (`spec_invalid`, `report_has_errors`, ...) | The generator refused the input | Follow the message |
| `generation_timeout` | Longer than `GENERATION_TIMEOUT_S` | Raise the setting or split the spec |
| `internal_error` | An unexpected exception | Check that storage is reachable (the worker log has the traceback under `generation raised`); otherwise report it with the spec |
| `worker_lost` | The worker died on it `GENERATION_MAX_ATTEMPTS` times | Look for OOM kills in the worker logs; give the worker more memory; report it with the spec |

Request a new generation to retry.

## content_expired on download

The archive (or, rarely, the spec) is no longer in storage: archives expire after
`archive_expiration_days` (90 by default). Request a new generation of the same version and
options; generation is deterministic, so the new archive has the same SHA-256.

## Uploading the same spec does not create a version

By design: uploads are idempotent by SHA-256. The response is 200 with
`created: false` and the existing version. Change the spec's bytes (even a description) to
get a new version; if only descriptions changed, the version's `changes` will be empty,
because titles, descriptions and examples are not part of the comparison.

## read_only_key, insufficient_role, csrf_required

- `read_only_key` (403): API keys may only `GET`. Sign in as an admin to upload or
  generate.
- `insufficient_role` (403): the action needs admin (projects, uploads, generations, keys,
  the audit log) or owner (users and roles).
- `csrf_required` (403): a cookie-authenticated `POST`, `PATCH` or `DELETE` without
  `X-APIForge-CSRF: 1`. The web app sends it; scripts should use a bearer token instead of
  the cookie.

## rate_limited

429 with `Retry-After`. Either sign-in (20 attempts a minute per address) or an API key's
limit (its `rpm_limit`, or `DEFAULT_RPM_LIMIT`, 600 a minute). Wait, or raise the key's
limit (API keys, Edit). Five wrong passwords from one address lock that address out of
that account for 15 minutes (`account_locked`), while sign-in from other addresses keeps
working; 50 failures from anywhere lock the account for everyone. Wait, or reset an owner
with `create-owner`.

## The service refuses to start: unsafe production configuration

`ENVIRONMENT=production` with demo secrets, equal secrets, `COOKIE_SECURE=false`,
`STORAGE=local`, `AWS_ENDPOINT_URL` with `APIFORGE_CLOUD=aws`, `*` or a non-https origin in
`CORS_ORIGINS`, the default or a localhost `DATABASE_URL`, or no `METRICS_TOKEN`. The message lists every
problem; [configuration.md](configuration.md#production-boot-guards) explains each.

## Local stack problems

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| `run make env first` | `deploy/compose/.env` is missing | `make env` (or `make up`, which runs it) |
| `port is already allocated` | Another process uses 4610, 4630, 4642, 4679 or 4666 | Set `AF_WEB_PORT`, `AF_API_PORT`, ... in `deploy/compose/.env` |
| `terraform` exits non-zero, `migrate`/`api`/`worker` never start | Floci was not ready or kept stale state | `make down` (deletes volumes) then `make up`; `make logs SERVICE=terraform` |
| The web app shows a network error | The API is not healthy yet, or `API_INTERNAL_URL` is wrong | `make ps`, `make logs SERVICE=api` |
| `make demo` says `Set DEMO_PASSWORD` | Running `seed-demo` outside Compose | `DEMO_PASSWORD=... uv run apiforge-server seed-demo` |
| Demo sign-in fails | The password changed (`.env` regenerated) after seeding | `make down && make up && make demo` |
| Integration tests refuse the database | The URL does not name a `*test*` database on a local host | Use `make test-integration`, or set `TEST_DATABASE_URL` correctly |
| `make test-matrix` says Floci is not reachable | The stack is not up | `make up` first |
| `make test-corpus` skips everything | `uv` is not on the path | Install uv |
