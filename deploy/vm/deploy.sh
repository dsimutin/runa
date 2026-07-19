#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing ${ROOT_DIR}/.env. Copy .env.example and fill BOT_TOKEN and DATABASE_URL." >&2
  exit 1
fi

if ! grep -Eq '^BOT_TOKEN=.+$' .env; then
  echo "BOT_TOKEN is empty in .env" >&2
  exit 1
fi

if ! grep -Eq '^DATABASE_URL=.+$' .env; then
  echo "DATABASE_URL is empty in .env" >&2
  exit 1
fi

docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
