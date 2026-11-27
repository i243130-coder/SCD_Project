#!/usr/bin/env bash
# R-G18: a non-M5 pod must NOT reach the internet; M5 (tools) must. Screenshot this output.
set -u
NS=idea-validator
echo "--- verdict -> https://api.github.com (must FAIL)"
if kubectl -n "$NS" exec deploy/verdict -- python -c "import urllib.request;urllib.request.urlopen('https://api.github.com',timeout=5)" 2>/dev/null; then
  echo "FAIL: verdict reached the internet"
  exit 1
fi
echo "OK: blocked"
echo "--- tools -> https://api.github.com (must print 200)"
if ! kubectl -n "$NS" exec deploy/tools -- python -c "import urllib.request;print(urllib.request.urlopen('https://api.github.com',timeout=5).status)"; then
  echo "FAIL: tools could not reach the internet"
  exit 1
fi
echo "NetworkPolicy test passed both ways"
