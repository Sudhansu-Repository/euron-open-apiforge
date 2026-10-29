# Testing

APIForge has several layers of automated checks, and each proves something different. At
0.1.0 there are 85 generator unit tests, 15 corpus tests, 55 API unit tests, 61
integration tests (run under 4 backend combinations), 43 web tests, 17 browser end to end
tests and a QA sweep of 88 pages; the README's Testing table keeps the current counts. This guide describes what each gate covers and how to run it.

| Gate | Command | Needs | Proves |
| ---- | ------- | ----- | ------ |
| Lint | `make lint` | uv, pnpm | ruff check and ruff format for the generator and the API, ESLint for the web app |
| Typecheck | `make typecheck` | uv, pnpm | mypy `--strict` for the generator and the API, `tsc --noEmit` for the web app |
| Unit | `make test` | uv, pnpm | Pure logic with no database and no network: the generator (pytest, Hypothesis), the API (pytest) and the web app (Vitest) |
| Integration | `make test-integration` | Docker | The real API and worker code in-process against real Postgres and Redis |
| Option matrix | `make test-matrix` | `make up` (Floci) | The integration suite under every cache and storage backend (4 runs) |
| Corpus | `make test-corpus` | uv, the package index or a warm uv cache, Docker (Postgres) | Every bundled spec, with and without `--db`, the hostile spec and a 240-operation spec, generated into a real project whose own gates pass; every `--db` project's tests run again on Postgres; plus a runtime test of the generated team-tasks app (`tests/test_hardening.py`) |
| Browser e2e | `make e2e` | `make up && make demo` | User journeys through the real web app, API and worker (Playwright, Chromium) |
| Browser QA | `make qa` | `make up && make demo` | Every page in light and dark, desktop and phone width, with no console errors, failed requests, broken images, error states or horizontal overflow (Puppeteer) |
| Sanitization | `make sanitize` | bash, git | No credentials, cloud identifiers, committed env files or em/en dashes in the tree |
| Terraform validate | `make tf-validate` | Docker or terraform | `terraform validate` for `local-floci`, `aws-dev` and `aws-prod` |
| Terraform lint | `make tf-lint` | Docker | tflint over every module and environment |
| Terraform security | `make tf-security` | Docker | checkov policy scan (inline, reasoned skips only) |
| AWS on Floci | `make tf-aws-on-floci` | Docker | The full `aws-dev` environment planned, applied, re-planned and destroyed against a throwaway Floci |
| Service benchmark | `make bench` | `make up && make demo` | Lint, upload, generation, archive and file latency of the running stack, and the generator's own time per example (numbers go in the README) |

## Acceptance criteria

The twelve acceptance criteria in [PLAN.md](../PLAN.md#acceptance-criteria-each-is-an-automated-test)
and where each is proven:

| # | Criterion | Proven by |
| - | --------- | --------- |
| 1 | It runs | `apps/forge/tests/test_corpus.py` (each generated project installs and its tests, which include `GET /health`, pass) |
| 2 | It is the spec | The generated `test_spec.py` in every corpus project; `apps/forge/tests/test_fidelity.py` for the comparison itself |
| 3 | It validates | The generated `*_rejects_invalid_input` tests in every corpus project |
| 4 | A mock on day one | The generated `*_matches_the_spec` contract tests (before any handler is written); `test_examples.py` (every example validates against its schema) |
| 5 | Regeneration keeps your code | `apps/forge/tests/test_writer.py` |
| 6 | Deterministic | `test_generator.py::test_the_same_input_gives_the_same_bytes`; `apps/api/tests/integration/test_generations.py::test_a_generation_runs_in_the_worker_and_its_archive_is_the_cli_output` (the web download equals the CLI zip) |
| 7 | Clean code | The corpus suite runs `ruff check`, `ruff format --check` and `mypy --strict` on every generated project |
| 8 | Nothing silent | `test_normalize.py::test_derived_operation_ids_and_unsupported_parts_are_reported`, `test_duplicate_routes_are_an_error`, `test_generator.py::test_errors_in_the_report_block_generation_until_accepted`, `test_generations.py::test_errors_in_the_report_block_generation_until_accepted`, `test_projects.py::test_report_findings_point_into_the_spec` |
| 9 | A hostile spec is inert | `test_hostile.py` (including Hypothesis property tests); `test_corpus.py::test_a_hostile_spec_generates_a_project_that_passes_its_gates` |
| 10 | Local-first | `test_generator.py::test_generating_needs_no_network` (sockets blocked); `test_loader.py::test_url_refs_are_never_fetched`; `test_hardening.py::test_a_spec_with_url_refs_never_makes_the_server_fetch` |
| 11 | Auth from the spec | The generated `*_requires_credentials` tests (`secure-notes.yaml` covers every scheme); `test_normalize.py::test_optional_authentication_and_explicitly_open_operations` |
| 12 | Persistence when asked | The generated `test_crud_<resource>.py` round trips in the `--db` corpus projects, on SQLite and again on Postgres (`make test-corpus`) |

## Static checks

```bash
make lint typecheck
```

- `apps/forge`: `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy src` (strict). The Jinja templates are excluded from ruff; what they
  produce is checked by the corpus suite.
- `apps/api`: the same three commands in its own uv project.
- `apps/web`: `pnpm lint` (ESLint) and `pnpm typecheck` (`tsc --noEmit`).

## Unit tests

```bash
make test
```

Runs `uv run pytest -q` in `apps/forge` (the corpus is excluded by the default
`-m 'not corpus'`), `uv run pytest tests/unit -q` in `apps/api` and `pnpm test` (Vitest) in
`apps/web`.

| Location | Covers |
| -------- | ------ |
| `apps/forge/tests/test_loader.py` | JSON and YAML equivalence, dates staying strings, alias bombs refused and ordinary aliases accepted, object-building tags refused, size and depth limits, unreadable input explained, URL refs never fetched, refs that leave the folder refused, multi-file refs and missing files named, JSON pointer escapes, zip bundles read safely |
| `apps/forge/tests/test_normalize.py` | Swagger 2.0 refused with a way forward, invalid specs listing their problems, the pet store mapped to routes, models and security, discriminated unions narrowing each variant, nullable, constraints and defaults, derived operation ids and unsupported parts reported, duplicate routes as errors, optional and explicitly open authentication |
| `apps/forge/tests/test_examples.py` | Every example validates against its schema, the same schema always gives the same example, spec examples win when they fit, `readOnly` and `writeOnly` respect the direction, sampled strings match their pattern, unsamplable patterns return none |
| `apps/forge/tests/test_fidelity.py` | Cosmetic differences ignored, a changed constraint found, missing and extra operations found, parameter location, requiredness and security compared, accepted differences filtered precisely |
| `apps/forge/tests/test_generator.py` | Byte-identical output for the same input, options changing the output and recorded in the lock, every file owned and handlers yours, the report gate, generating with sockets blocked, the CLI (`lint`, `generate`, `--zip`, `diff`, `examples`, folders and zips with relative refs) |
| `apps/forge/tests/test_hostile.py` | A spec built to break out of identifiers, strings, docstrings and comments generates inert code; property tests over arbitrary text for literals, docstrings and identifiers |
| `apps/forge/tests/test_writer.py` | Regeneration after spec changes keeps every line you wrote; a hand-edited generated file is never overwritten silently; a generated file no longer produced is removed; a hostile lock file cannot delete outside the generated folders |
| `apps/forge/tests/test_hardening.py` | What a generated app must get right, checked in the generated source: AND and OR security requirements, an unsupported scheme failing closed and staying in the report, an unsupported alternative not opening the route, scopes decided in `require()`, paging with missing values and bounded offsets, PUT keeping columns outside the input model, integer enum parameters, default-only operations, the Dockerfile and CI using `uv.lock`, the production guards in the user-owned settings. Its corpus test runs the same fixes in a live team-tasks app |
| `apps/forge/tests/test_budgets.py` | The `$ref` expansion budget: a self-referencing fan-out under 1 KB is refused fast with `spec_too_complex`; a modest fan-out still generates |
| `apps/api/tests/unit/core/` | Settings and the production boot guards, Redis being optional, defaults that send nothing anywhere, worker bounds, the KV store and the config cache (single flight, cross-instance invalidation, TTL, the invalidation race, byte bounds), cursors, emails, the error envelope, JSON logs with redaction, API keys, passwords and sessions, local storage (path traversal) |
| `apps/api/tests/unit/generations/test_archive_cache.py` | The archive file cache: least recently used first over the count bound, the byte bound always keeping the newest entry, the same archive never counted twice, ETags for an archive and one file |
| `apps/api/tests/unit/system/test_openapi_drift.py` | `docs/api/openapi.yaml` matches the app and every operation is documented. `make openapi` regenerates it |
| `apps/web/test/` | Formatting, error messages, auth redirects, and domain helpers (lint findings, spec changes, the file tree) |

## Integration tests

```bash
make test-integration
```

`scripts/test-db.sh` reuses the Compose Postgres and Redis when they are up, and otherwise
starts just those two, then creates the `apiforge_test` database. The suite runs
`apps/api/tests/integration` with coverage against that database (migrated with Alembic for
the session) and Redis database 15. Workers are driven in-process (`claim`, `run`,
`process`), so a test can queue a generation, run the worker's code and read the result.

Safety: the suite empties every table, so it refuses a database whose name lacks `test`,
and any host other than `localhost`, `127.0.0.1` or `postgres` unless
`ALLOW_REMOTE_TEST_DB=true`. Override the targets with `TEST_DATABASE_URL` and
`TEST_REDIS_URL` ([configuration.md](configuration.md#test-suite)).

| File | Proves |
| ---- | ------ |
| `test_projects.py` | Project lifecycle and unique slugs; uploads linted, stored and numbered; report findings pointing into the spec; unusable specs refused with a reason; zip bundles with relative refs; the size limit on file uploads, text uploads and the playground; the playground storing nothing; examples listed, read one by one (`GET /api/v1/examples/{name}`, unknown names 404) and turned into projects |
| `test_generations.py` | A generation run by the worker whose archive equals the CLI output (and its ETag, and a 304 that never reads storage); files browsed one by one (and their 304); options defaulting from the project; the report gate; generating without a spec; no archive before success; a crashed worker's job retried, then failed with `worker_lost`; concurrent workers never running the same generation; a generator failure recorded, not raised; a worker that lost its lease recording nothing; a project deleted mid-generation leaving no archive behind; the overview |
| `test_admin.py` | Sign-in and lockout, CSRF, the role matrix, read-only API keys, per-key rate limits, owner guards, password changes ending other sessions, the append-only audit log, system info, health and metrics, the metrics token |
| `test_hardening.py` | Lone surrogates as 422, chunked bodies over the limit, URL refs never fetched, upload names that cannot escape storage, zip and YAML bombs refused before the work, parallel uploads of one spec storing one version, forged `X-Forwarded-For`, parallel wrong passwords, server-side sign-out, signed-out sessions surviving cache eviction, uncached login responses, racing owner demotions and user creates, security headers |
| `test_backends.py` | The configured cache and storage backends are the ones in use; specs and archives round trip through storage; lint results cached and surviving a cache outage |
| `test_worker_cli.py` | The worker schedule running queued generations, a failing job not stopping the others, the CLI's `openapi` and `create-owner`, the demo seed filling every screen, being idempotent and refusing `ENVIRONMENT=production`, editing API keys |

## Option matrix

```bash
make up
make test-matrix
```

`scripts/test-matrix.sh` checks that Floci answers on `localhost:4666`, then runs the
integration suite four times:

| Axis | Values | Set by |
| ---- | ------ | ------ |
| Cache | `redis`, `memory` (no Redis at all) | `TEST_CACHE` |
| Storage | `local` (disk), `s3` (Floci S3, the `apiforge-local-artifacts` bucket the `local-floci` Terraform created) | `TEST_STORAGE`, `TEST_AWS_ENDPOINT` |

It prints `matrix: all 4 combinations passed` or lists the failing ones.

## The corpus suite

```bash
make test-corpus
# = AF_TEST_DB=generated_test scripts/test-db.sh, then
#   cd apps/forge && CORPUS_DATABASE_URL=postgresql+asyncpg://apiforge:apiforge@localhost:4642/generated_test \
#     uv run pytest -m corpus
```

For every spec in `apps/forge/src/apiforge/corpus`, with and without `--db`, plus the
hostile spec from `test_hostile.py` and a synthesized 240-operation spec, the suite
generates a project into a temporary folder and runs `apiforge verify` on it: `uv sync`,
`ruff check`, `ruff format --check`, `mypy app tests` and `pytest`. A failing step fails the
test with that step's output. This is the proof behind acceptance criteria 1, 2, 3, 4, 7,
11 and 12: the generated tests check those claims, so the generated suite passing is the
claim holding. That is 14 cases (six specs with and without `--db`, the hostile spec and
the 240-operation spec). The fifteenth corpus test, in `tests/test_hardening.py`, generates
the team-tasks spec with `--db`, adds runtime checks to its test suite (an unsupported
scheme refusing every request, AND requirements, scopes across alternatives, the Basic
challenge, paging and huge offsets, integer enum queries, PUT keeping read-only fields, a
409 without SQL, validation errors without input, a bare JSON 500, 501 and the docs switch
in production, security headers, chunked bodies over the limit, `scp`, `iss` and leeway in
tokens) and runs its gates, on Postgres too when `CORPUS_DATABASE_URL` is set.

`make test-corpus` first makes sure the Compose Postgres is up and a `generated_test`
database exists, and sets `CORPUS_DATABASE_URL`. With it set, each `--db` project runs its
tests a second time with `DATABASE_URL` pointing at that database, so the generated
persistence is proven on Postgres as well as SQLite. The suite refuses a database whose
name does not end in `_test`, because the generated tests drop and create tables. Running
`uv run pytest -m corpus` by hand without the variable skips the Postgres pass.

It is slow (each project is installed and tested) and needs the package index or a warm
uv cache for the install step; it is skipped when `uv` is not on the path. Run it whenever
you touch the generator, a template or the corpus.

## Browser end-to-end tests

```bash
make up && make demo
make e2e
```

Playwright (Chromium) against the running stack, signed in with the demo password
(`AF_DEMO_PASSWORD`). The suites live in `e2e/tests/` and cover the primary journeys:
signing in, browsing projects and spec versions with their reports and changes,
requesting a generation and following it to success, browsing files and downloading the
archive, the playground, API keys, users, the audit log and settings, and what a viewer
can and cannot do.

## Browser QA

```bash
make qa
```

`scripts/qa/qa.mjs` (Puppeteer) visits every page in light and dark mode at desktop and
phone width, fails on console errors, failed requests, broken images, error states,
horizontal overflow or empty unexplained states, and saves a screenshot of each.
`make screenshots` produces the README images and `scripts/qa/make-tour.sh` the tour GIF.

## Infrastructure

```bash
make tf-validate tf-lint tf-security
make tf-aws-on-floci
```

- `tf-validate` runs `terraform init -backend=false` and `validate` for each environment,
  with a local terraform or the pinned `hashicorp/terraform:1.16.6` image.
- `tf-lint` runs tflint v0.64.0 recursively (plugins cached in a Docker volume).
- `tf-security` runs checkov 3.3.30 over `infra/terraform`.
- `tf-aws-on-floci` copies the Terraform tree to a temporary directory, starts a
  throwaway Floci on port 4696, then plans, applies, re-plans (no additions or
  replacements allowed) and destroys the full `aws-dev` environment. It catches plan and
  apply time errors that `validate` cannot see. The repository is not modified.

`make up` also applies `local-floci` on every start.

## Sanitization

```bash
make sanitize
```

`scripts/check-sanitization.sh` scans the files git would commit for AWS access keys,
private keys, 12-digit numbers that could be account ids, AWS resource ids, RDS and
ElastiCache endpoints, common token formats, em and en dashes, and committed env files.
It prints `sanitization: clean` or the offending lines. Run it before every commit.

## In CI

`.github/workflows/checks.yml` runs lint, typecheck and unit tests for the generator, the
API and the web app on every push and pull request. The full pipeline (integration tests
with Postgres and Redis service containers, the no-Redis run, the corpus, image builds,
Terraform, security scans, e2e) is in `.github/workflows-full/` and opt-in; see its
[README](../../.github/workflows-full/README.md).
