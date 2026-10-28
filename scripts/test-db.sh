#!/usr/bin/env bash
# Make sure Postgres and Redis are reachable for the integration suite and that the
# apiforge_test database exists (the suite refuses any database not named *_test).
# Reuses the Compose services when the stack is up; otherwise starts just those two.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG_PORT="${AF_PG_PORT:-4642}"
REDIS_PORT="${AF_REDIS_PORT:-4679}"
TEST_DB="${AF_TEST_DB:-apiforge_test}"

ready() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

"$ROOT/scripts/gen-local-env.sh" >/dev/null
compose() {
  docker compose --env-file "$ROOT/deploy/compose/.env" -f "$ROOT/deploy/compose/compose.yaml" "$@"
}

if ! (ready "$PG_PORT" && ready "$REDIS_PORT"); then
  compose up -d --wait postgres redis
fi

exists="$(compose exec -T postgres psql -U apiforge -d apiforge -tAc \
  "SELECT 1 FROM pg_database WHERE datname = '$TEST_DB'")"
if [[ "$exists" != "1" ]]; then
  compose exec -T postgres psql -U apiforge -d apiforge -qc "CREATE DATABASE $TEST_DB"
  echo "created database $TEST_DB"
fi
