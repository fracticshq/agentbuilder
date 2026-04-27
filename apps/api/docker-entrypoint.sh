#!/bin/sh
set -eu

require_env() {
  var_name="$1"
  var_value="$(printenv "$var_name" || true)"

  if [ -z "$var_value" ]; then
    echo "ERROR: $var_name is required. Set it in the container environment, Azure app settings, Key Vault, or local .env.docker before starting." >&2
    exit 1
  fi

  if [ "$var_value" = "change-me-to-a-random-32-char-string" ]; then
    echo "ERROR: $var_name is still set to the example placeholder. Generate a real value before starting docker compose." >&2
    exit 1
  fi
}

require_env SECRET_KEY

if [ "${ENVIRONMENT:-development}" = "production" ]; then
  require_env ADMIN_API_KEY
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
