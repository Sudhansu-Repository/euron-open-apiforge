# Run locally against real AWS

`make up` runs everything against the Floci emulator. To check the S3 code path against a
real bucket without deploying the containers, run the local stack with the
`compose.aws.yaml` overlay. Postgres, Redis and the web app stay local containers; the
api, worker and migrate containers store uploaded specs and generated archives in your S3
bucket.

## 1. Create the resources

Apply `infra/terraform/envs/aws-dev` ([deploy-aws.md](deploy-aws.md)), or create your own
bucket. If you create it yourself, give it default SSE-KMS encryption: the app writes every
object with `ServerSideEncryption=aws:kms` and S3 uses the bucket's default key. Your
credentials need `s3:PutObject`, `s3:GetObject` and `s3:DeleteObject` under `specs/*` and
`archives/*` in the bucket, and `kms:GenerateDataKey` and `kms:Decrypt` on the bucket's
key (through S3).

## 2. Configure

```bash
cp deploy/compose/.env.aws.example deploy/compose/.env.aws
```

Fill it in from `terraform output` in `infra/terraform/envs/aws-dev`:

| Variable | Value |
| -------- | ----- |
| `AWS_REGION` | The region of the bucket |
| `AWS_PROFILE` | Optional: the profile to use (default `default`) |
| `ARTIFACTS_BUCKET` | `artifacts_bucket` output |

`.env.aws` is git-ignored. It never holds credentials: the overlay mounts `~/.aws`
read-only into the containers and uses your profile through the standard AWS chain.

## 3. Start

```bash
make up-aws
```

This is `compose.yaml` plus `compose.aws.yaml`. The overlay sets, for migrate, api and
worker: `APIFORGE_CLOUD=aws`, `STORAGE=s3`, the profile variables, and the values from
`.env.aws`. `AWS_ENDPOINT_URL` is not set, so the SDK talks to real AWS. There is no Floci
and no Terraform container in this mode. The stack still runs with
`ENVIRONMENT=development`.

`make admin` and `make demo` address the Floci overlay, so in this mode run the CLI
through the AWS overlay directly:

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.aws.yaml exec api apiforge-server seed-demo
```

Then upload a spec and generate from the web app at http://localhost:4610: the spec lands
under `specs/` and the archive under `archives/` in your bucket.

## Notes

- **Costs:** S3 storage and requests and KMS requests are billed to your account. The
  bucket's lifecycle rule expires archives after `archive_expiration_days`.
- **Credentials:** the containers run as UID 10001 and read `~/.aws/config` and
  `~/.aws/credentials` through the read-only mount, so those files must be readable by
  that user. A profile with static or role-based credentials in those files is the
  simplest setup.
- **Stopping:** `make down` stops this stack too. It deletes the local volumes, not your
  bucket or what is in it.
