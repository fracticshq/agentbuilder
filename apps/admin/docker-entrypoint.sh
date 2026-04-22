#!/bin/sh
set -eu

cat >/usr/share/nginx/html/runtime-config.js <<EOF
window.__APP_CONFIG__ = {
  API_BASE_URL: "${API_BASE_URL:-http://localhost:8000}"
};
EOF
