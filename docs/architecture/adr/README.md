# Architecture Decision Records

Each ADR captures one significant decision: the context that forced it, what we chose,
and what it costs us. ADRs are immutable once accepted. To revisit one, write a new ADR
that supersedes it.

| ADR | Decision | Status |
| --- | -------- | ------ |
| [0001](0001-deterministic-generation-first.md) | Deterministic generation first; AI-assisted handler bodies on the roadmap | Accepted |
| [0002](0002-generation-gap-with-a-lock-file.md) | The generation gap with a lock file, instead of merge markers | Accepted |
| [0003](0003-fastapi-only-target.md) | FastAPI as the only target in 0.1.0 | Accepted |
| [0004](0004-fidelity-by-openapi-round-trip.md) | Fidelity checked by comparing the served OpenAPI document with the spec | Accepted |
| [0005](0005-generator-as-a-shared-library.md) | The generator as a library shared by the CLI and the service (byte-identical archives) | Accepted |
| [0006](0006-lease-based-worker-on-postgres.md) | A lease-based worker on Postgres instead of a queue service | Accepted |
| [0007](0007-postgres-and-object-storage-redis-optional.md) | Postgres plus object storage; Redis optional with an in-process fallback | Accepted |
| [0008](0008-never-fetch-url-refs.md) | Never fetching URL `$ref`s, on the CLI or the server | Accepted |
| [0009](0009-local-aws-emulation.md) | Local AWS emulator (Floci), provisioned by the same Terraform as production | Accepted |
| [0010](0010-python-fastapi-and-nextjs.md) | Python and FastAPI for the generator, API and worker; Next.js for the web app | Accepted |

**Template:** Status / Date, then Context, Decision, Consequences (good and bad), and
Alternatives considered.
