# Threat Model

The attacker's view of APIForge, organised by entry point. The controls are described in
[security.md](security.md); this document lists what could go wrong, what stops it, and
what is left.

## Scope and assumptions

- One deployment serves one team. Users are members of that team with one of three roles;
  admins and owners are trusted to upload specs and request generations.
- Specs are untrusted, whoever uploads them: a spec may come from a partner, a public
  repository or a compromised colleague's laptop, and may be built to attack the parser,
  the generator, the server or the people who will run the generated code.
- Generated code runs on the users' own machines and CI, not on the service.
- The network between clients and the service may be hostile; production runs HTTPS only.
- The AWS account, Postgres, Redis, the S3 bucket and the KMS key are trusted. A
  compromise of those is out of scope, except where noted (T16).

## Entry points

| Entry point | Who reaches it | Authentication |
| ----------- | -------------- | -------------- |
| `POST /api/v1/projects/{slug}/specs`, `.../specs/text` | Admins and owners | Session (cookie plus CSRF header, or bearer) |
| `POST /api/v1/lint` | Any signed-in user, API keys | Session or read-only API key (`afk_`) |
| `POST /api/v1/projects/{slug}/generations` | Admins and owners | Session |
| Other `/api/v1/*` | Browsers, scripts, CI | Session or read-only API key |
| `POST /api/v1/auth/login` | Anyone | Email and password |
| `/metrics` (API), port 9464 (worker) | Prometheus | `METRICS_TOKEN` (when set); worker port limited to listed in-VPC CIDRs |
| `/healthz`, `/health`, `/readyz`, `/docs`, `/openapi.json` | Anyone | None (status and the public API description only) |
| The CLI | A developer, on their own machine | None (it reads local files and writes a folder or a zip) |
| A downloaded archive | Whoever runs the generated project | Not applicable: it is code, reviewed and run by its owner |

## Threats and mitigations

STRIDE categories: Spoofing, Tampering, Repudiation, Information disclosure, Denial of
service, Elevation of privilege.

| # | Threat | STRIDE | Mitigation | Residual |
| - | ------ | ------ | ---------- | -------- |
| T1 | A hostile spec injects code into the generated project through a name, description, example, default, enum value or pattern (breaking out of a string, docstring, comment or identifier) | T, E | Names become safe identifiers once in the IR; text reaches templates only through `lit`, `doc` and `comment`; sandboxed, strict Jinja; signatures computed in Python; ruff formatting fails on invalid Python. `test_hostile.py` (a spec built to break out, plus Hypothesis property tests) and the corpus suite (the hostile project installs and passes ruff, mypy and pytest) | A template change that adds an unescaped interpolation would reopen it; CONTRIBUTING requires the filters and the hostile test covers every template the corpus reaches |
| T2 | A hostile spec makes the server fetch a URL (SSRF) through `$ref`, `servers`, `externalDocs` or an OpenID Connect URL, reaching cloud metadata or internal services | I, E | URL `$ref`s are refused before resolution (`RefError`); the service has no outbound HTTP client; other URLs are data copied into the generated project, never requested. `test_hardening.py::test_a_spec_with_url_refs_never_makes_the_server_fetch`, `test_loader.py::test_url_refs_are_never_fetched` | None by design ([ADR-0008](adr/0008-never-fetch-url-refs.md)) |
| T3 | A relative `$ref` reads a file outside the spec (`../../etc/passwd`) | I | Refs resolve only to files of the uploaded bundle; normalized paths that leave the spec's folder are refused; the server never reads the filesystem for a ref. `test_loader.py::test_refs_cannot_leave_the_spec_folder` | None known |
| T4 | A YAML bomb ("billion laughs") exhausts memory or CPU | D | 10,000 alias events while composing, 2,000,000 values visited after loading, 64 levels of nesting, 5 MiB per document; parser recursion errors are refusals. `test_loader.py::test_alias_bombs_are_refused`, `test_hardening.py::test_zip_bombs_and_yaml_bombs_are_refused_before_doing_the_work` | A spec within the budgets can still take seconds to lint; linting runs in a thread so the event loop stays free |
| T5 | A zip bomb expands to gigabytes | D | Declared sizes summed before decompression (20 MiB total, 5 MiB per file, 200 files); each member read with a cap so a lying header is caught; encrypted entries, unsupported compression and corrupt members are refused (`spec_unreadable`) instead of raising a 500. Same tests as T4 | None known |
| T5a | A tiny spec whose schemas `$ref` each other many times over makes inlining (examples, the bundled document) explode in memory and time | D | Expansion is counted per spec and bounded at 500,000 nodes; above it the spec is refused with `spec_too_complex` in a fraction of a second. `tests/test_budgets.py` (a self-referencing fan-out refused fast, a modest one still generates) | None known |
| T5b | A crafted string (an unpaired UTF-16 surrogate, a non-ASCII digit in a JSON pointer, a DEL character) crashes the loader or produces invalid output | D, T | Surrogates refused at load, non-ASCII pointer digits are a ref error, DEL is escaped in the generated `pyproject.toml` | None known |
| T6 | A YAML tag builds Python objects (`!!python/object`) | E | `SafeLoader` subclass; only JSON scalar types accepted after loading. `test_loader.py::test_tags_that_build_objects_are_refused` | None known |
| T7 | A crafted upload file name writes outside the storage folder (`../../x`, absolute paths, backslashes) | T | Name reduced to its last component and `[A-Za-z0-9._-]`; keys built from UUIDs; `LocalStorage` refuses keys that resolve outside its root. `test_storage.py::test_local_storage_refuses_path_traversal`, `test_hardening.py::test_uploaded_file_names_cannot_escape_the_storage_folder` | None known |
| T8 | Zip member names inside a spec bundle escape (`../`, absolute) | T | Normalized and refused before reading (`bundles.read_zip`); members are kept in memory, never extracted to disk. `test_loader.py::test_zip_bundles_are_read_safely` | None known |
| T8a | A hostile `apiforge.lock` (from a cloned repository or a pull request) makes `apiforge generate` compare, overwrite or delete files outside the generated folders, with or without `--force` | T | Lock entries are trusted only for relative paths under `app/generated/` or `tests/generated/` that resolve inside the project; anything else is ignored, as are non-dict `operations` entries. `test_writer.py::test_a_hostile_lock_file_cannot_delete_outside_the_generated_folders` | None known |
| T9 | The file browser serves arbitrary files (`?path=../../etc/passwd`) | I | Only paths in the generation's stored manifest are served, from the archive in storage. `test_generations.py::test_files_can_be_browsed_one_by_one` | None known |
| T10 | A spec makes the server run code (generated tests, `verify`, an import of the generated package) | E | The worker renders templates and runs only the pinned ruff formatter on files it wrote; it never installs, imports or runs the generated project. `verify` exists only on the CLI | A vulnerability in ruff's formatter fed hostile Python source would run in the worker container (read-only root filesystem, non-root user, no inbound port, egress only to AWS APIs) |
| T11 | A spec makes the generator loop or allocate without bound (deep recursion through `$ref`s, huge unions) | D | Load budgets (T4); recursion marked by component name in the IR; `GENERATION_TIMEOUT_S` bounds the worker's wait; after `GENERATION_MAX_ATTEMPTS` crashes the generation fails permanently. The 240-operation corpus spec proves scale | A timed-out generation thread keeps running until it finishes; repeated huge generations can keep a worker's CPU busy |
| T12 | A worker crashes mid-job (OOM, killed task) and the generation is lost, or two workers run it, or a slow worker overwrites the result of the worker that took over its expired lease | D, T | Claims are one transaction with `FOR UPDATE SKIP LOCKED` and a lease longer than the timeout; an expired lease is claimed again with `attempts + 1`; `worker_lost` after the maximum. The result is written only after locking the row and checking `attempts` still matches this claim; otherwise nothing is recorded (`generation lease lost`). If the project was deleted meanwhile, the stored archive is deleted. `test_generations.py::test_a_crashed_workers_job_is_retried_then_failed_with_a_reason`, `test_concurrent_workers_never_run_the_same_generation`, `test_a_worker_that_lost_its_lease_records_nothing`, `test_a_project_deleted_mid_generation_leaves_no_archive_behind` | A generation cut off by a crash costs one extra attempt |
| T13 | Someone tampers with an archive in storage, and users download planted code | T | Archives are written once and their SHA-256 is recorded on the row; the ETag is that hash; generation is deterministic, so anyone can regenerate the same spec and options (in the service or with `apiforge generate --zip`) and compare hashes. S3 is private, versioned, SSE-KMS, and the task roles are scoped to `specs/*` and `archives/*` | The download path does not re-hash the object against the row before serving it; a writer with bucket access can replace an archive. Verify the hash in CI ([examples](../../examples/README.md)) |
| T14 | Someone tampers with a stored spec so the next generation uses different input | T | The row keeps the upload's SHA-256; versioning keeps the previous object; `apiforge.lock` in every archive records the spec hash | The worker does not re-hash the spec it reads against the row before generating |
| T15 | A viewer or an API key uploads, generates, deletes or changes configuration (escalation) | E | One role dependency per route; API keys only on safe methods (403 `read_only_key` before the route runs). `test_admin.py::test_roles_are_enforced`, `test_api_keys_read_but_never_write` | None known |
| T16 | An admin escalates to owner, or the team loses its last owner | E | Only owners create users or change roles; nobody changes their own role; the last active owner cannot be demoted or disabled (rows locked while counting). `test_admin.py::test_users_keep_an_owner`, `test_hardening.py::test_two_owners_demoting_each_other_keep_an_owner` | A database superuser can change roles directly |
| T17 | A stolen session token keeps working after sign-out, a password change or a role change | S | `revoked_sessions` in Postgres; `session_version` bump on password, role and access changes; 12 hour expiry. `test_hardening.py::test_logout_ends_the_session_server_side`, `test_signed_out_session_survives_cache_eviction`, `test_admin.py::test_password_change_ends_other_sessions` | A token stolen and used before sign-out works until then |
| T18 | A stolen API key is used to read specs and archives | S, I | Read-only; per-key rate limit; optional expiry; immediate revocation (cluster-wide within a second, at most 5 s without Redis); `last_used_at` shows activity; only a peppered HMAC is stored | Until revoked, a stolen key reads every project |
| T19 | A leaked database dump yields usable keys or sessions | I, S | Peppered HMACs only; sessions are not stored (only revoked ids); the pepper and session secret live in the environment or Secrets Manager | A dump plus the pepper allows offline checking of guessed key secrets (they are 32 random bytes) |
| T20 | Password guessing | S | Argon2id, 20 attempts a minute per address, a 15 minute lockout after 5 failures counted atomically, constant-time unknown-email path. `test_admin.py::test_login_failures_and_lockout`, `test_hardening.py::test_parallel_wrong_passwords_still_lock_the_account` | Lockout can be triggered deliberately against a known email |
| T21 | A forged `X-Forwarded-For` dodges the per-address throttle | S | uvicorn trusts the header only from `FORWARDED_ALLOW_IPS`. `test_hardening.py::test_forwarded_for_cannot_dodge_the_login_throttle` | Setting `FORWARDED_ALLOW_IPS=*` behind an untrusted proxy reopens it |
| T22 | Cross-site request forgery with the session cookie | T, E | Cookie mutations need `X-APIForge-CSRF: 1`; CORS allowlist; `SameSite=Lax`. `test_admin.py::test_cookie_session_requires_csrf_header` | None known |
| T23 | A crafted body crashes the API (huge body, chunked body, lone surrogate, invalid UTF-8) | D | Body limit before parsing with chunked counting; orjson validation (422 `invalid_json`); bounded Pydantic schemas. `test_hardening.py::test_lone_surrogate_is_a_422_not_a_500`, `test_chunked_bodies_obey_the_body_limit` | None known |
| T24 | Parallel uploads of one spec create duplicates, or two specs race for one version number | T | Unique `(project_id, sha256)` and `(project_id, number)`; the loser returns the winner or gets 409; its stored object is deleted. `test_hardening.py::test_parallel_uploads_of_one_spec_store_one_version` | None known |
| T25 | Someone denies having uploaded a spec or requested a generation | R | `spec.uploaded` and `generation.queued` audit rows in the same transaction as the change, with actor and address; a trigger refuses `UPDATE` and `DELETE`. `test_admin.py::test_audit_log_records_changes_and_is_append_only` | A database superuser can drop the trigger |
| T26 | Secrets or spec content leak through logs or error messages | I | `hide_parameters=True`; log field redaction; one error envelope without stack traces; generation errors show the generator's message, not a traceback | Spec text quoted in a lint finding message is visible to every user of the project, by design |
| T27 | Redis is lost or evicted to bypass a revocation or a limit | S, D | Revocations, lockouts, roles and key hashes live in Postgres; the config cache holds key rows for at most 5 s; rate limiters pass on a KV error (protective, not a security boundary) | Up to 5 s of grace for a revoked key on another replica when the version stamp is unreachable; rate limits are off while Redis is down |
| T28 | A production deployment runs with demo secrets or unsafe options | S, E | Boot guards refuse weak or equal secrets, insecure cookies, local storage and an endpoint override on AWS. `test_config.py::test_production_guards` | Guards check shape and length, not entropy |
| T29 | `/metrics` discloses activity | I | `METRICS_TOKEN`; optional CIDR restriction at the ALB; metrics carry counts, never names or content | Unset token means public metrics on a public endpoint |
| T30 | A generated project ships insecure defaults (an open endpoint the spec secured, a blank JWT secret accepted, wildcard CORS in production) | E | Security dependencies for every declared scheme, generated auth tests (401 without credentials); `app/auth.py` fails closed on an empty secret; `app/config.py` refuses weak production settings and `*` CORS | The defaults are starting points: once you edit `app/auth.py`, its correctness is yours |

## Known limitations

- Every `$ref` key anywhere in the spec, even inside an `example`, is checked to be local
  before the validator runs, so the validator can never meet a remote reference. A literal
  `{"$ref": "https://..."}` inside example data is therefore refused, and anchor refs such
  as `#foo` are refused as "not a JSON pointer". This trades a rare false refusal for a
  guarantee that no reference is ever fetched.

## Out of scope

- A compromised AWS account, database superuser, or leaked deployment secrets.
- Denial of service through legitimate load on a deployment you operate yourself.
- The demo seed (`make demo`), which creates well-known logins on purpose and refuses to
  run with `ENVIRONMENT=production`.
- Vulnerabilities in the generated project's dependencies (FastAPI, Pydantic, SQLAlchemy):
  the generated `pyproject.toml` sets lower bounds, and keeping them updated is part of
  owning the project.
