#!/bin/sh
# Write the runtime API address (never baked at build time). The html dir is read-only; config.js lives in
# an emptyDir mounted at /usr/share/nginx/html/runtime and nginx serves /config.js from there.
set -eu
mkdir -p /usr/share/nginx/html/runtime
printf 'window.__CONFIG__ = { API_BASE_URL: "%s" };\n' "${API_BASE_URL:-/api}" > /usr/share/nginx/html/runtime/config.js
exec nginx -g 'daemon off;'
