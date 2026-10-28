# ADR-0009: Local AWS emulator (Floci), provisioned by the same Terraform as production

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

On AWS, APIForge stores specs and archives in S3 with SSE-KMS and reads its secrets from
Secrets Manager. Code paths that only run in the cloud are code paths that are not tested.
The project is developed and verified locally, with no AWS account, and the Terraform for
`aws-dev` and `aws-prod` must still be correct enough that someone could apply it.

## Decision

- `make up` runs **Floci** (`floci/floci:2.3.0`, MIT) in Docker Compose as the AWS
  endpoint for S3, KMS and Secrets Manager.
- A one-shot `terraform` container applies `infra/terraform/envs/local-floci` against
  Floci before `migrate`, `api` and `worker` start. That environment uses the same
  `storage`, `kms` and `secrets` modules as `aws-dev` and `aws-prod`, turning off only what
  an HTTP-only emulator cannot do (the TLS-only bucket policy).
- The application selects backends through environment variables only
  (`AWS_ENDPOINT_URL`, `S3_FORCE_PATH_STYLE`, `STORAGE`, `ARTIFACTS_BUCKET`). There is no
  emulator branch in the code.
- Services Floci does not back (RDS, ElastiCache) run as plain `postgres:16` and `redis:7`
  containers locally and are covered by the AWS environments.
- `make tf-aws-on-floci` plans, applies, re-plans (no additions or replacements) and
  destroys the full `aws-dev` environment against a throwaway Floci, which catches errors
  `terraform validate` cannot see.

## Consequences

**Good**
- The S3 storage backend is exercised on every `make up` and in `make test-matrix`.
- The same modules that would provision production are applied on every local start.
- No AWS account, no credentials and no cost to develop or test.

**Bad / caveats**
- An emulator is not AWS: IAM policies, KMS key policies and some S3 behaviours are not
  enforced the same way. The AWS environments are validated, linted and policy-scanned
  (`tf-validate`, `tf-lint`, `tf-security`), but nothing is applied to a real account by
  this project.
- One more container to start locally.

## Alternatives considered

- **LocalStack.** The common choice; Floci is MIT licensed, lighter, and covers the
  services APIForge uses.
- **Local disk only.** Simpler, but the S3 code path would only ever run in production.
