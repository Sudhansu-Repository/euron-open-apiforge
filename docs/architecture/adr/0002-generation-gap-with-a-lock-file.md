# ADR-0002: The generation gap with a lock file, instead of merge markers

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

A generator that overwrites the code you added is used once. Specs change for the life of
an API, so regenerating into an existing project has to be safe. Existing generators
either overwrite (losing work), freeze files listed in an ignore file (so spec changes stop
reaching them), or write merge markers into source files (so every regeneration is a
manual merge, and a half-resolved file does not compile).

## Decision

- **Separate files by owner** (the generation gap pattern). APIForge owns
  `app/generated/**`, `tests/generated/**` and `apiforge.lock` and rewrites them on every
  generation. The user owns `app/handlers/**` (one module per tag, one function per
  operation), `app/auth.py`, `app/config.py`, `app/main.py`, `app/db.py`, the project
  files and the Alembic files: created when missing, never rewritten.
- **The generated routers call the user's handlers.** A spec change that changes a
  handler's signature is a mypy error in the user's file, not a silent mismatch.
- **A lock file records what was generated**: generator version, options, the spec's
  title, version and SHA-256, every operation (function, module, method, path) and the
  SHA-256 of every generated file.
- **Rules, not merges** ([regeneration.md](../regeneration.md)): a generated file whose
  hash differs from the lock is a conflict and nothing is written unless `--force`; a new
  operation gets a stub appended to the end of its handler module; a new tag gets a new
  module; a removed operation keeps its handler and is reported; a generated file that is
  no longer produced is deleted if unedited.
- `apiforge diff` shows what a regeneration would do without writing.

## Consequences

**Good**
- Regeneration is safe by construction: no user file is ever rewritten, and no generated
  file edited by hand is overwritten silently.
- Appending is the only change to a user file, and nothing already in it changes, so the
  user's version control shows a clean addition.
- The lock file makes the archive self-describing (which spec, which options, which
  generator).

**Bad / caveats**
- Users must put their code in the files they own. A fix inside `app/generated/` is a
  conflict on the next generation (by design; move it, or change the spec).
- A removed operation's handler stays until the user deletes it.
- Renaming an operation id looks like a removal plus an addition.

## Alternatives considered

- **Three-way merge with markers.** Keeps everything in one file but turns every
  regeneration into conflict resolution and can leave code that does not compile.
- **Protected regions inside generated files** (`# BEGIN USER CODE`). Fragile under
  formatting and refactoring, and the generator still rewrites the surrounding file.
- **Subclassing generated base classes.** Natural in some languages, awkward for FastAPI
  route functions; calling plain handler functions is simpler and type checked.
