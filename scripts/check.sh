#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../backend"
uv sync --frozen
uv run ruff check app worker tests migrations ../scripts
uv run ruff format --check app worker tests migrations ../scripts
uv run mypy app worker
uv run pytest -q
uv run python ../scripts/export_openapi.py
cd ..
npm ci
npm run api:generate
npm run format:check
npm run typecheck
npm test
npm run build
go vet ./...
go test -race ./...
mkdir -p .local
go build -o .local/coroof ./cmd/coroof
