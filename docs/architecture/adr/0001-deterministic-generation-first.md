# ADR-0001: Deterministic generation first; AI-assisted handlers on the roadmap

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

The source brief for APIForge mentioned AI-assisted handler bodies: let a model write the
business logic behind each generated route. Spec-to-code is also a task language models
can attempt end to end. But the people APIForge is for (teams that design API first) need
to trust the output before they adopt it: it must compile, pass mypy `--strict`, serve
exactly the spec, reject what the spec forbids, and come out the same every time so it can
be reviewed, diffed and regenerated. A model in the loop makes every one of those harder
to guarantee and adds a network dependency, an account, a key and a cost to a tool whose
CLI should run offline.

## Decision

- 0.1.0 ships a **deterministic generator only**: templates over a normalized
  intermediate representation, formatted by a pinned ruff, with no model, no network and
  no clock or environment in the output.
- Fresh handlers return **schema-valid example data** built from the spec's own examples
  or synthesized from the schema, so the project is a working mock before anyone writes a
  line.
- With `--db`, collection resources get **working CRUD** handlers generated from the
  resource shape, which covers a large share of real handler code without guessing.
- An opt-in AI step (the user's own model and key, never required) is on the roadmap in
  [PLAN.md](../../PLAN.md). When it comes, its output goes through the same generated
  tests and fidelity check as hand-written code, and it writes only into files the user
  owns.

## Consequences

**Good**
- The same spec and options give a byte-identical archive on any machine, so the archive
  SHA-256 is a fingerprint and the web download equals the CLI output
  ([ADR-0005](0005-generator-as-a-shared-library.md)).
- The CLI needs no account, key or network; the service needs no outbound access.
- Every claim is testable: the corpus suite installs and checks every bundled spec's
  project, and the hostile-spec tests are meaningful because the output is fixed.

**Bad / caveats**
- Handlers other than CRUD start as mocks: the business logic is still the user's work.
- Spec constructs the templates cannot express are reported, not attempted.

## Alternatives considered

- **AI-written handlers in 0.1.0.** Most impressive in a demo, least trustworthy in a
  repository; nondeterministic output defeats regeneration, review and the archive hash.
- **AI-assisted generation of the whole project.** Same problems, plus no guarantee that
  the routes match the spec, which is the product's core promise.
