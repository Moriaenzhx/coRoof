#!/usr/bin/env sh
# Native fallback: requires an existing dedicated PostgreSQL database and redis-server.
set -eu
cd "$(dirname "$0")/.."
COROOF_ROOT=$(pwd)
COROOF_UV=${COROOF_UV:-uv}
COROOF_REDIS_BIN=${COROOF_REDIS_BIN-redis-server}
: "${COROOF_DATABASE_URL:?Set COROOF_DATABASE_URL to an existing dedicated development database}"
export COROOF_REDIS_URL=${COROOF_REDIS_URL:-redis://127.0.0.1:56379/0}
export COROOF_WEB_ORIGIN=${COROOF_WEB_ORIGIN:-http://localhost:3000}
export COROOF_ENVIRONMENT=development
export NEXT_TELEMETRY_DISABLED=1
mkdir -p .local
npm ci
"$COROOF_UV" sync --project backend --frozen
(cd backend && "$COROOF_UV" run alembic upgrade head)
COROOF_CHILDREN=""
cleanup() {
  trap - INT TERM EXIT
  for COROOF_PID in $COROOF_CHILDREN; do kill -TERM "$COROOF_PID" 2>/dev/null || true; done
  wait || true
}
trap cleanup INT TERM EXIT
# Set COROOF_REDIS_BIN='' only when an already-running Redis is configured explicitly.
if [ -n "$COROOF_REDIS_BIN" ]; then
  "$COROOF_REDIS_BIN" --bind 127.0.0.1 --port 56379 --save '' --appendonly no > .local/redis.log 2>&1 &
  COROOF_CHILDREN="$COROOF_CHILDREN $!"
fi
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --no-access-log > ../.local/api.log 2>&1 &
COROOF_CHILDREN="$COROOF_CHILDREN $!"
.venv/bin/celery -A worker.app:celery worker --pool=solo --loglevel=WARNING > ../.local/worker.log 2>&1 &
COROOF_CHILDREN="$COROOF_CHILDREN $!"
.venv/bin/celery -A worker.app:celery beat --loglevel=WARNING --schedule=../.local/coroof-beat > ../.local/scheduler.log 2>&1 &
COROOF_CHILDREN="$COROOF_CHILDREN $!"
cd "$COROOF_ROOT/apps/web"
node ../../node_modules/next/dist/bin/next dev --hostname 127.0.0.1 > ../../.local/web.log 2>&1 &
COROOF_CHILDREN="$COROOF_CHILDREN $!"
printf '\ncoRoof: http://localhost:3000\nLogs: .local/{api,worker,scheduler,web,redis}.log\nCtrl+C stops only these child processes.\n'
wait
