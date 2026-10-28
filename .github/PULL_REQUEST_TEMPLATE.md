## What and why

<!-- One paragraph: the problem, and how this change solves it. Link the issue. -->

## How it was verified

- [ ] `make lint typecheck test` (generator, API and web)
- [ ] `make test-integration` (if the API, worker, cache or database code changed)
- [ ] `make test-matrix` (if a backend changed: cache or storage)
- [ ] `make e2e` and `make qa` (if a dashboard flow, the UI or infrastructure changed)
- [ ] `make tf-validate tf-lint tf-security tf-aws-on-floci` (if Terraform changed)
- [ ] `make test-corpus` (if the generator or its templates changed)

## Checklist

- [ ] Docs updated (README, `docs/`, configuration reference) for any behavior or config change
- [ ] New Alembic revision instead of editing an applied one
- [ ] Generated output is still deterministic (same spec, same bytes) and keeps user code on regeneration
- [ ] Spec input is still treated as untrusted (validated at upload, size-limited, never interpolated unescaped into generated code)
- [ ] Caching table in `docs/architecture/HLD.md` updated if a cache was added or changed
- [ ] `make openapi` run if the API changed
- [ ] No secrets, account ids, real hostnames or em/en dashes (`make sanitize` is clean)
- [ ] Security-relevant change? Described the threat and mitigation above
