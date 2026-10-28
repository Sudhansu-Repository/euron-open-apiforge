# euron-apiforge

The generator behind [Euron Open APIForge](https://github.com/euron-sde-team/euron-open-apiforge):
an OpenAPI 3.0 or 3.1 spec in, a FastAPI project you can run, verify and keep out. Offline,
deterministic, no account, no tokens.

```bash
pip install euron-apiforge          # or: uv tool install euron-apiforge

apiforge lint openapi.yaml
apiforge generate --spec openapi.yaml --output my-api
cd my-api && uv sync && uv run uvicorn app.main:app --reload
```

Open http://localhost:8000/docs: every operation already answers with example data that
matches the spec, so the project is a working mock before you write a line.

## What you get

- **Pydantic v2 models** with the spec's rules: required fields, formats, enums, lengths,
  ranges, patterns, `allOf` inheritance, `oneOf`/`anyOf` (discriminated when the spec says
  so), nullable fields, recursive models, and separate input models where `readOnly` or
  `writeOnly` fields differ.
- **FastAPI routes** with path, query, header and cookie parameters (spec names kept, Python
  names in your code), JSON, form and multipart bodies, file upload and download, every
  documented response.
- **Security from the spec**: bearer and OAuth2 (JWT with scopes), OpenID Connect, API keys in
  a header, query or cookie, HTTP basic. Missing or bad credentials get 401, missing scopes 403.
- **Optional persistence** (`--db`): SQLAlchemy 2 tables, an Alembic migration and working
  CRUD for collection resources (`/things` and `/things/{id}`), with paging and filters.
- **Tests that prove it**: a contract test per operation, validation and auth tests, a CRUD
  round trip per resource with `--db`, and a test that compares the OpenAPI document the app
  serves with the spec it came from.
- **A project, not a stub**: `pyproject.toml` (uv), ruff and mypy `--strict` configured and
  passing, Dockerfile, Compose, `.env.example`, Makefile, GitHub Actions, README.

## Your code survives regeneration

Generated code and your code live in different files:

| Path | Owner |
| --- | --- |
| `app/handlers/`, `app/auth.py`, `app/config.py`, `app/main.py`, project files | you: created once, never overwritten |
| `app/generated/`, `tests/generated/` | APIForge: rewritten on every generation |

Change the spec and run `apiforge generate` into the same folder: generated files are
updated, every new operation gets a stub appended to its handler module, removed operations
are reported (their handlers are kept), and `apiforge.lock` detects a generated file edited by
hand instead of overwriting it (`--force` to overwrite anyway). `apiforge diff` shows what a
regeneration would change.

## Nothing is dropped silently

`apiforge lint` lists everything APIForge noticed, with a JSON pointer into the spec:
constructs it can only approximate (an XML alternative, a `deepObject` parameter, a `not`
keyword) are warnings, guesses it made (a derived operation id) are notes, and anything that
would change what the API accepts (two routes with the same shape) is an error that blocks
generation until you accept the report (`--accept-report`).

## Verify

```bash
apiforge verify my-api
```

installs the project and runs its lint, type check and tests, which include the round-trip
comparison of the served OpenAPI with the spec.

## Commands

| Command | |
| --- | --- |
| `apiforge lint SPEC` | Validate and report (`--json` for machines). Exit code 1 on errors. |
| `apiforge generate --spec SPEC [-o DIR] [--db] [--zip FILE]` | Generate or update a project, or write a zip |
| `apiforge diff --spec SPEC -o DIR` | What generating into DIR would change |
| `apiforge verify [DIR]` | Install and run the project's own gates (needs uv) |
| `apiforge examples [--copy DIR]` | The bundled example specs |

`SPEC` is a `.yaml` or `.json` file, a folder with an `openapi.yaml` at its top, or a zip.
`$ref`s to other files of the spec are followed; URLs are never fetched.

MIT licensed. Part of the open-source initiative of ENGAGESPHERE TECHNOLOGY PRIVATE LIMITED.
