# Fidelity: the app serves its spec

Every generated project carries a test (`tests/generated/test_spec.py`) that starts the app,
reads the OpenAPI document FastAPI serves, and compares it with the spec it was generated
from (`app/generated/openapi.json`). The comparison is `apiforge/fidelity.py`, copied into the
project as `tests/generated/fidelity.py` so the project depends on nothing from APIForge.

## What is compared

Both documents are reduced to a canonical form per operation (`METHOD /path`):

- parameters: location, name, requiredness and schema;
- the request body: requiredness, media type family and schema;
- responses: status codes, media type family and schemas;
- security: the schemes and scopes that apply (operation level or global).

Schemas are compared after inlining `$ref`s, merging `allOf`, unifying 3.0 `nullable` with
3.1 `null` types, ordering union members, and marking recursion by component name.

## What is ignored, and why

| Ignored | Because |
| --- | --- |
| titles, descriptions, examples | they change no behaviour |
| the 422 response FastAPI adds | every FastAPI app documents validation errors; the spec need not |
| integer and number `format` hints (`int64`, `double`) | Python has one `int` and one `float` |
| `null` on optional properties and parameters | an optional field is generated as `T \| None = None`, which also accepts an explicit null |
| the `enum` of a discriminator property | variants narrow it to a `Literal`, which is stricter, not different |

## Accepted differences

When the lint report says APIForge approximated something (a `deepObject` parameter received
as a string, `uniqueItems` on objects), the generated `test_spec.py` lists that exact
difference in `ACCEPTED`, as an (operation, part) pair. Any other difference fails the test.

## Where it runs

- In every generated project's test suite, so its CI keeps checking it after you edit code.
- In `apps/forge/tests/test_corpus.py`, for every bundled spec with and without `--db`, the
  hostile spec and a 240-operation synthesized spec.
