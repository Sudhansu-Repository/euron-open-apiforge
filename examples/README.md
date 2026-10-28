# Examples

Small, real, runnable examples for using APIForge from scripts and CI. Each one was run
against the code in this repository.

| File | What it shows |
| ---- | ------------- |
| [`todo.yaml`](todo.yaml) | A tiny OpenAPI 3.1 spec (4 operations, bearer auth, a collection resource) to try the generator in a minute |
| [`download_latest.py`](download_latest.py) | A CI step with a read-only `afk_` API key: download the latest succeeded generation of a project and verify its SHA-256 before writing it. Standard library only |
| [`apiforge-check.yml`](apiforge-check.yml) | A GitHub Actions workflow for a repository that keeps a spec and its generated project: `apiforge lint` fails on errors, `apiforge diff` fails when the committed project is not up to date with the spec |

## todo.yaml

From a checkout (or with `pip install euron-apiforge` and plain `apiforge`):

```bash
cd apps/forge
uv run apiforge lint ../../examples/todo.yaml
uv run apiforge generate --spec ../../examples/todo.yaml --output /tmp/todo --db
uv run apiforge verify /tmp/todo
```

```
Todo 1.0.0: 4 operations, 3 models
No findings.

Todo: 4 operations into /tmp/todo/
  40 created, 0 updated, 0 unchanged, 0 of yours kept

  ok     install (0.9 s)
  ok     lint (0.7 s)
  ok     format (0.0 s)
  ok     types (6.3 s)
  ok     tests (4.8 s)
verified
```

With `--db`, `/todos` and `/todos/{todoId}` are a collection resource: `cd /tmp/todo && uv
run uvicorn app.main:app --reload`, then create a to-do at http://localhost:8000/docs
(`POST /todos` needs a bearer token signed with `JWT_SECRET`; see
[generated-project.md](../docs/guides/generated-project.md#authentication)) and read it
back with `GET /todos`. Without `--db`, every operation answers with example data from the
spec.

## download_latest.py

`make demo` prints a read-only key the first time it runs ("Read-only API key (shown
once): afk_..."). You can also create one in the web app (API keys, Create key; admins
only).

```bash
APIFORGE_API_KEY=afk_... python examples/download_latest.py pet-store
python examples/download_latest.py pet-store --url https://apiforge.example.com \
  --key afk_... --out build/pet-store.zip
```

```
pet-store generation 2 (spec v3, 40 files): pet-store-2.zip 29,626 bytes, sha256 90698d57...6b9315c verified
```

The script:

1. lists the project's generations, newest first (`GET /api/v1/projects/{slug}/generations`)
   and picks the newest with `status` `succeeded`;
2. downloads `GET .../generations/{number}/archive`;
3. hashes the bytes and compares them with the generation's `archive_sha256` and with the
   `ETag` the service sent (and with `--expect-sha256` if you pin a reviewed archive);
4. writes the zip atomically only when everything matches.

Exit codes: 0 verified, 1 no succeeded generation or a hash mismatch, 2 a usage, network or
HTTP error (the service's error code and message are printed, for example
`401 ...: invalid_api_key: Unknown API key`). API keys are read-only and rate limited (600
requests a minute unless the key has its own limit).

Because generation is deterministic, you can also compare the hash with a local
`apiforge generate --spec <the same spec> --zip out.zip` (same options): the bytes are
identical.

## apiforge-check.yml

Copy it to `.github/workflows/` in the repository that holds your spec and generated
project, and set `SPEC` and `PROJECT`. It installs the pinned generator with
`uv tool install euron-apiforge==0.1.0`, then:

- `apiforge lint "$SPEC"`: fails on errors, prints warnings and notes;
- `apiforge diff --spec "$SPEC" --output "$PROJECT" ... --json`, with the flags read from
  the project's `apiforge.lock`, and fails when anything would be created, updated,
  deleted or appended, or when a generated file was edited by hand.

When it fails, regenerate locally with the same flags and commit:

```bash
apiforge generate --spec openapi.yaml --output service --db
```

The generated project's own workflow (`.github/workflows/ci.yml` inside the project) runs
its ruff, mypy and pytest gates.
