#!/usr/bin/env bash
# Each service has its own `src` package, so pytest runs once per module (no import clashes).
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
export TRACE_STDOUT=0
fail=0
for d in services/verdict services/gateway services/profile services/orchestrator services/scouts services/tools \
         services/kb services/analyst services/ideation services/validators services/scorer services/critic \
         services/agentops jobs/ingestion jobs/finetune eval/retrieval eval/behaviour; do
  if [ -d "$d" ]; then
    echo "== $d"
    "$PY" -m pytest "$d" -q -p no:cacheprovider || fail=1
  fi
done
exit "$fail"
