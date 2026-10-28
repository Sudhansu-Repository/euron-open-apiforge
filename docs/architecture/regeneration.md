# Regeneration: keeping your code

A generator that overwrites the code you added is used once. APIForge separates generated
code from yours by file, records what it generated, and applies a small set of rules when
you generate into an existing project (`writer.py`).

## Ownership

| Owner | Paths | On regeneration |
| --- | --- | --- |
| APIForge | `app/generated/**`, `tests/generated/**`, `apiforge.lock` | rewritten |
| You | `app/handlers/**`, `app/auth.py`, `app/config.py`, `app/main.py`, `app/db.py`, `pyproject.toml`, README, Docker and CI files, Alembic files | created when missing, never rewritten |

The generated routers call your handlers (`app/handlers/<tag>.py`), so mypy tells you when a
spec change changed a handler's signature.

## The lock file

`apiforge.lock` records the generator version, the options, the spec's title, version and
SHA-256, every operation (function, module, method, path) and the SHA-256 of every generated
file. It is what makes the rules below safe.

The lock is read from disk, so it is treated as untrusted input (it may arrive in a cloned
repository or a pull request). Only entries for relative paths under `app/generated/` or
`tests/generated/` that stay inside the project are used; anything else (`../x`, an absolute
path, a handler module) is ignored, so a crafted lock can never make a regeneration delete
or compare a file outside the generated folders, with or without `--force`.

## Rules

1. **A generated file edited by hand** (its hash differs from the lock) is a conflict: nothing
   is written, and the files are listed. Move the change into a file you own, or pass
   `--force`.
2. **A new operation** gets a stub appended to the end of its handler module. Nothing that is
   already in the file changes; the stub returns example data until you write it.
3. **A new tag** gets a new handler module.
4. **A removed operation** keeps its handler and is reported, so you delete it when you are
   ready (the route is gone, so it is no longer called).
5. **A generated file no longer produced** (a tag that went away) is deleted if it was not
   edited; otherwise it is a conflict like rule 1. Only files under the generated folders
   are ever deleted.
6. **Your files** are never touched, apart from rule 2.

`apiforge diff --spec openapi.yaml -o .` prints what a regeneration would do without writing.

## Tested

`apps/forge/tests/test_writer.py` edits a handler and `main.py`, changes the spec (adds an
operation, adds a field, removes an operation, adds a tag), regenerates, and checks every
rule; a hand-edited generated file is refused, then overwritten only with `force`.
A crafted lock file with paths outside the generated folders (`../victim.txt`, an absolute
path, a handler module) deletes nothing, with or without `force`.
