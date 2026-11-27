#!/usr/bin/env bash
set -euo pipefail
TAG="${1:?usage: push_images.sh TAG}"
REGISTRY="${REGISTRY:-localhost:5001}"
for m in gateway ui profile orchestrator scouts tools kb analyst ideation validators scorer verdict critic agentops ingestion evaluation; do
  docker push "$REGISTRY/$m:$TAG"
done
