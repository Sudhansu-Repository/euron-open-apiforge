#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-shot deployment to AWS:  scripts/aws-deploy.sh <aws-dev|aws-prod> <image-tag>
#
#   1. terraform apply the image registries (and the KMS key that encrypts them)
#   2. build the api and web images for the cluster's CPU architecture and push them
#   3. terraform apply everything else, the services still on the tag they run now and
#      only the migrate task on the new one
#   4. run the database migrations as a one-off ECS task, before any new code serves
#   5. terraform apply again with the new tag everywhere: the services roll onto it
#   6. wait for the api, worker and web services to become stable
#
# Migrations go first so new code never runs against an old schema; a failed migration
# stops the deploy with the previous release still serving. Migrations must therefore
# stay backward compatible with the release before them (add, then remove a release
# later). On the very first deploy there is no previous release: the services start with
# the new tag and become usable once step 4 has created the schema.
#
# Needs: terraform, docker (buildx), the AWS CLI, credentials for the target account,
# and infra/terraform/envs/<env>/terraform.tfvars (copy the .example next to it).
# This repository never runs it against a real account itself; it is here so you can.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
ENV="${1:?usage: aws-deploy.sh <aws-dev|aws-prod> <image-tag>}"
TAG="${2:?usage: aws-deploy.sh <aws-dev|aws-prod> <image-tag>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/infra/terraform/envs/$ENV"
PLATFORM="${PLATFORM:-linux/arm64}"   # matches the service module's default cpu_architecture

for bin in terraform docker aws python3; do command -v "$bin" >/dev/null || { echo "missing: $bin"; exit 1; }; done
[[ -f "$DIR/terraform.tfvars" ]] || { echo "create $DIR/terraform.tfvars from terraform.tfvars.example first"; exit 1; }
[[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]] && echo "note: the working tree has uncommitted changes; the images are built from it as-is"

tf() { terraform -chdir="$DIR" "$@"; }
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

echo "==> terraform init"
tf init -input=false >/dev/null

# The tag the services run now, read before any apply touches the outputs (empty on the
# first deploy, and on stacks created before this output existed).
current=$(tf output -raw image_tag 2>/dev/null || true)
current="${current:-$TAG}"

echo "==> 1/6 registries"
tf apply -input=false -auto-approve -var "image_tag=$TAG" -target=module.ecr

region="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
region="${region:-$(grep -E '^region' "$DIR/terraform.tfvars" | sed -E 's/.*"(.*)".*/\1/')}"
repos=$(tf output -json ecr_repositories)
api_repo=$(echo "$repos" | json "['api']")
web_repo=$(echo "$repos" | json "['web']")
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "${api_repo%%/*}" >/dev/null

echo "==> 2/6 images ($TAG, $PLATFORM)"
# The api image builds from the repository root: it installs apps/forge and apps/api.
docker buildx build --platform "$PLATFORM" -f "$ROOT/infra/docker/api.Dockerfile" -t "$api_repo:$TAG" --push "$ROOT"
docker buildx build --platform "$PLATFORM" -f "$ROOT/infra/docker/web.Dockerfile" -t "$web_repo:$TAG" --push "$ROOT/apps/web"

echo "==> 3/6 infrastructure (services stay on $current, migrate on $TAG)"
tf apply -input=false -auto-approve -var "image_tag=$current" -var "migrate_image_tag=$TAG"

echo "==> 4/6 migrations"
"$ROOT/scripts/aws-run-task.sh" "$ENV" migrate

echo "==> 5/6 services onto $TAG"
tf apply -input=false -auto-approve -var "image_tag=$TAG"

echo "==> 6/6 waiting for the services"
cluster=$(tf output -raw cluster_name)
services=$(tf output -json services | python3 -c "import json,sys; print(' '.join(json.load(sys.stdin).values()))")
# shellcheck disable=SC2086 # one argument per service name
aws ecs wait services-stable --region "$region" --cluster "$cluster" --services $services

echo
echo "Deployed $TAG to $ENV: $(tf output -raw url)"
cat <<NEXT
Next, the first owner account:
  APIFORGE_OWNER_PASSWORD='...' make aws-admin ENV=$ENV EMAIL=you@example.com
NEXT
