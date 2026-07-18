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
  require_env SETTINGS_ENCRYPTION_KEY
  require_env PII_ENCRYPTION_KEY
  require_env MONGODB_URI
  require_env REDIS_URL
  require_env MCP_SERVICE_AUTH_TOKEN
  require_env STRAPI_API_TOKEN

  case "${STRAPI_URL:-}" in
    ""|*localhost*|*127.0.0.1*)
      echo "ERROR: STRAPI_URL must point at the deployed Strapi service in production." >&2
      exit 1
      ;;
  esac
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
