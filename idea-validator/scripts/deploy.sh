#!/usr/bin/env bash
# Pin every image to TAG in the test overlay, apply, and wait. A failed rollout fails the pipeline.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:?usage: deploy.sh TAG}"
REGISTRY="${REGISTRY:-localhost:5001}"
pushd k8s/overlays/test >/dev/null
for m in gateway ui profile orchestrator scouts tools kb analyst ideation validators scorer verdict critic agentops ingestion evaluation; do
  kustomize edit set image "registry/$m=$REGISTRY/$m:$TAG"
done
popd >/dev/null
kubectl apply -k k8s/overlays/test
for d in gateway ui profile orchestrator tools kb analyst ideation validators scorer verdict critic agentops; do
  kubectl -n idea-validator rollout status "deploy/$d" --timeout=180s
done
