#!/usr/bin/env bash
# On pipeline failure: undo every deployment whose latest rollout is not healthy.
set -uo pipefail
NS=idea-validator
for d in $(kubectl -n "$NS" get deploy -o name); do
  if ! kubectl -n "$NS" rollout status "$d" --timeout=20s >/dev/null 2>&1; then
    echo "rolling back $d"
    kubectl -n "$NS" rollout undo "$d"
  fi
done
