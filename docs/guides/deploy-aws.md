# Deploy to AWS

The Terraform in `infra/terraform` describes a complete production deployment. The
maintainers develop and test against the local emulator only: nothing in this project has
been applied to a real AWS account. The AWS environments are kept valid
(`make tf-validate tf-lint tf-security`) on every change, and the whole `aws-dev`
environment is planned, applied, re-planned and destroyed against Floci
(`make tf-aws-on-floci`, see [testing.md](testing.md#infrastructure)). This guide describes
how you would apply it in your own account. Review the plan before you apply it. The
module overview, the topology diagram and the security posture are in
[infra/README.md](../../infra/README.md).

- [Environments](#environments)
- [What gets created](#what-gets-created)
- [Prerequisites](#prerequisites)
- [Variables](#variables)
- [One-command deploy](#one-command-deploy)
- [Step by step](#step-by-step)
- [First owner](#first-owner)
- [CI access with an API key](#ci-access-with-an-api-key)
- [Prometheus and the metrics token](#prometheus-and-the-metrics-token)
- [Upgrades](#upgrades)
- [Tearing down](#tearing-down)

## Environments

| Environment | What it is |
| ----------- | ---------- |
| `envs/local-floci` | The artifacts bucket, the KMS key and the secrets on the Floci emulator. Applied automatically by `make up` |
| `envs/aws-dev` | The full stack, cost-lean: two availability zones, a single NAT gateway, single-AZ RDS with 3-day backups, one cache node, api 1 to 2 tasks, web 1 to 2, one worker, no deletion protection, 14-day log retention |
| `envs/aws-prod` | The full stack, resilient: three availability zones with a NAT gateway each, VPC interface endpoints, Multi-AZ RDS with 14-day backups, a primary and replica cache with failover, api 2 to 8 tasks (1 vCPU, 2 GB), web 2 to 4, one worker, deletion protection, a 30-day KMS deletion window and 365-day log retention |

## What gets created

| Module | Resources |
| ------ | --------- |
| `network` | VPC across two or three availability zones, public and private subnets, NAT, flow logs, an S3 gateway endpoint (interface endpoints in prod) |
| `kms` | Customer-managed key with rotation (RDS, ElastiCache, S3, ECR, secrets, logs) |
| `storage` | One private, versioned, TLS-only artifacts bucket with SSE-KMS: `specs/` kept, `archives/` expiring after `archive_expiration_days` (90), noncurrent versions after 30 days |
| `secrets` | `SESSION_SECRET` and `API_KEY_PEPPER` (generated once, distinct), `METRICS_TOKEN`, and the database and cache URLs in Secrets Manager, injected by ECS |
| `database` | RDS PostgreSQL 16 (encrypted, private, automated backups, `rds.force_ssl`) |
| `cache` | ElastiCache Valkey with TLS and an AUTH token |
| `ecr` | Repositories for the api and web images |
| `service` | ECS Fargate cluster; api, worker and web services behind one ALB with WAF; a task definition for one-off commands (migrate, create-owner) |
| `observability` | CloudWatch log groups, a dashboard and alarms to an SNS topic ([operations.md](operations.md#alarms)) |

The ALB sends `/api/*`, `/healthz`, `/readyz`, `/docs` and `/openapi.json` to the api,
`/metrics` to the api (optionally only from `metrics_allowed_cidrs`), and everything else
to the web app, which proxies `/api` back through the ALB.

The api, worker and migrate tasks run with `ENVIRONMENT=production`,
`APIFORGE_CLOUD=aws`, `STORAGE=s3`, `ARTIFACTS_BUCKET` from the storage module,
`COOKIE_SECURE=true`, `CORS_ORIGINS` set to the deployment URL, `FORWARDED_ALLOW_IPS` set
to the VPC CIDR, `WEB_CONCURRENCY=1`, `DB_POOL_SIZE=5` and `DB_MAX_OVERFLOW=10`. Add other
non-secret settings from [configuration.md](configuration.md) through
`api_extra_environment` (for example `GENERATION_TIMEOUT_S`, `WORKER_CONCURRENCY`,
`DEFAULT_RPM_LIMIT`).

## Prerequisites

- An AWS account and credentials for it in your shell (profile or SSO).
- Terraform 1.16, Docker with buildx, the AWS CLI and Python 3.
- An ACM certificate in the target region for the host name you will use.
- Optionally a Route53 hosted zone for that name (otherwise you create the DNS record
  yourself).

## Variables

Copy `infra/terraform/envs/aws-dev/terraform.tfvars.example` to `terraform.tfvars`
(git-ignored) and fill it in:

| Variable | Required | Meaning |
| -------- | -------- | ------- |
| `region` | yes | AWS region |
| `name_prefix` | yes | Prefix for every resource; the bucket name derives from it, so make it globally unique (`acme-apiforge-dev`) |
| `hostname` | yes | The public host name (`apiforge-dev.example.com`) |
| `certificate_arn` | yes | ACM certificate for `hostname`, same region |
| `route53_zone_id` | no | Creates the DNS record; otherwise point a CNAME at `load_balancer_dns_name` |
| `image_tag` | yes | The tag you push to the ECR repositories |
| `alarm_email` | no | Subscribes an address to the alarm topic |
| `metrics_allowed_cidrs` | no | Addresses allowed to scrape `/metrics` through the ALB (they still need `METRICS_TOKEN`) |
| `worker_metrics_cidrs` | no | In-VPC Prometheus addresses allowed to scrape the worker on 9464 |
| `archive_expiration_days` | no (90) | Days before a generated archive expires from S3 |
| `api_extra_environment` | no | Extra non-secret settings for api, worker and migrate |
| `api_p95_latency_seconds` | no (1.5) | p95 response time that raises an alarm |
| `db_instance_class`, `cache_node_type` | no | Sizes |
| `environment`, `extra_tags` | no | Tagging |

Optionally copy `backend.tf.example` to `backend.tf` for remote state in S3.

## One-command deploy

```bash
make aws-deploy ENV=aws-dev TAG=0.1.0
```

[`scripts/aws-deploy.sh`](../../scripts/aws-deploy.sh) runs, in order:

1. `terraform apply -target=module.ecr` (the registries and the key that encrypts them);
2. builds the api image from the repository root (it installs `apps/forge` and
   `apps/api` together) and the web image from `apps/web`, for `linux/arm64` (override with
   `PLATFORM`), and pushes both with your tag;
3. `terraform apply` of everything else with that tag;
4. the database migrations as a one-off ECS task (`make aws-migrate`);
5. waits for the api, worker and web services to become stable, then prints the URL.

## Step by step

```bash
cd infra/terraform/envs/aws-dev
terraform init
terraform apply -target=module.ecr
# build and push both images with your image_tag (repositories from `terraform output ecr_repositories`)
docker buildx build --platform linux/arm64 -f infra/docker/api.Dockerfile -t <api repo>:<tag> --push .   # from the repo root
docker buildx build --platform linux/arm64 -f infra/docker/web.Dockerfile -t <web repo>:<tag> --push apps/web
terraform apply
```

Then run the migrations with `make aws-migrate ENV=aws-dev`
([`scripts/aws-run-task.sh`](../../scripts/aws-run-task.sh) starts the `run_task` task
definition with the command override `migrate`, waits for it and prints its logs), and
point DNS at `load_balancer_dns_name` if the zone is not in Route53.

Useful outputs: `url`, `load_balancer_dns_name`, `cluster_name`, `services`,
`ecr_repositories`, `run_task`, `artifacts_bucket`, `metrics_token_secret_arn`,
`kms_key_alias`, `dashboard_name`.

## First owner

```bash
APIFORGE_OWNER_PASSWORD='a long password with Upper, lower and 1 digit' \
  make aws-admin ENV=aws-dev EMAIL=you@example.com
```

This runs `apiforge-server create-owner --email you@example.com` as a one-off task, with
the password passed as an environment override (never on the command line of the
container). Sign in at the `url` output, then invite the team from Users (owner only). Do
not run `seed-demo` on a real deployment: it creates well-known demo logins, and it
refuses to run with `ENVIRONMENT=production` (which the AWS tasks set).

## CI access with an API key

Create a key in the web app (API keys, admins only) with an expiry and a rate limit that
fits your CI, store it in your CI's secret store, and use it against
`https://<hostname>/api/v1/...`. Keys are read-only: a pipeline can list generations and
download archives, never upload or generate.
[examples/download_latest.py](../../examples/download_latest.py) downloads the latest
succeeded archive and checks its SHA-256.

## Prometheus and the metrics token

Read the token from the secret named by the `metrics_token_secret_arn` output and scrape
`https://<hostname>/metrics` with `Authorization: Bearer <token>`. Restrict the source
addresses with `metrics_allowed_cidrs` if your scraper has a stable egress address. The
worker's own metrics (generation counts, durations, the queue) are on port 9464 of the
worker task and reachable only from `worker_metrics_cidrs` inside the VPC.

## Upgrades

1. Read the [CHANGELOG](../../CHANGELOG.md) for migration notes.
2. `make aws-deploy ENV=aws-dev TAG=<new tag>`: new images, `terraform apply`, migrations,
   then a rolling replacement of the services. Migrations are additive, so the old tasks
   keep working while the new ones start.
3. A new generator version can change the bytes of new archives (the lock file in each
   archive records the version). Existing archives are untouched.

## Tearing down

`aws-prod` has deletion protection on the database and the load balancer; turn it off in
`main.tf` first. Then:

```bash
terraform -chdir=infra/terraform/envs/aws-dev destroy
```

In `aws-dev` the artifacts bucket is force-destroyed (with every spec and archive in it)
and RDS skips its final snapshot. In `aws-prod` the bucket is not force-destroyed (empty
it, all versions, or keep it) and RDS takes a final snapshot (`<name_prefix>-db-final`).
The KMS key enters its deletion window (7 days in dev, 30 in prod).
