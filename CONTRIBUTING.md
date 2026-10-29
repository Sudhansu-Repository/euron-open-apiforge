# Contributing

Thanks for helping improve Euron Open APIForge. This guide covers the layout, the
workflow, the bar a change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. See
  [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Project layout

```
apps/forge/       the generator (package euron-apiforge, import apiforge, CLI apiforge): spec loading and
                  validation, the FastAPI target and its templates, the bundled spec corpus; tests/
apps/api/         FastAPI service, worker and CLI (package apiforge_server, CLI apiforge-server):
                  src/apiforge_server/<domain>/, tests/unit, tests/integration; depends on apps/forge
apps/web/         Next.js 15 dashboard: src/app (routes), src/features/<domain>, src/components, src/lib
e2e/              Playwright suites against make up && make demo
infra/docker/     api (built from the repo root: forge + api) and web Dockerfiles (multi-stage, non-root, pinned bases)
infra/terraform/  modules/ and envs/{local-floci,aws-dev,aws-prod}
deploy/compose/   compose.yaml plus the floci and aws overlays, .env.example
scripts/          sanitization, env generation, test database, test matrix, tf-aws-on-floci, AWS deploy, qa/
docs/             architecture (HLD, LLD, data model, security, subsystems, ADRs), guides, api/openapi.yaml
examples/         a CI download script, a GitHub Actions workflow and a tiny spec
```

[docs/architecture/LLD.md](docs/architecture/LLD.md) describes every package.

## Development setup

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and
pnpm 9 (`corepack enable`).

```bash
make up          # Postgres, Redis, Floci (provisioned by Terraform), api, worker, web
make demo        # demo users, projects from the bundled specs and generated archives
make test        # unit tests: generator, API and web
```

Working on one part outside containers:

```bash
cd apps/forge && uv sync && uv run apiforge --help            # generate a project from a spec on disk
cd apps/api   && uv sync && uv run apiforge-server --help     # serve, worker, migrate, seed-demo, ...
cd apps/web   && pnpm install && pnpm dev                     # http://localhost:4610, proxies /api to :4630
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack in detail.

## Before you open a pull request

Each of these must pass ([docs/guides/testing.md](docs/guides/testing.md) explains what
each covers):

```bash
make lint typecheck test
make test-integration                  # the API against real Postgres and Redis
make test-matrix                       # when you touched a backend (cache, storage); needs make up
make test-corpus                       # when you touched the generator or its templates (slow)
make e2e                               # when you touched a dashboard flow or infrastructure
make qa                                # when you touched the UI: every page, light and dark, desktop and phone
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make tf-aws-on-floci                   # same: apply and destroy aws-dev against Floci
make openapi                           # when you changed an endpoint (a test checks drift); then pnpm gen:api in apps/web
make sanitize                          # no credentials, account ids, resource ids or dashes
```

## Conventions

### The generator (`apps/forge`)

**Everything after `normalize` reads the IR.** Templates, the example builder, the
tests generator and the report agree because they share one interpretation of the spec
(`apiforge/ir.py`). Never read the raw spec in `plan.py` or a template; add what you need
to the IR instead.

**Spec text is data.** In a template, a value that came from the spec reaches the output
only through `|lit` (a Python literal), `|doc` (a docstring body) or `|comment` (one comment
line), and a name only as the safe identifier the IR already holds (`.name`, never
`.wire` in code position). There is no raw filter; do not add one. If you add a template
or a new interpolation, extend the hostile spec in `tests/test_hostile.py` so it reaches
your code path.

**Logic lives in Python, not in templates.** Signatures, decorators, imports and test cases
are computed in `targets/fastapi/plan.py`; templates loop and print. A template with an
`if` chain longer than a few lines belongs in `plan.py`.

**Deterministic output.** No clock, no environment, no unordered iteration in anything
that reaches a file. Sort what you emit. `tests/test_generator.py::test_the_same_input_gives_the_same_bytes`
must keep passing, and the archive hash in the service must keep matching the CLI.

**Nothing silent.** A construct you cannot express is reported, not skipped:
`report.warning(code, message, pointer)` when only documentation or strictness is lost,
`report.error(...)` when the generated API would accept or return something the spec does
not allow, `report.info(...)` for a choice made on the user's behalf. Codes are
`snake_case` and stable (users filter on them); messages say what APIForge did and what the
user can do.

#### How to add a template

1. Write `targets/fastapi/templates/<name>.j2`. Keep it free of logic; take every value
   from the context.
2. Add one `gen("<path in the project>", "<name>.j2", owner=...)` line in
   `FastApiTarget.files()`: `owner="generated"` for files APIForge rewrites (they must
   live under `app/generated/` or `tests/generated/`), `owner="user"` for files created
   once and then owned by the user. Gate optional files on `self.options`.
3. If the file is Python, it is formatted by ruff and must pass the generated project's
   own `ruff check` and `mypy --strict`.
4. Run `uv run pytest` and `make test-corpus`; update the layout tables in
   [generated-project.md](docs/guides/generated-project.md).

#### How to add a lint finding

1. Find where the construct is read (`normalize.py` for operations, parameters, bodies and
   security; `schemas.py` for schemas; `crud.py` for `--db`) and call
   `self.report.warning("your_code", "What happened and what to do.", pointer)` with the
   construct's JSON pointer (`pointer(...)` in `report.py` builds one).
2. If the generated code approximates the construct and the served OpenAPI will differ,
   record the (operation, part) pair in `op.accepted` or `api.accepted` so the generated
   `test_spec.py` lists it in `ACCEPTED`; any unlisted difference fails the test.
3. Add a unit test in `tests/test_normalize.py`; if the construct is common, add it to
   `corpus/edge-cases.yaml` so the corpus suite exercises it.

#### How to add an IR field

1. Add the field with a default to the right dataclass in `ir.py` (`OperationDef`,
   `ParamDef`, `FieldDef`, `ModelDef`, ...). Names in the IR are safe identifiers; keep the
   original under a `wire` or `alias` field.
2. Populate it in `normalize.py` or `schemas.py`, once.
3. Use it in `plan.py`, then in templates through the view or context.
4. Test it in `tests/test_normalize.py` with a minimal spec (`tests/conftest.py::minimal`).

#### How to add a target option

1. Add the field to `GenerateOptions` in `options.py` and to `from_dict`'s list of known
   keys. It is recorded in `apiforge.lock` automatically.
2. Add the CLI flag in `cli.py` (`parser()` and `_options()`), for both `generate` and
   `diff`.
3. Add it to `GenerationOptions` in `apps/api/src/apiforge_server/projects/schemas.py`, so
   projects and generations can carry it, then `make openapi` and `pnpm gen:api`.
4. Use it in `plan.py` and the templates; extend `test_corpus.py`'s cases if it changes
   what gets generated; document it in [cli.md](docs/guides/cli.md).

#### How the corpus suite works

`apps/forge/src/apiforge/corpus/` holds the bundled example specs (they also ship as
`apiforge examples` and as the service's examples). `tests/test_corpus.py`, marked
`corpus` and excluded from `make test`, generates every corpus spec with and without
`--db`, the hostile spec and a synthesized 240-operation spec, writes each project to a
temporary folder and runs `apiforge verify` on it (`uv sync`, ruff, format check, mypy,
pytest). With `CORPUS_DATABASE_URL` set (`make test-corpus` sets it to a `generated_test`
database it creates), every `--db` project runs its tests a second time on Postgres. A
failing step fails the test with that step's output. `tests/test_hardening.py` adds one
more corpus test: it generates the team-tasks spec, appends runtime checks to that
project's own tests and runs them in the live app; when you fix how generated apps behave,
add a source check there and, if it needs a running app, a runtime check. Run it with
`make test-corpus` whenever you touch the generator, a template or the corpus. To add a
spec, drop it in `corpus/` (a realistic API that exercises something the others do not),
add its features to `EXAMPLE_FEATURES` in `apps/api/src/apiforge_server/projects/service.py`,
and run the suite.

### The service (`apps/api`)

**Package by domain.** `apps/api/src/apiforge_server/<domain>/` owns its `router.py` (HTTP
only), `schemas.py` (the public contract), `service.py` (rules) and `models.py`.
Dependencies point inward: router, service, data. A domain calls another domain's service,
never its router.

**The server never executes generated code and never calls out.** No route or job may
install, import or run a generated project, and there is no outbound HTTP client in the
service. A change that would weaken either needs an ADR first.

**Specs are untrusted.** Every byte a user sends goes through the generator's loader with
its limits before anything else looks at it. File names are sanitized; object keys are built
from ids.

**Background work is coordinated in Postgres.** The worker claims rows with
`FOR UPDATE SKIP LOCKED` and a lease; every outcome is written to the row. Never rely on
in-process locks alone.

**Redis is optional.** Every Redis use goes through `core/kv.py`, has an in-process
fallback, and treats a Redis error as a miss or a pass. Security state never lives only in
the KV store. The test matrix runs the whole integration suite without Redis.

**External systems sit behind a Protocol.** Storage (`ObjectStorage`) and the KV store
(`KV`). Adding a backend means adding an implementation, chosen by configuration, not
editing call sites. No emulator-specific branches.

**Caching is documented.** A new cache or a change to one updates the caching table in
[HLD.md](docs/architecture/HLD.md#caching-layers), with its key, TTL, invalidation trigger
and the test that proves invalidation. Content-addressed caches (keyed by a SHA-256) need
no invalidation; say so.

**Configuration is validated.** A new setting goes in `core/config.py`, is documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR, and
security-relevant ones are enforced by `Settings.guard()` at boot.

**Database changes are new migrations.** Change the models, then run
`make migration MSG="what changed"`: it migrates the local Postgres and autogenerates a
revision under `apps/api/src/apiforge_server/migrations/versions/` for you to review.
Indexes and constraints are declared on the models (`__table_args__`), so autogenerate sees
them. Never edit an applied revision. Indexes for every new filter the API exposes belong in
the same revision.

### Everywhere

**Frontend.** Routes in `src/app` stay thin; each screen lives in `src/features/<domain>`
with its TanStack Query hooks in `api.ts`. Query keys come from `lib/query-keys.ts`, and
each query picks a deliberate `staleTime` class. API types are generated from the OpenAPI
document, never written by hand. Every async view has loading, error and empty states, and
every empty state says what to do next.

**Comments explain why.** The code says what it does. Comments are for the constraint, the
incident, or the trade-off that made it this way.

**Style.** ruff and mypy `--strict` for Python (generator and API); ESLint and TypeScript
strict for the web. No em dashes or en dashes anywhere, including UI copy, generated code
and commit messages (the sanitization check enforces it).

## Commit messages

Imperative mood with an optional scope: `forge: report callbacks with their pointer`,
`worker: fail a generation after its last lease`. Explain the why in the body when it is
not obvious. No dashes in messages.

## Architecture decisions

Significant decisions are recorded in [docs/architecture/adr/](docs/architecture/adr/).
If your change reverses or extends one, add a new ADR rather than editing the old one.
