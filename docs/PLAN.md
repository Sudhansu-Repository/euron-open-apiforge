# Euron Open APIForge 0.1.0: build plan

**Hand it an OpenAPI spec, get a backend you can run, trust and keep.** APIForge turns an
OpenAPI 3.x document (JSON or YAML) into a complete, editable FastAPI project: routes,
Pydantic models with the spec's validation rules, auth from the spec's security schemes,
optional SQLAlchemy persistence, tests, Docker and docs. It runs as a CLI with no account
and no network, and as a self-hosted web app where a team uploads specs, reviews what will
be generated and downloads the project.

Source brief: "Euron APIForge" (`briefs/06-apiforge.md`). Where the brief and the
repository rules differ, the rules win: MIT instead of Apache 2.0, repo
`euron-open-apiforge`, FastAPI service plus Next.js web app, Docker plus Floci plus
Terraform.

## Purpose

Backend developers and teams that design API first write the OpenAPI spec, then spend days
typing the same spec again as routes, models, validation and tests, and the two drift apart
from the first commit. Existing generators help once and then get in the way: their output
is a stub that does not run, misses polymorphic models and array parameters, does not look
like code anyone would write, and regenerating after a spec change overwrites the code you
added. **A forge must produce something that holds up under use: APIForge must generate a
project that installs, passes its own tests and type checks, serves exactly the API the
spec describes (checked by comparing its OpenAPI output with the input), rejects every
request the spec forbids, answers every operation with schema-valid data before you write a
line, and lets you regenerate after a spec change without losing a line of your code.**
The outcome it guarantees: the spec stays the source of truth, the generated code is plain
and yours, and nothing the spec says is silently dropped: anything APIForge cannot express
is listed in a report with its location.

### Comparable products (researched October 2026)

| Product | What it is | Gap APIForge fills |
| --- | --- | --- |
| OpenAPI Generator, `python-fastapi` server template (Apache 2.0) | The broad open-source generator (Java), server stubs in many languages | Stubs, not a running service; regeneration either overwrites your code or freezes excluded files; no tests that prove the stub matches the spec |
| fastapi-code-generator (MIT, one maintainer) | Spec to FastAPI routes plus models via datamodel-code-generator | Self-described experimental; known gaps with discriminated unions and array query parameters; no persistence, auth, tests or regeneration story |
| datamodel-code-generator (MIT) | Spec or JSON Schema to Pydantic models | Models only |
| Stainless, Fern, Speakeasy, APIMatic | Commercial generators, SDK focused | Cloud-bound, client SDKs rather than backends |
| Prism, Mockoon, MockMyData | Mock servers from a spec | A mock is not a backend you keep; you start over when you build the real one |

What makes ours worth starring: one generated project that is a mock on day one and your
backend on day thirty; regeneration that keeps your code (generation gap: generated code
and your code live in separate files, and a lock file detects edits); proof instead of
promises (every generation can be verified: install, tests, mypy, and a round-trip
comparison of the served OpenAPI with the input); a lint report that names every feature it
could not express; deterministic, local-first, no tokens.

## Acceptance criteria (each is an automated test)

1. **It runs:** for every spec in the bundled corpus, the generated project installs, its
   generated tests pass, and the app starts and answers `GET /health` (integration, the
   corpus suite runs the generated projects for real).
2. **It is the spec:** the generated app's `/openapi.json` matches the input spec with zero
   differences in paths, operations, parameters (name, location, required, schema),
   request bodies and responses (status codes, media types, schemas), for every corpus spec
   (integration, `apiforge verify`).
3. **It validates:** a request the spec forbids (missing required field, wrong type, value
   out of range, unknown enum value, pattern mismatch, too many items) gets 422 from the
   generated app; a valid one does not (generated tests plus integration).
4. **A mock on day one:** before any code is written, every operation answers with a
   status code from the spec and a body that validates against that response's schema
   (integration over the corpus).
5. **Regeneration keeps your code:** edit a handler, change the spec (add an operation, add
   a field, remove an operation), regenerate: the edit is untouched, the new operation has a
   new stub, the field appears, the removed operation is reported with its handler kept;
   a hand-edited generated file is detected from the lock file and never overwritten
   without `--force` (integration).
6. **Deterministic:** the same spec and options produce a byte-identical archive, on the
   CLI and the web app (integration, archive hash; the web download equals the CLI output).
7. **Clean code:** generated projects pass `ruff check`, `ruff format --check` and
   `mypy --strict` (integration over the corpus).
8. **Nothing silent:** every spec construct APIForge cannot express (for example an XML
   body, a callback, a link) appears in the lint report with its JSON pointer and a
   severity, and generation proceeds without it only when the user accepts the report
   (unit plus integration).
9. **A hostile spec is inert:** names, descriptions, examples and patterns from the spec
   cannot inject code; a spec built to break out of identifiers, strings and docstrings
   generates code that compiles, passes mypy and contains no spec text outside string
   literals and comments (unit, property tests).
10. **Local-first:** the CLI generates and lints with no network (sockets blocked in the
    test) and no account; external `$ref`s are resolved only from local files on the CLI and
    never fetched by the server (unit plus integration, SSRF test).
11. **Auth from the spec:** with bearer, API key or basic security on an operation, the
    generated app answers 401 without credentials, 401 with a bad token and 200 with a valid
    one; operations without security stay open (generated tests plus integration).
12. **Persistence when asked:** with `--db`, collection resources (`/things`,
    `/things/{id}`) get SQLAlchemy models, an Alembic migration and working CRUD: create,
    read back, update, list with pagination, delete, 404 after delete (generated tests on
    SQLite, and again on Postgres in the corpus suite).

## Scope

**In 0.1.0**

- **Input:** OpenAPI 3.0 and 3.1, JSON or YAML, single file or a zip with relative `$ref`s.
  Safe YAML loading (no tags, alias and size limits). Swagger 2.0 is detected and refused
  with a clear message (conversion is on the roadmap).
- **Lint:** structural validation (`openapi-spec-validator`), plus APIForge's own report:
  unsupported constructs, ambiguous names, missing operation ids (derived and shown),
  duplicate routes, unused components, each with a JSON pointer.
- **Model (IR):** a normalized intermediate representation (operations, parameters,
  bodies, responses, schemas, security) that every later step uses; testable on its own.
- **FastAPI target:**
  - Pydantic v2 models: objects, enums, nullable, formats (date, date-time, uuid, email,
    uri, byte, binary), constraints (length, range, pattern, items, multipleOf),
    `additionalProperties`, `allOf` composition, `oneOf`/`anyOf` with and without a
    discriminator, recursive schemas, `readOnly`/`writeOnly` (separate input and output
    models where they differ).
  - Routers per tag; path, query, header and cookie parameters including arrays and
    `explode`/`style` for form and simple; JSON, form and multipart bodies; file upload
    and download; multiple responses with `response_model`.
  - Security: HTTP bearer (JWT verification with a configurable secret; JWKS is on the roadmap), API key
    (header, query, cookie), HTTP basic, OAuth2 password flow scaffold; scopes mapped to a
    dependency.
  - **Generation gap layout:** `app/generated/` (models, routers, security, owned by
    APIForge, regenerated) and `app/handlers/` (one module per tag, a function per
    operation, created once, yours). Fresh handlers return a schema-valid example built
    from the spec's `example`/`examples` or synthesized from the schema, so the project is
    a mock immediately.
  - `apiforge.lock`: generator version, options, spec hash and a hash per generated file.
    `apiforge generate` into an existing project updates generated files, adds stubs for
    new operations, reports removed ones and refuses to overwrite hand-edited generated
    files unless `--force`.
  - Optional `--db` (SQLAlchemy 2 async, SQLite or Postgres, Alembic) with CRUD handlers for
    collection resources. (Auth helpers for issuing tokens are on the roadmap; 0.1.0
    verifies credentials, it does not issue them.)
  - Project files: `pyproject.toml` (uv), ruff and mypy config, Dockerfile, Compose
    (with Postgres when `--db`), `.env.example` without secrets, README with the
    operations table, Makefile, GitHub Actions workflow, pytest suite: a contract test per
    operation (status and response schema), validation tests, auth tests, CRUD tests.
- **CLI (`apiforge`):** `lint`, `generate`, `verify` (install, test, mypy and round-trip
  the generated project locally), `diff` (what a regeneration would change), `examples`.
  Published as the `euron-apiforge` package.
- **Web app and API (self-hosted):** projects with spec versions, upload or paste a spec,
  lint report with pointers into the spec, endpoint and schema browser, generation options,
  generated file tree with a code viewer, download ZIP, what changed between two spec
  versions (operations added, removed and changed), generation history, read-only API keys
  for CI, users with owner, admin and viewer roles, audit log. Generation runs in a worker;
  specs and archives are kept in S3. **The server never executes generated code.**
- **Demo:** bundled example specs (a pet store, a bookstore with polymorphism and files, an
  auth-heavy API, a CRUD-heavy inventory API, plus edge-case specs) and seeded projects
  with history.

**Roadmap (not in 0.1.0)**

- AI-assisted handler bodies with the user's own model and key (opt-in, never required).
  Decided 2026-10-28: the user left the call to us with production readiness as the goal,
  so 0.1.0 ships the deterministic generator only. A generator people can trust has to
  produce verified output first; an AI step comes once the generated code is proven, and
  its output will go through the same generated tests.
- Swagger 2.0 import through conversion; AsyncAPI.
- More targets: Django REST Framework, Node (Express or Nest), Go.
- Breaking-change classification between spec versions (beyond added, removed, changed).
- A VS Code extension and a pre-commit hook that runs `apiforge verify`.

## Design

### Repository layout

```
apps/forge/   the generator: `apiforge` package and CLI (pure Python, no database), the
              target templates (Jinja2), the corpus of example specs, its own tests
apps/api/     the service: `apiforge_server` (FastAPI), domains auth, users, keys, audit,
              projects (with spec versions, the playground and the examples),
              generations, overview, system; a worker for generations
apps/web/     the Next.js web app
```

The service imports the generator as a library (`apps/forge` is a path dependency), so
the CLI and the web app produce byte-identical output for the same input.

### Generator pipeline

`load` (bytes to document; safe YAML; size and alias limits; local refs only) ->
`validate` (openapi-spec-validator) -> `normalize` (dereference, derive names and operation
ids, build the IR) -> `lint` (report) -> `plan` (the file set: path to template plus
context) -> `render` (Jinja2 with a sandboxed environment, every spec string passed through
`py_literal`, `py_identifier` or `docstring` filters) -> `format` (ruff format in process)
-> `write` (lock file, generation-gap rules) or `archive` (zip with fixed timestamps and
sorted entries).

### Storage decision

Postgres for projects, spec versions (metadata and hash), generations and their manifests,
users, keys and audit; S3 for spec bodies and generated archives (rows keep a key); Redis
optional for rate limits, the lint cache (by spec SHA-256) and the config version stamp. Same choice as every reference.

### Data model (service)

`users`, `api_keys`, `audit_log` (from the references); `projects` (name, slug, owner,
default options); `spec_versions` (project, number, title, version, hash, storage key,
lint summary, created by); `generations` (project, spec version, options JSON, status,
archive key, archive hash, file manifest JSON, report JSON, timings); `jobs` handled by a
lease on `generations` rows (no queue service).

### Ports (project 06)

web 4610, api 4630, postgres 4642, redis 4679, floci 4666, tf-aws-on-floci 4696.

### Terraform

Modules network, database, cache, storage (one artifacts bucket: `specs/` kept,
`archives/` expiring), kms, secrets, ecr, service (api, worker, web behind an ALB with
WAF), observability; environments `local-floci`, `aws-dev`, `aws-prod`.

## Test plan

- **Unit (forge):** loader limits, IR normalization per construct, naming and escaping
  (property tests with hostile strings), example synthesis validates against its schema,
  lint findings, lock file and merge rules, determinism.
- **Corpus suite (forge, integration):** for every bundled spec, generate, then in a
  temporary virtual environment: install, ruff, mypy, pytest, start the app, round-trip
  `/openapi.json`, call every operation as a mock and validate responses. The `--db`
  projects run their tests a second time on Postgres.
- **Unit and integration (service):** every endpoint, roles, jobs and leases, S3 and local
  storage, Redis or none, SSRF refusal, size limits, audit.
- **OpenAPI drift, e2e (Playwright), Terraform gates, sanitization, browser QA:** as in the
  references.

## Honest labelling

- The corpus is APIForge's own set of specs written to cover the constructs above, plus the
  OpenAPI Initiative's example documents (Apache 2.0, attributed). The README says which
  constructs are supported, which are reported as unsupported, and that very large public
  specs are a roadmap benchmark, not a 0.1.0 guarantee.
- Generated handlers are examples until you write them; the README never calls a mock a
  finished backend.
