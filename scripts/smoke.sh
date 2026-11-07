#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
curl --fail --silent http://localhost:8000/healthz
curl --fail --silent http://localhost:8000/readyz
curl --fail --silent http://localhost:3000/api/v1/runtime
docker compose -f infra/compose.yaml exec -T worker uv run --no-sync python -c 'from worker.app import ping; assert ping.delay().get(timeout=10) == "pong"; print("Worker: pong")'
