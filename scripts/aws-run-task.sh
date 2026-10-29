#!/usr/bin/env bash
# Run a one-off command on the API image as an ECS task, wait for it, print its logs.
#   scripts/aws-run-task.sh <aws-dev|aws-prod> migrate
#   APIFORGE_OWNER_PASSWORD=... scripts/aws-run-task.sh aws-dev create-owner --email you@example.com
# The command runs as arguments to the `apiforge-server` CLI (the image's entrypoint).
# APIFORGE_OWNER_PASSWORD never leaves this machine: it is hashed here (argon2id, with the
# app's own hasher through uv) and only the hash goes to the task, because ECS keeps task
# overrides readable to anyone allowed to describe the task.
set -euo pipefail
ENV="${1:?usage: aws-run-task.sh <env> <apiforge-server command...>}"; shift
DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform/envs/$ENV"
spec=$(terraform -chdir="$DIR" output -json run_task)
get() { echo "$spec" | python3 -c "import json,sys; v=json.load(sys.stdin)['$1']; print(','.join(v) if isinstance(v, list) else v)"; }
cluster=$(get cluster); taskdef=$(get task_definition); container=$(get container)
password_hash=""
if [[ -n "${APIFORGE_OWNER_PASSWORD:-}" ]]; then
  password_hash=$(cd "$(dirname "$0")/../apps/api" && uv run --quiet apiforge-server hash-password)
fi
overrides=$(PASSWORD_HASH="$password_hash" python3 - "$container" "$@" <<'PY'
import json, os, sys
container, *command = sys.argv[1:]
override = {"name": container, "command": command}
if os.environ.get("PASSWORD_HASH"):
    override["environment"] = [{"name": "APIFORGE_OWNER_PASSWORD_HASH",
                                "value": os.environ["PASSWORD_HASH"]}]
print(json.dumps({"containerOverrides": [override]}))
PY
)
network="awsvpcConfiguration={subnets=[$(get subnets)],securityGroups=[$(get security_groups)],assignPublicIp=DISABLED}"
arn=$(aws ecs run-task --cluster "$cluster" --task-definition "$taskdef" --launch-type FARGATE \
  --network-configuration "$network" --overrides "$overrides" \
  --query 'tasks[0].taskArn' --output text)
echo "started $arn"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$arn"
code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$arn" --query 'tasks[0].containers[0].exitCode' --output text)
group=$(aws ecs describe-task-definition --task-definition "$taskdef" \
  --query 'taskDefinition.containerDefinitions[0].logConfiguration.options."awslogs-group"' --output text)
aws logs tail "$group" --since 15m --format short | tail -40
echo "exit code: $code"
[[ "$code" == "0" ]]
