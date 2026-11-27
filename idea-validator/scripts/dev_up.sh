#!/usr/bin/env bash
# Local dev: build + start everything (migrations run in the profile container), then load the card snapshot.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then echo "copy .env.example to .env and fill the secrets first"; exit 1; fi
docker compose up -d --build
docker compose --profile jobs run --rm ingestion python -m src.ingest --from-snapshot --snapshot /data/snapshot/cards.jsonl.gz || true
docker compose restart kb analyst
echo "gateway: http://localhost:8000   ui: http://localhost:8080"
