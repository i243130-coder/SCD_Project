#!/usr/bin/env bash
# Build every module image tagged with the commit SHA (never only `latest`).
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:-$(git rev-parse --short HEAD)}"
REGISTRY="${REGISTRY:-localhost:5001}"
MODULES="gateway ui profile orchestrator scouts tools kb analyst ideation validators scorer verdict critic agentops ingestion evaluation"
for m in $MODULES; do
  dir="services/$m"
  if [ ! -d "$dir" ]; then dir="jobs/$m"; fi
  echo "==> $m"
  docker build -f "$dir/Dockerfile" -t "$REGISTRY/$m:$TAG" .
done
