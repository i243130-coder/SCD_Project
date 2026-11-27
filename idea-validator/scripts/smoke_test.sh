#!/usr/bin/env bash
# Smoke: every service ready, register + login through the gateway, a validate run on a fixture idea returns a verdict.
set -euo pipefail
NS=idea-validator
BASE="${GATEWAY_URL:-}"
if [ -z "$BASE" ]; then
  kubectl -n "$NS" port-forward svc/gateway 18000:8000 >/dev/null 2>&1 &
  PF=$!
  trap 'kill "$PF"' EXIT
  sleep 3
  BASE=http://localhost:18000
fi
for d in gateway profile orchestrator tools kb analyst ideation validators scorer verdict critic agentops; do
  kubectl -n "$NS" exec "deploy/$d" -- python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready',timeout=5).status==200 else 1)"
  echo "ready: $d"
done
EMAIL="smoke-$(date +%s)@smoke.invalid"
PW="smoke-$(openssl rand -hex 8)"
json() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }
TOKEN=$(curl -sf -X POST "$BASE/auth/register" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\"}" | json '["token"]')
curl -sf -X POST "$BASE/auth/login" -H 'content-type: application/json' -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\"}" >/dev/null
H="Authorization: Bearer $TOKEN"
curl -sf -X PUT "$BASE/profile" -H "$H" -H 'content-type: application/json' \
  -d '{"skills":["python","react"],"hours_per_week":10,"weeks_available":12,"team_size":2,"compute":"laptop","goal":"portfolio","interests":["web"]}' >/dev/null
RUN=$(curl -sf -X POST "$BASE/validate" -H "$H" -H 'content-type: application/json' \
  -d '{"idea_text":"RSVP tool for university societies, web only, one core feature"}' | json '["run_id"]')
for _ in $(seq 1 60); do
  STATE=$(curl -sf "$BASE/runs/$RUN" -H "$H" | json '.get("state")')
  case "$STATE" in
    DONE) echo "smoke ok: $RUN"; exit 0 ;;
    FAILED) echo "run failed"; exit 1 ;;
    WAITING_ANSWER) curl -sf -X POST "$BASE/runs/$RUN/answer" -H "$H" -H 'content-type: application/json' -d '{"question_id":"q_scope","skip":true}' >/dev/null ;;
    WAITING_APPROVAL) curl -sf -X POST "$BASE/runs/$RUN/approve" -H "$H" -H 'content-type: application/json' -d '{"approve":false}' >/dev/null ;;
  esac
  sleep 3
done
echo "timeout waiting for a verdict"
exit 1
