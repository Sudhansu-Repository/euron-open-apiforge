# The generator

`apps/forge` is a plain Python package (`euron-apiforge`, import name `apiforge`). It has no
database and no network access; the CLI and the web service both call the same
`apiforge.generator.generate`, which is why their archives are identical.

## Pipeline

```
bytes ─▶ load ─▶ validate ─▶ normalize ─▶ (detect CRUD) ─▶ plan ─▶ render ─▶ format ─▶ files
                                  │
                                  └─▶ report (findings with JSON pointers)
```

| Step | Module | What it does |
| --- | --- | --- |
| load | `loader.py`, `bundles.py` | JSON or YAML to plain values with a safe loader (no tags, timestamps stay strings), size, depth and expansion limits; zips read with declared sizes checked before decompression; `$ref`s resolved only inside the bundle |
| validate | `normalize.validate` | Swagger 2.0 refused with a way forward; every `$ref` checked to be local; `openapi-spec-validator` on a private temporary copy |
| normalize | `normalize.py`, `schemas.py` | The intermediate representation (`ir.py`): operations, parameters, bodies, responses, security, models. Names are made safe here, once |
| detect CRUD | `crud.py` | With `--db`: which operations form collection resources |
| plan | `targets/fastapi/plan.py` | Every signature, decorator and import list, computed in Python |
| render | `render.py` + `targets/fastapi/templates` | A sandboxed, strict Jinja environment; spec text reaches the code only through the `lit`, `doc` and `comment` filters |
| format | `render.format_python` | The pinned ruff binary sorts imports, removes unused imports in `app/generated/` and `tests/generated/` only (handler modules keep their convenience imports) and formats, with a fixed configuration; each ruff call times out after 120 s, and a failure reports ruff's output |
| write / archive | `writer.py`, `archive.py` | The generation gap on disk, or a byte-identical zip |

## The intermediate representation

Everything after `normalize` reads the IR only: `ApiDef` holds `OperationDef`s (with
`ParamDef`, `BodyDef`, `ResponseDef`, security alternatives) and `ModelDef`s (objects, enums,
aliases). Names in the IR are already safe Python identifiers; the `wire` names are what the
HTTP API uses. A single interpretation keeps the routes, the handlers, the mocks, the tests
and the report consistent with each other.

## Schemas to models

| Spec | Generated |
| --- | --- |
| `components/schemas/X`, an object | `class X(ApiModel)`; `allOf` object members become base classes |
| A string or integer enum component | `StrEnum` / `IntEnum` |
| Arrays, unions, primitives as components | module-level aliases |
| Inline objects | a named model (`PetOwner` for `Pet.owner`) |
| `nullable` (3.0), `type: [x, "null"]` (3.1) | `T \| None` |
| `oneOf`/`anyOf` with a discriminator over object components | `Annotated[A \| B, Field(discriminator=...)]`, each variant's field narrowed to a `Literal` |
| Constraints | `Field(min_length=..., pattern=..., ge=...)`, nested with `Annotated` on items |
| `readOnly` / `writeOnly` | an `XInput` model for request bodies when the shapes differ |
| `not`, `if`, `patternProperties`, `prefixItems`, ... | approximated and reported |

Every model inherits `ApiModel`: it reads field names or JSON names, writes JSON names and
uses Python's regular expression engine, so patterns with lookarounds work.

## Mocks and examples

`examples.py` builds a schema-valid example for every request and response: the spec's own
`example`, `examples` or `default` when they fit the schema, otherwise a value synthesized
from the type, format, enum and constraints. A value for a `pattern` is built by walking the
regular expression (`sample_pattern`); patterns it cannot sample (lookarounds,
backreferences) fall back to a literal and are covered by the spec's examples when present.
The same input always gives the same value. With `APP_ENV=production`, an operation whose
handler still returns its example answers 501 `{"detail": "Not implemented"}` instead, and
logs a warning the first time it is called, so a mock never reaches users by accident.

## Determinism

Nothing in the output depends on the clock, the machine or the environment: templates are
rendered in sorted order, ruff runs with a pinned configuration, and the zip has fixed
timestamps, fixed permissions and sorted entries. `tests/test_generator.py` asserts the
archive hash is stable, and the service's integration test asserts the web app's archive
equals the CLI's.
