# ADR-0005: The generator as a library shared by the CLI and the service

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

APIForge has two front doors: a CLI developers run offline, and a self-hosted service
where a team uploads specs and downloads projects. If the two produced different output
for the same input, every bug report would start with "which one did you use", the
service's file browser would show code the CLI would not write, and a CI job that
compares a committed project with a fresh generation could never trust either.

## Decision

- The generator is a plain Python package, `euron-apiforge` (import `apiforge`), in
  `apps/forge`. It has no database, no web framework and no network access. Its public
  entry points are `apiforge.generator.lint`, `apiforge.generator.generate` and
  `apiforge.archive.build_zip`.
- The CLI (`apiforge`) is a thin layer over those functions.
- The service (`apps/api`) declares the package as a path dependency and calls the same
  functions: `analyze` calls `load` and `normalize` for the lint report, the worker calls
  `generate` and `build_zip`. The API image installs both packages from the repository
  root.
- `generate` is deterministic: templates rendered in sorted order, a pinned ruff
  configuration, no clock or environment in the output. `build_zip` writes sorted entries
  with fixed timestamps (1980-01-01), fixed permissions and a pinned compression level.

## Consequences

**Good**
- **Byte-identical archives.** The service's download equals
  `apiforge generate --zip` for the same spec and options; the integration test
  `test_a_generation_runs_in_the_worker_and_its_archive_is_the_cli_output` asserts the
  hashes are equal.
- The archive SHA-256 is a stable fingerprint: it is the download ETag, the file browser's
  cache key, and something a CI job can verify.
- A retried or repeated generation is free of surprises: same input, same bytes.
- The generator is tested once (`apps/forge/tests`) and every front door inherits it.

**Bad / caveats**
- The service and the generator version together; upgrading the service upgrades the
  generator for every project. The lock file in each archive records the generator
  version that produced it.
- Formatting depends on the pinned ruff binary shipped with the package; a ruff upgrade
  can change output bytes and must be a deliberate release.

## Alternatives considered

- **The service shelling out to the CLI.** Same output, but a subprocess per lint and
  generation, string parsing of results, and a harder security story.
- **A separate generator service over HTTP.** Another network hop and deployment for no
  isolation gain: the worker already isolates generation from the API.
