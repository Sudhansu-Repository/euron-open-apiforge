# `storage` module

One private S3 bucket, `<name_prefix>-artifacts` (`ARTIFACTS_BUCKET`), for everything APIForge keeps outside Postgres. Database rows keep only the object key.

| Prefix | Contents | Kept |
|---|---|---|
| `specs/` | Uploaded OpenAPI documents, the input of every regeneration | until deleted |
| `archives/` | Generated FastAPI project archives (zip); a new generation of the same spec version rebuilds the same bytes | `archive_expiration_days` (90) |

- Public access blocked, bucket-owner-enforced ownership, TLS-only bucket policy (`aws:SecureTransport`).
- Default encryption SSE-KMS with the CMK (bucket key on), SSE-S3 when no key is given.
- Versioning on, so an overwritten or deleted spec can be recovered; noncurrent versions expire after `noncurrent_version_expiration_days` (30).
- Lifecycle: objects under `archives/` expire after `archive_expiration_days`; `specs/` has no expiration; incomplete multipart uploads abort after a day.
- Optional CORS (`cors_origins`), only for JavaScript fetches from the dashboard; downloads go through the API, so none is needed by default.

Applied in `local-floci` as `apiforge-local-artifacts` (the `ARTIFACTS_BUCKET` in `deploy/compose/compose.floci.yaml`) with `enforce_tls = false` (the emulator speaks plain HTTP) and `force_destroy = true`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. The bucket is `<name_prefix>-artifacts`. | `string` | required |
| `kms_key_arn` | CMK for SSE-KMS. Null falls back to SSE-S3. | `string` | `null` |
| `enforce_tls` | Deny any request not made over TLS. | `bool` | `true` |
| `archive_expiration_days` | Days a generated archive under `archives/` is kept. | `number` | `90` |
| `noncurrent_version_expiration_days` | Days an overwritten or deleted object version is kept. | `number` | `30` |
| `cors_origins` | Browser origins allowed to GET objects with JavaScript. Empty = no CORS. | `list(string)` | `[]` |
| `force_destroy` | Allow destroying a non-empty bucket. Never in production. | `bool` | `false` |

## Outputs

| Name | Description |
|---|---|
| `bucket_name` | Artifacts bucket name (`ARTIFACTS_BUCKET`). |
| `bucket_arn` | Artifacts bucket ARN, for IAM policies. |
