# The `apiforge` CLI

The generator's command line ([`apiforge/cli.py`](../../apps/forge/src/apiforge/cli.py)).
It works offline, needs no account and never opens a network connection, except
`apiforge verify`, which installs the generated project's dependencies with uv. The
service's own command line, `apiforge-server`, is described in
[apps/api/README.md](../../apps/api/README.md).

- [Install](#install)
- [Spec inputs](#spec-inputs)
- [apiforge lint](#apiforge-lint)
- [apiforge generate](#apiforge-generate)
- [apiforge diff](#apiforge-diff)
- [apiforge verify](#apiforge-verify)
- [apiforge examples](#apiforge-examples)
- [Exit codes](#exit-codes)

## Install

```bash
pip install euron-apiforge          # or: uv tool install euron-apiforge
apiforge --version                  # apiforge 0.1.0
```

From a checkout: `cd apps/forge && uv sync && uv run apiforge --help`. Python 3.12 or
3.13.

## Spec inputs

Every command that takes a spec accepts:

| Input | How it is read |
| ----- | -------------- |
| A `.yaml`, `.yml` or `.json` file | One document. `$ref`s must point inside it |
| A folder | Every `.yaml`, `.yml` and `.json` file under it; the root document is `openapi.yaml`, `openapi.yml` or `openapi.json` at the top of the folder. `$ref`s may point to other files of the folder (`./schemas/pet.yaml#/Pet`) |
| A `.zip` | The same as a folder: the root document is the shallowest `openapi.yaml`, `openapi.yml` or `openapi.json`, and paths are taken relative to its folder |

Limits, the same as in the service: 5 MiB per document, 200 files and 20 MiB per spec,
64 levels of nesting, 10,000 YAML aliases, 2,000,000 values after expansion. A `$ref` to a
URL is refused with a message: download the file and pass a folder or a zip. A relative
`$ref` that leaves the spec's folder is refused. Swagger 2.0 is refused with a way forward
(convert it to OpenAPI 3 first).

## apiforge lint

```
apiforge lint SPEC [--json]
```

Loads and validates the spec and prints everything APIForge noticed, each finding with a
severity and a JSON pointer into the spec.

| Severity | Meaning |
| -------- | ------- |
| `error` | Something that would change what the API accepts or returns (two routes with the same shape, a duplicate operation id, a `$ref` to something that is not a schema, a path parameter that is not declared). Blocks generation until the report is accepted |
| `warning` | A construct APIForge approximates or leaves out (an XML alternative to a JSON body, a callback, a `deepObject` parameter, a keyword Pydantic cannot enforce). The generated `test_spec.py` lists each approximation as an accepted difference |
| `info` | A choice APIForge made for you (a derived operation id, an operation with several tags generated under the first, an ignored reserved header) |

```
$ apiforge lint specs/edge-cases.yaml
Edge Cases 0.1.0: 4 operations, 6 models
  warning /components/schemas/Loose: minProperties on an object is not enforced.
  warning /paths/~1shapes/post/callbacks: Callbacks are documentation only in this release.
  info    /paths/~1search/get: GET /search has no operationId; it is named 'get_search'.
  ...
0 errors, 11 warnings, 4 notes
```

`--json` prints `{title, version, operations, findings: [{severity, code, message,
pointer}]}` for scripts. Exit code 1 when there is at least one error.

## apiforge generate

```
apiforge generate --spec SPEC [--output DIR | --zip FILE] [--name NAME] [--db]
                  [--no-docker] [--no-ci] [--accept-report] [--force] [--framework fastapi]
```

| Flag | Default | Meaning |
| ---- | ------- | ------- |
| `--spec` | required | The spec: a file, a folder or a zip |
| `--output`, `-o` | the spec title as a slug (`pet-store`) | The project folder. Created if missing; if it already holds an APIForge project, it is updated (regeneration) |
| `--zip FILE` | | Write a zip archive instead of a folder. The archive is byte-identical to the service's download for the same spec and options |
| `--name` | from the spec title | The project and package name |
| `--db` | off | SQLAlchemy 2 models, an Alembic migration and CRUD handlers for collection resources (`/things` and `/things/{id}`) |
| `--no-docker` | | Leave out `Dockerfile`, `.dockerignore` and `compose.yaml` |
| `--no-ci` | | Leave out `.github/workflows/ci.yml` |
| `--accept-report` | | Generate even when the lint report has errors; the parts the errors name are left out |
| `--force` | | Overwrite generated files that were edited by hand (the lock file detected the edit) |
| `--framework` | `fastapi` | The target. `fastapi` is the only one in 0.1.0 |

A first generation prints a summary and the next step:

```
Pet Store: 4 operations into pet-store/
  40 created, 0 updated, 0 unchanged, 0 of yours kept

Next: cd pet-store && uv sync && uv run uvicorn app.main:app --reload
```

Generating into an existing project applies the regeneration rules
([regeneration.md](../architecture/regeneration.md)) and prints what it did: files
created and updated, your files kept, new stubs appended to handler modules, operations
no longer in the spec (their handlers are kept), generated files deleted. If a generated
file was edited by hand, nothing is written:

```
These generated files were edited since the last generation: app/generated/models.py.
Move your changes into app/handlers (which APIForge never overwrites), or pass --force
to replace them.
```

## apiforge diff

```
apiforge diff --spec SPEC --output DIR [--name NAME] [--db] [--no-docker] [--no-ci] [--json]
```

What `generate` into `DIR` would do, without writing anything. Takes the same option flags
as `generate` (pass the ones the project was generated with). Always plans as if the
report were accepted.

For a project generated before `DELETE /pets/{petId}` was added to the spec:

```
updated: app/generated/mock.py, app/generated/openapi.json, app/generated/routers/pets.py, tests/generated/test_pets.py, apiforge.lock
new stubs in app/handlers/pets.py: delete_pet
```

or `Nothing would change.` `--json` prints `{created, updated, unchanged, kept, deleted,
appended, removed_operations, conflicts}`. Exit code 1 when there is a conflict (a
generated file edited by hand). To check in CI that a committed project is up to date with
its spec, fail when `created`, `updated`, `deleted`, `appended` or `conflicts` is not
empty; [examples/apiforge-check.yml](../../examples/apiforge-check.yml) does exactly that.

## apiforge verify

```
apiforge verify [DIR]
```

Installs the generated project in `DIR` (default `.`) and runs its own gates, the same
ones its CI runs, stopping at the first failure:

| Step | Command |
| ---- | ------- |
| install | `uv sync --quiet` |
| lint | `uv run ruff check .` |
| format | `uv run ruff format --check .` |
| types | `uv run mypy app tests` |
| tests | `uv run pytest -q`: contract, validation, auth and CRUD tests, and the round trip of the served OpenAPI against the spec |

```
  ok     install (3.1 s)
  ok     lint (0.2 s)
  ok     format (0.1 s)
  ok     types (6.4 s)
  ok     tests (2.8 s)
verified
```

A failed step prints the last 40 lines of its output. Needs
[uv](https://docs.astral.sh/uv/) on the path, and the package index (or a warm uv cache)
for the install step. Each step times out after 600 s. Without uv, it prints
`apiforge: apiforge verify needs uv (https://docs.astral.sh/uv/) to install the project.`
and exits 1 (error code `tool_missing`).

## apiforge examples

```
apiforge examples [--copy FOLDER]
```

Lists the bundled example specs, or copies them into `FOLDER`:

| Spec | Shows |
| ---- | ----- |
| `petstore.yaml` | CRUD, bearer auth, enums, patterns, `readOnly` fields |
| `bookstore.yaml` | OpenAPI 3.1, discriminated unions, file upload, forms, OAuth2 scopes |
| `inventory.yaml` | CRUD with `--db`, UUID ids, `PATCH`, paging and filters |
| `secure-notes.yaml` | Every security scheme, optional auth, scopes, an API key in a cookie |
| `team-tasks.yaml` | Team Tasks, 8 operations: a requirement needing two credentials at once (AND), alternatives with and without scopes, an HTTP digest scheme APIForge cannot check (a reported error, so it needs `--accept-report`; the route then answers 401), server-managed `readOnly` fields a PUT keeps, paging without defaults, integer enums in the query string and an operation documented only by `default` |
| `edge-cases.yaml` | The lint report: `deepObject`, callbacks, webhooks, XML alternatives; a look-ahead pattern on a query parameter |

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success (`lint` with no errors, `diff` with no conflicts, `verify` passed) |
| 1 | The spec or project has problems: a lint error, a refused spec (unreadable, invalid, Swagger 2.0, a URL `$ref`), a report that blocks generation, a conflict with a hand-edited generated file, a failed verification, `verify` without uv. The message goes to stderr |
| 2 | Usage error (an unknown flag, a missing `--spec`), from argparse |
