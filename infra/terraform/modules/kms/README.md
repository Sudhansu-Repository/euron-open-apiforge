# `kms` module

One customer-managed KMS key (annual rotation) plus alias. It encrypts data at rest: the artifacts bucket (SSE-KMS), RDS, ElastiCache, ECR, Secrets Manager and CloudWatch logs. The application never calls KMS itself (nothing is sealed in the app); every use goes through an AWS service, so task roles are granted the key only with a `kms:ViaService` condition (S3 for the task roles, Secrets Manager for the execution roles).

Applied in `local-floci` as `alias/apiforge-local`, which encrypts the emulated artifacts bucket and secrets.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. The alias is `alias/<name_prefix>`. | `string` | required |
| `deletion_window_in_days` | Waiting period before a scheduled key deletion completes. | `number` | `30` |
| `admin_principal_arns` | IAM principals allowed to administer (not use) the key. Empty = account root only, which delegates to IAM policies. | `list(string)` | `[]` |

## Outputs

| Name | Description |
|---|---|
| `key_arn` | KMS key ARN. |
| `key_id` | KMS key id. |
| `alias_name` | Key alias (`alias/<name_prefix>`). |
