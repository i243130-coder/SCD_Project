#!/usr/bin/env bash
# Waits for the eval Job, prints its result, and fails on regression (the harness exits 1).
set -euo pipefail
NS=idea-validator
if ! kubectl -n "$NS" wait --for=condition=complete job/eval-job --timeout=1800s; then
  kubectl -n "$NS" logs job/eval-job || true
  exit 1
fi
kubectl -n "$NS" logs job/eval-job | tail -5
