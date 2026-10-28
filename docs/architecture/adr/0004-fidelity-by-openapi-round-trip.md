# ADR-0004: Fidelity checked by comparing the served OpenAPI document with the spec

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

"The generated project implements the spec" is the claim that matters most and the
easiest to get subtly wrong: a parameter generated as optional when the spec requires it,
a header read from a query string, a response schema missing a constraint, a security
requirement dropped from one operation. Unit tests of the generator only show that the
templates render what the generator intended. The claim needs a check from the outside,
and it has to keep running after the user edits the project.

FastAPI serves an OpenAPI document built from the routes, parameters, models and security
dependencies that actually exist in the running app.

## Decision

- Every generated project carries `tests/generated/test_spec.py`, which starts the app,
  reads the document it serves and compares it with the spec it was generated from
  (`app/generated/openapi.json`).
- The comparison is [`apiforge/fidelity.py`](../../../apps/forge/src/apiforge/fidelity.py),
  copied into the project as `tests/generated/fidelity.py`, so the project depends on
  nothing from APIForge at run time.
- Both documents are reduced to a canonical form per operation: parameters (location,
  name, requiredness, schema), the request body, responses (status codes, media type
  family, schemas) and security. Schemas are compared after inlining `$ref`s, merging
  `allOf`, unifying 3.0 `nullable` with 3.1 `null` types, ordering union members and
  marking recursion ([fidelity.md](../fidelity.md)).
- Cosmetic differences are ignored on purpose (titles, descriptions, examples, the 422
  FastAPI adds, integer and number `format` hints). Approximations the lint report
  announced are listed in the test's `ACCEPTED` as exact (operation, part) pairs; any
  other difference fails.
- The same canonical form fingerprints operations in the service to show what changed
  between spec versions.

## Consequences

**Good**
- The check runs in the generated project's CI forever, so a hand change that drifts
  from the spec fails a test with the exact operation and part.
- It catches generator bugs no unit test anticipated; the corpus suite runs it for every
  bundled spec, the hostile spec and a 240-operation spec.
- One canonical form serves fidelity and version diffs, so they agree.

**Bad / caveats**
- It checks the interface, not the behaviour: a handler that returns the wrong data still
  passes. The generated contract tests (status codes and response schemas) and validation
  tests cover part of behaviour.
- The canonical form is a judgement about what is cosmetic; a mistake there could hide a
  real difference. Each ignored aspect is documented with its reason.

## Alternatives considered

- **Snapshot tests of generated code.** Show that output did not change, not that it is
  right.
- **Contract testing tools (Schemathesis, Dredd) only.** Valuable for behaviour, but they
  need a running server and network calls; the round trip runs in-process in the
  project's own test suite.
