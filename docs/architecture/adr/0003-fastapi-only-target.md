# ADR-0003: FastAPI as the only target in 0.1.0

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

OpenAPI generators often advertise dozens of targets, and the quality varies from
production ready to barely compiling. APIForge's promise is specific: the generated
project installs, passes ruff and mypy `--strict`, serves exactly the spec and rejects
what the spec forbids. Keeping that promise for one framework already takes a corpus of
specs, a fidelity checker and a suite that installs and runs every generated project.

FastAPI is a natural first target: it is spec driven itself (it serves an OpenAPI
document derived from its routes, which makes the round-trip check possible), Pydantic v2
expresses most of JSON Schema's validation, and the generator is written in Python.

## Decision

- One target: FastAPI with Pydantic v2, optional SQLAlchemy 2 async with Alembic, pytest,
  uv, ruff and mypy.
- The target lives behind a seam: `apiforge/targets/fastapi/` holds the plan (signatures,
  decorators, imports, the file list) and the templates. Everything before it (loader,
  normalizer, IR, report, examples, fidelity) is target independent.
- The CLI keeps a `--framework` flag with the single choice `fastapi`, so scripts written
  today keep working when more targets arrive.
- More targets (Django REST Framework, Node, Go) are on the roadmap in
  [PLAN.md](../../PLAN.md).

## Consequences

**Good**
- Every claim is proven for the one target that ships, on every bundled spec, with and
  without `--db`.
- The fidelity check compares the spec with what the framework itself serves, not with
  what the generator thinks it emitted ([ADR-0004](0004-fidelity-by-openapi-round-trip.md)).

**Bad / caveats**
- Teams on other stacks get the lint report and the spec diff, but no project.
- A second target will need its own fidelity strategy where the framework does not serve
  OpenAPI.

## Alternatives considered

- **Several targets at once.** Broader appeal, thinner guarantees for each.
- **A client SDK target first.** The commercial tools (Stainless, Fern, Speakeasy)
  already cover SDKs; a backend that is yours to keep is the gap.
