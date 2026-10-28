# The generated project

What APIForge puts in a project, what each file does, and how to turn the mock into your
backend without losing anything on the next regeneration. The examples use the bundled
Pet Store spec (`apiforge examples --copy ./specs`), generated with
`apiforge generate --spec specs/petstore.yaml --output pet-store --db`.

- [Layout](#layout)
- [Run it](#run-it)
- [Implement a handler](#implement-a-handler)
- [Return a documented error](#return-a-documented-error)
- [Authentication](#authentication)
- [Persistence with --db](#persistence-with---db)
- [Regenerate after a spec change](#regenerate-after-a-spec-change)
- [Verify](#verify)
- [What is checked for you](#what-is-checked-for-you)
- [Ship it](#ship-it)

## Layout

```
pet-store/
  apiforge.lock                 what was generated: generator version, options, spec hash, file hashes
  app/
    main.py                     yours: the entry point (uvicorn app.main:app); middleware and setup
    config.py                   yours: settings from the environment; refuses unsafe production settings
    auth.py                     yours: how credentials are checked
    db.py                       yours (--db): the engine and sessions
    handlers/
      pets.py                   yours: one module per tag, one function per operation
    generated/                  APIForge's: rewritten on every generation, do not edit
      app.py                    build_app(): the FastAPI app, error handler, /health
      models.py                 Pydantic v2 models with the spec's validation rules
      routers/pets.py           one router per tag: the routes, calling your handlers
      security.py               one dependency per security scheme
      principal.py              Principal: who is calling
      errors.py                 ApiError, for documented error responses
      mock.py                   schema-valid example responses
      db_models.py, crud.py     (--db) SQLAlchemy tables and a repository per resource
      openapi.json              the spec, bundled into one document
  tests/
    generated/                  APIForge's: contract, validation, auth and CRUD tests, the spec round trip
  migrations/, alembic.ini      yours (--db): Alembic, with an initial migration
  pyproject.toml, Makefile, README.md, .env.example, .gitignore
  Dockerfile, .dockerignore, compose.yaml     (unless --no-docker)
  .github/workflows/ci.yml                    (unless --no-ci)
```

The rule is in the file names: everything under `generated/` belongs to APIForge, and
everything else is yours. Your files are created once and never rewritten
([regeneration.md](../architecture/regeneration.md)).

| File | Owner | What it does |
| ---- | ----- | ------------ |
| `app/main.py` | you | Calls `build_app()`, adds CORS from `CORS_ORIGINS`. Add middleware, startup hooks and routes that are not in the spec here (mark them `include_in_schema=False`, or add them to the spec) |
| `app/config.py` | you | `Settings` from the environment and `.env`: `APP_ENV`, `CORS_ORIGINS`, and the settings the spec's security schemes and `--db` need ([configuration.md](configuration.md#the-generated-projects-settings)) |
| `app/auth.py` | you | One `verify_<scheme>` function per security scheme. Returns a `Principal` or `None` (401) |
| `app/handlers/<tag>.py` | you | Your logic. Each function receives validated arguments and returns the success response |
| `app/generated/routers/<tag>.py` | APIForge | Routes with the spec's paths, parameters (spec names kept on the wire, Python names in your code), bodies, response models, documented responses and security |
| `app/generated/models.py` | APIForge | Models, enums and aliases; `XInput` models where `readOnly` or `writeOnly` fields make request and response shapes differ |
| `app/generated/mock.py` | APIForge | One function per operation (and per documented error) returning an example that validates against the schema |
| `tests/generated/test_<tag>.py` | APIForge | Per operation: answers with a documented status and a schema-valid body; rejects invalid input with 422; requires credentials where the spec does |
| `tests/generated/test_spec.py` | APIForge | Starts the app and compares the OpenAPI it serves with `app/generated/openapi.json` ([fidelity.md](../architecture/fidelity.md)) |
| `tests/generated/test_crud_<resource>.py` | APIForge | (--db) Create, read back, update, list, delete, 404 after delete |

You can add your own tests anywhere under `tests/` outside `tests/generated/`.

## Run it

```bash
cd pet-store
uv sync
uv run uvicorn app.main:app --reload        # or: make run
```

Open http://localhost:8000/docs (Swagger UI) or `/redoc`. `GET /health` answers
`{"status": "ok"}` unless the spec defines its own `/health`. Every operation answers
right away: with `--db`, collection resources store real rows in SQLite (`app.db`); every
other operation returns its example from `mock.py`.

`make check` runs what CI runs: `ruff check`, `ruff format --check`, `mypy app tests`
(strict) and `pytest`.

## Implement a handler

A generated stub, as generated without `--db` (with it, collection operations like this
one call `crud.pet` instead of returning a mock):

```python
async def get_pet(
    pet_id: int,
    x_request_id: UUID | None = None,
) -> models.Pet:
    """GET /pets/{petId}: Get a pet

    Return the 200 response. ...
    Documented errors (404): raise ApiError(status, body).
    """
    return mock.get_pet()
```

- Parameters arrive validated (a `pattern` is compiled with Python's `re`, as
  `pattern=re.compile(...)`, so look-aheads such as `^(?!admin)` work, the same engine the
  models use), with Python names (`petId` becomes `pet_id`,
  `X-Request-Id` becomes `x_request_id`); the route keeps the spec's names on the wire.
- The return annotation is the success response model. Return an instance (or anything
  Pydantic can validate into it); return `None` for a response without a body.
- For an operation with security, the handler also receives `principal: Principal` (the
  caller: `subject`, `scheme`, `scopes`, `claims`).
- Replace the body with your logic. Keep the signature: the generated router calls it with
  exactly these arguments, and mypy tells you if a spec change changed it.

```python
async def get_pet(pet_id: int, x_request_id: UUID | None = None) -> models.Pet:
    row = await pets_repository.find(pet_id)
    if row is None:
        raise ApiError(404, models.Error(code=404, message=f"No pet {pet_id}"))
    return models.Pet.model_validate(row)
```

Helpers of your own go in new modules you create (`app/services/`, `app/repositories/`);
APIForge never touches them.

## Return a documented error

`ApiError(status_code, body=None, headers=None)` from `app/generated/errors.py` answers
with that status and body. A Pydantic model is written with the spec's JSON names; other
values go through `jsonable_encoder`.

```python
from app.generated.errors import ApiError

raise ApiError(409, models.Error(code=409, message="A pet with this name exists"))
```

`mock.py` has a function for each documented error (`mock.get_pet_404()`), handy while the
real error bodies are not written yet. Validation errors (422) are FastAPI's own and need
no code.

## Authentication

For each security scheme in the spec, `app/generated/security.py` reads the credential
where the spec says it is (an `Authorization` header, an API key header, query parameter
or cookie, HTTP basic) and hands it to your `app/auth.py`:

| Scheme | Function in `app/auth.py` | Default behaviour | Settings |
| ------ | ------------------------- | ----------------- | -------- |
| HTTP bearer, OAuth2, OpenID Connect | `verify_<scheme>(token)` | A JWT signed with `JWT_SECRET` (`JWT_ALGORITHM`, optional `JWT_AUDIENCE`), requiring `sub` and `exp`; scopes from `scope` (space separated) or `scopes`. An empty secret accepts nothing | `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_AUDIENCE` |
| API key (header, query, cookie) | `verify_<scheme>(key)` | One of `API_KEYS`, compared in constant time | `API_KEYS` |
| HTTP basic | `verify_<scheme>(username, password)` | A user in `BASIC_USERS`, compared in constant time | `BASIC_USERS` |

A missing or invalid credential is 401 with `WWW-Authenticate`. For OAuth2 and OpenID
Connect, missing scopes are 403. When an operation lists alternatives (`security: [{a:
[]}, {b: []}]`), the first scheme that accepts the request wins. Operations without
security stay open. An empty `{}` alternative makes authentication optional: requests
without credentials are allowed and the handler receives no principal (the lint report
notes it as `optional_auth`).

To use your identity provider, change only `app/auth.py`: verify the token with your
provider's keys (for example PyJWT's `PyJWKClient` against your JWKS endpoint), look up the
API key in your database, and return a `Principal`. The generated dependencies and the
generated auth tests keep working as long as a valid credential gives a `Principal` and an
invalid one gives `None`. The generated tests sign tokens with the `JWT_SECRET` from
`tests/generated/conftest.py`; if you switch to asymmetric keys, override that fixture in a
`tests/conftest.py` of your own.

## Persistence with --db

With `--db`, every collection resource (`GET/POST /things` and
`GET/PUT/PATCH/DELETE /things/{id}` over one schema with an id) gets:

- a SQLAlchemy table in `app/generated/db_models.py` (JSON columns for arrays and nested
  objects);
- a `Repository` in `app/generated/crud.py` with `list` (paging with
  `limit`/`offset` or `page`/`pageSize`, equality filters on query parameters), `count`,
  `create`, `get`, `replace`, `update` (partial) and `delete`. A query parameter filters
  the column whose wire name it shares (`?status=` filters `status`, even though the
  handler's argument is `status_`); JSON columns (arrays, nested objects) are never offered
  as filters;
- handlers that call the repository and raise the documented 404 (their docstrings say the
  response is "kept in the database through `crud.<resource>`", and the handler module's
  docstring says which operations already use the database);
- `app/db.py` (yours): the engine from `DATABASE_URL` and a `session_scope()` context
  manager;
- Alembic: `alembic.ini`, `migrations/env.py` (reads `DATABASE_URL` and the generated
  metadata) and `migrations/versions/0001_initial.py`;
- `tests/generated/test_crud_<resource>.py`: a full round trip on a fresh database (SQLite
  by default). The generated `tests/generated/conftest.py` disposes the engine after each
  test, so the same tests pass on Postgres: `DATABASE_URL=postgresql+asyncpg://... uv run
  pytest` (APIForge's own corpus suite runs every `--db` project this way).

Which operations were recognised, and why others were not, is in the lint report
(`crud_*` notes). Outside production the tables are created at startup; in production run
the migrations:

```bash
uv run alembic upgrade head                                     # apply
uv run alembic revision --autogenerate -m "add pet owner"       # after a model change
```

The default database is SQLite (`sqlite+aiosqlite:///./app.db`); `compose.yaml` runs
Postgres 16 and sets `DATABASE_URL=postgresql+asyncpg://...`. With Docker, apply the
migrations from the image (it carries `alembic.ini` and `migrations/`):
`docker compose run --rm api /srv/.venv/bin/alembic upgrade head`. The migration files are
yours: after a spec change adds a field, regenerate (the table class in
`db_models.py` changes), then autogenerate a new revision.

## Regenerate after a spec change

From the project folder, with the options you generated it with:

```bash
apiforge diff --spec ../openapi.yaml --output . --db       # what would change
apiforge generate --spec ../openapi.yaml --output . --db   # do it
```

- Files under `app/generated/` and `tests/generated/` are rewritten, and `apiforge.lock`
  is updated.
- A new operation gets a stub appended at the end of its handler module; a new tag gets a
  new handler module. Nothing already in your files changes.
- A removed operation is reported; its handler stays (no route calls it any more) until
  you delete it.
- A generated file you edited is detected from its hash in `apiforge.lock`: nothing is
  written, and the files are listed. Move the change into a file you own (or change the
  spec), or pass `--force` to overwrite.
- Run `make check`: mypy points at any handler whose signature the spec change affected.

Commit the project before regenerating, so the change is a reviewable diff.

## Verify

```bash
apiforge verify .
```

installs the project with uv and runs `ruff check`, `ruff format --check`, `mypy app
tests` and `pytest`, stopping at the first failure and printing its output
([cli.md](cli.md#apiforge-verify)). It is the same as `make install check`, with one line
per step.

## What is checked for you

| Check | Where | Fails when |
| ----- | ----- | ---------- |
| The app serves its spec | `tests/generated/test_spec.py` | A route, parameter, body, response or security requirement differs from the spec (except the approximations listed in `ACCEPTED`, which the lint report announced) |
| Contract per operation | `tests/generated/test_<tag>.py` | A status code the spec does not document, or a success body that does not validate |
| Validation | same | Invalid input (a missing required field, a wrong type, an out-of-range value) is not refused with 422 |
| Auth | same | A secured operation answers without credentials |
| CRUD | `tests/generated/test_crud_<resource>.py` | The round trip breaks |
| Types | `mypy --strict` | A handler's signature no longer matches what the router passes |

When `test_spec.py` fails after you changed a route by hand, change the spec and
regenerate instead: the spec is the API's source of truth.

## Ship it

- `docker compose up --build` runs the API on port 8000 (with Postgres when `--db`).
- The `Dockerfile` is a slim Python 3.12 image, non-root (uid 10001), with a health check
  on `/health`. With `--db` it also carries `alembic.ini` and `migrations/`, so the same
  image runs `alembic upgrade head` before a production start.
- `.github/workflows/ci.yml` runs ruff, mypy and pytest on every push and pull request.
- Set `APP_ENV=production` in production: `app/config.py` then refuses a `JWT_SECRET`
  under 32 characters, API keys under 24, basic passwords under 16 and `*` in
  `CORS_ORIGINS`.
