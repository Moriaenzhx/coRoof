#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose -f infra/compose.yaml up --build -d --wait
printf '\ncoRoof: http://localhost:3000\nAPI: http://localhost:8000/docs\nDevelopment only: mock identity / rules fallback.\n'
