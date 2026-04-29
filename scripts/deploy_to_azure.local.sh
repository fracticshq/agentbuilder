#!/usr/bin/env bash
set -euo pipefail

# NOVA Azure Container Apps deployment helper.
# Secrets stay in .env.azure; the script validates before changing Azure resources.
#
# Usage:
#   ./scripts/deploy_to_azure.local.sh --service all
#   ./scripts/deploy_to_azure.local.sh --service api
#   ./scripts/deploy_to_azure.local.sh --service api --use-existing-image --tag 20260428-abc1234
#   ./scripts/deploy_to_azure.local.sh --service all --env-file .env.azure
#   ./scripts/deploy_to_azure.local.sh --service all --show-secrets
#   ./scripts/deploy_to_azure.local.sh --service all --use-existing-secrets
#
# Required shell/env values:
#   SUBSCRIPTION_ID RESOURCE_GROUP ACR_NAME ACA_ENV
# Optional app/resource values:
#   LOCATION API_APP ADMIN_APP WIDGET_APP SHOPIFY_APP STRAPI_APP STRAPI_ROOT

SERVICE="all"
USE_EXISTING_IMAGE=false
CREATE_MISSING=true
ENV_FILE=".env.azure"
TAG=""
SHOW_SECRETS=false
DRY_RUN=false
USE_EXISTING_SECRETS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE="${2:?Missing value for --service}"
      shift 2
      ;;
    --use-existing-image)
      USE_EXISTING_IMAGE=true
      shift
      ;;
    --tag)
      TAG="${2:?Missing value for --tag}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:?Missing value for --env-file}"
      shift 2
      ;;
    --no-create)
      CREATE_MISSING=false
      shift
      ;;
    --show-secrets)
      SHOW_SECRETS=true
      shift
      ;;
    --use-existing-secrets)
      USE_EXISTING_SECRETS=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      sed -n '1,35p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STRAPI_ROOT="${STRAPI_ROOT:-$(cd "$ROOT_DIR/../agentbuilder-strapi" 2>/dev/null && pwd || true)}"

cd "$ROOT_DIR"

if [[ -f "$ENV_FILE" ]]; then
  echo "Loading env file: $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "No $ENV_FILE found; using current shell environment."
fi

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

require_var SUBSCRIPTION_ID
require_var RESOURCE_GROUP
require_var ACR_NAME
require_var ACA_ENV

LOCATION="${LOCATION:-eastus}"
API_APP="${API_APP:-agentbuilder-api}"
ADMIN_APP="${ADMIN_APP:-agentbuilder-admin}"
WIDGET_APP="${WIDGET_APP:-agentbuilder-widget}"
SHOPIFY_APP="${SHOPIFY_APP:-agentbuilder-shopify}"
STRAPI_APP="${STRAPI_APP:-agentbuilder-strapi}"

if [[ -z "$TAG" ]]; then
  GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo local)"
  TAG="$(date +%Y%m%d%H%M%S)-$GIT_SHA"
fi
CONFIG_VERSION="${CONFIG_VERSION:-$TAG}"

VALIDATOR_ARGS=(--env-file "$ENV_FILE" --service "$SERVICE")
if [[ "$SHOW_SECRETS" == true ]]; then
  VALIDATOR_ARGS+=(--show-secrets)
fi
if [[ "$USE_EXISTING_SECRETS" == true ]]; then
  VALIDATOR_ARGS+=(--allow-missing-secrets)
fi
python3 "$SCRIPT_DIR/validate_azure_env.py" "${VALIDATOR_ARGS[@]}"

if [[ "$DRY_RUN" == true ]]; then
  echo ""
  echo "Dry run complete. Azure resources were not changed."
  exit 0
fi

az account set --subscription "$SUBSCRIPTION_ID"
ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)"
ACR_USERNAME="$(az acr credential show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query passwords[0].value -o tsv)"

secret_name_for() {
  echo "$1" | tr '[:upper:]_' '[:lower:]-'
}

set_secret_envs() {
  local app="$1"
  shift
  local secret_args=()
  local env_args=()

  for key in "$@"; do
    local value="${!key:-}"
    if [[ -z "$value" ]]; then
      continue
    fi
    local secret_name
    secret_name="$(secret_name_for "$key")"
    secret_args+=("$secret_name=$value")
    env_args+=("$key=secretref:$secret_name")
    if [[ "$SHOW_SECRETS" == true ]]; then
      echo "  $app secret $key=$value"
    fi
  done

  if [[ ${#secret_args[@]} -gt 0 ]]; then
    echo "Setting ${#secret_args[@]} secrets on $app"
    az containerapp secret set \
      --name "$app" \
      --resource-group "$RESOURCE_GROUP" \
      --secrets "${secret_args[@]}" >/dev/null
  fi

  if [[ ${#env_args[@]} -gt 0 ]]; then
    az containerapp update \
      --name "$app" \
      --resource-group "$RESOURCE_GROUP" \
      --set-env-vars "${env_args[@]}" >/dev/null
  fi
}

set_plain_envs() {
  local app="$1"
  shift
  local env_args=()

  for key in "$@"; do
    local value="${!key:-}"
    if [[ -z "$value" ]]; then
      continue
    fi
    env_args+=("$key=$value")
    if [[ "$SHOW_SECRETS" == true ]]; then
      echo "  $app env $key=$value"
    fi
  done

  if [[ ${#env_args[@]} -gt 0 ]]; then
    echo "Setting ${#env_args[@]} plain env vars on $app"
    az containerapp update \
      --name "$app" \
      --resource-group "$RESOURCE_GROUP" \
      --set-env-vars "${env_args[@]}" >/dev/null
  fi
}

latest_revision_for() {
  local app="$1"
  az containerapp revision list \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --query "sort_by(@, &properties.createdTime)[-1].name" \
    -o tsv 2>/dev/null || true
}

revision_state_for() {
  local app="$1"
  local revision="$2"
  az containerapp revision show \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --revision "$revision" \
    --query properties.runningState \
    -o tsv 2>/dev/null || true
}

wait_for_latest_revision_running() {
  local app="$1"
  local timeout_seconds="${2:-600}"
  local revision
  local elapsed=0

  revision="$(latest_revision_for "$app")"
  if [[ -z "$revision" ]]; then
    echo "No revision found for $app yet."
    return 0
  fi

  echo "Waiting for $app revision $revision to run..."
  while [[ "$elapsed" -lt "$timeout_seconds" ]]; do
    local state
    state="$(revision_state_for "$app" "$revision")"
    if [[ "$state" == "Running" ]]; then
      echo "  $app: $revision is Running"
      return 0
    fi
    if [[ "$state" == "Failed" ]]; then
      echo "  $app: $revision failed. Recent logs:" >&2
      az containerapp logs show --name "$app" --resource-group "$RESOURCE_GROUP" --tail 80 || true
      return 1
    fi
    sleep 10
    elapsed=$((elapsed + 10))
  done

  echo "Timed out waiting for $app revision $revision to run." >&2
  az containerapp revision list --name "$app" --resource-group "$RESOURCE_GROUP" -o table || true
  return 1
}

app_exists() {
  az containerapp show --name "$1" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1
}

secret_ref_for_env() {
  local app="$1"
  local key="$2"
  az containerapp show \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.template.containers[0].env[?name=='$key'].secretRef | [0]" \
    -o tsv 2>/dev/null || true
}

ensure_secret_envs_available() {
  local app="$1"
  shift

  for key in "$@"; do
    local value="${!key:-}"
    if [[ -n "$value" ]]; then
      continue
    fi

    if [[ "$USE_EXISTING_SECRETS" != true ]]; then
      echo "Missing required secret value for $app: $key" >&2
      exit 1
    fi

    local secret_ref
    secret_ref="$(secret_ref_for_env "$app" "$key")"
    if [[ -z "$secret_ref" || "$secret_ref" == "null" ]]; then
      echo "Missing local value for $key and $app does not already reference an Azure secret for this env var." >&2
      echo "Set $key in $ENV_FILE or deploy once with a value before using --use-existing-secrets." >&2
      exit 1
    fi

    echo "Using existing Azure secret ref for $app.$key -> $secret_ref"
  done
}

ensure_local_secret_values_for_new_app() {
  local app="$1"
  shift

  if app_exists "$app"; then
    return
  fi

  for key in "$@"; do
    local value="${!key:-}"
    if [[ -z "$value" ]]; then
      echo "Cannot create $app with --use-existing-secrets because $key has no local value and the app does not exist yet." >&2
      echo "Set $key in $ENV_FILE for the first deployment of this app." >&2
      exit 1
    fi
  done
}

create_app_if_missing() {
  local app="$1"
  local image="$2"
  local port="$3"
  local cpu="$4"
  local memory="$5"

  if app_exists "$app"; then
    return
  fi

  if [[ "$CREATE_MISSING" != true ]]; then
    echo "Container App $app does not exist. Re-run without --no-create or create it first." >&2
    exit 1
  fi

  echo "Creating Container App: $app"
  az containerapp create \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ACA_ENV" \
    --image "$image" \
    --target-port "$port" \
    --ingress external \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --cpu "$cpu" \
    --memory "$memory" \
    --min-replicas 1 \
    --max-replicas 10 >/dev/null
}

build_image() {
  local image_name="$1"
  local dockerfile="$2"
  local context="$3"
  local image_ref="$ACR_LOGIN_SERVER/$image_name:$TAG"

  if [[ "$USE_EXISTING_IMAGE" == true ]]; then
    echo "Using existing image: $image_ref" >&2
  else
    echo "Building image: $image_ref" >&2
    az acr build \
      --registry "$ACR_NAME" \
      --image "$image_name:$TAG" \
      --file "$dockerfile" \
      "$context" >&2
  fi

  echo "$image_ref"
}

update_image() {
  local app="$1"
  local image_ref="$2"
  echo "Updating $app image -> $image_ref"
  az containerapp update \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$image_ref" >/dev/null
}

fqdn_for() {
  local app="$1"
  az containerapp show \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn \
    -o tsv 2>/dev/null || true
}

url_for() {
  local app="$1"
  local fqdn
  fqdn="$(fqdn_for "$app")"
  if [[ -n "$fqdn" ]]; then
    echo "https://$fqdn"
  fi
}

deploy_api() {
  local image
  image="$(build_image nova-api apps/api/Dockerfile apps/api)"
  ensure_local_secret_values_for_new_app "$API_APP" \
    SECRET_KEY ADMIN_API_KEY SETTINGS_ENCRYPTION_KEY PII_ENCRYPTION_KEY \
    MONGODB_URI REDIS_URL VOYAGE_API_KEY AZURE_OPENAI_API_KEY STRAPI_API_TOKEN
  create_app_if_missing "$API_APP" "$image" 8000 1.0 2Gi
  update_image "$API_APP" "$image"

  API_URL="${API_URL:-$(url_for "$API_APP")}"
  ADMIN_URL="${ADMIN_URL:-$(url_for "$ADMIN_APP")}"
  WIDGET_URL="${WIDGET_URL:-$(url_for "$WIDGET_APP")}"
  SHOPIFY_URL="${SHOPIFY_URL:-$(url_for "$SHOPIFY_APP")}"
  STRAPI_URL="${STRAPI_URL:-$(url_for "$STRAPI_APP")}"
  SHOPIFY_MCP_URL="${SHOPIFY_MCP_URL:-${SHOPIFY_URL:+$SHOPIFY_URL/mcp}}"
  CORS_ALLOW_ORIGINS="${API_CORS_ALLOW_ORIGINS:-${CORS_ALLOW_ORIGINS:-$API_URL,$ADMIN_URL,$WIDGET_URL,$SHOPIFY_URL,$STRAPI_URL}}"

  ENVIRONMENT="${ENVIRONMENT:-production}"
  API_PORT="${API_PORT:-8000}"
  REQUIRE_REDIS="${REQUIRE_REDIS:-false}"
  DEFAULT_LLM_PROVIDER="${DEFAULT_LLM_PROVIDER:-azure_openai}"
  VECTOR_BACKEND="${VECTOR_BACKEND:-atlas}"
  VECTOR_INDEX_NAME="${VECTOR_INDEX_NAME:-vector_index}"
  VECTOR_DIMENSIONS="${VECTOR_DIMENSIONS:-1024}"
  MONGO_SYSTEM_DB="${MONGO_SYSTEM_DB:-agent-builder}"
  MONGODB_DATABASE="${MONGODB_DATABASE:-agent-builder}"
  VOYAGE_BASE_URL="${VOYAGE_BASE_URL:-https://api.voyageai.com/v1}"
  VOYAGE_MODEL="${VOYAGE_MODEL:-voyage-3-large}"
  VOYAGE_RERANK_MODEL="${VOYAGE_RERANK_MODEL:-rerank-2.5}"
  ENABLE_HUMAN_TAKEOVER="${ENABLE_HUMAN_TAKEOVER:-true}"

  ensure_secret_envs_available "$API_APP" \
    SECRET_KEY ADMIN_API_KEY SETTINGS_ENCRYPTION_KEY PII_ENCRYPTION_KEY \
    MONGODB_URI REDIS_URL VOYAGE_API_KEY AZURE_OPENAI_API_KEY STRAPI_API_TOKEN

  set_secret_envs "$API_APP" \
    SECRET_KEY ADMIN_API_KEY SETTINGS_ENCRYPTION_KEY PII_ENCRYPTION_KEY \
    MONGODB_URI REDIS_URL VOYAGE_API_KEY AZURE_OPENAI_API_KEY STRAPI_API_TOKEN \
    OPENAI_API_KEY QWEN_API_KEY FIRECRAWL_API_KEY ATLAS_PRIVATE_KEY

  set_plain_envs "$API_APP" \
    ENVIRONMENT API_PORT REQUIRE_REDIS DEFAULT_LLM_PROVIDER \
    VECTOR_BACKEND VECTOR_INDEX_NAME VECTOR_DIMENSIONS MONGO_SYSTEM_DB MONGODB_DATABASE \
    STRAPI_URL SHOPIFY_MCP_URL CORS_ALLOW_ORIGINS CONFIG_VERSION \
    AZURE_OPENAI_MODEL AZURE_OPENAI_DEPLOYMENT AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_VERSION \
    AZURE_OPENAI_ACCOUNT_NAME AZURE_SUBSCRIPTION_ID AZURE_RESOURCE_GROUP \
    ENABLE_HUMAN_TAKEOVER \
    VOYAGE_BASE_URL VOYAGE_MODEL VOYAGE_RERANK_MODEL \
    QDRANT_URL QDRANT_API_KEY QDRANT_COLLECTION_PREFIX \
    ATLAS_PROJECT_ID ATLAS_CLUSTER_NAME ATLAS_PUBLIC_KEY ATLAS_AUTO_CREATE_VECTOR_INDEXES

  wait_for_latest_revision_running "$API_APP"
}

deploy_admin() {
  local image
  image="$(build_image nova-admin apps/admin/Dockerfile apps/admin)"
  create_app_if_missing "$ADMIN_APP" "$image" 3000 0.5 1Gi
  update_image "$ADMIN_APP" "$image"

  API_BASE_URL="${API_BASE_URL:-${API_URL:-$(url_for "$API_APP")}}"
  WIDGET_BASE_URL="${WIDGET_BASE_URL:-${WIDGET_URL:-$(url_for "$WIDGET_APP")}}"
  set_plain_envs "$ADMIN_APP" API_BASE_URL WIDGET_BASE_URL CONFIG_VERSION
  wait_for_latest_revision_running "$ADMIN_APP"
}

deploy_widget() {
  local image
  image="$(build_image nova-widget apps/widget/Dockerfile apps/widget)"
  create_app_if_missing "$WIDGET_APP" "$image" 5174 0.5 1Gi
  update_image "$WIDGET_APP" "$image"

  API_BASE_URL="${API_BASE_URL:-${API_URL:-$(url_for "$API_APP")}}"
  set_plain_envs "$WIDGET_APP" API_BASE_URL CONFIG_VERSION
  wait_for_latest_revision_running "$WIDGET_APP"
}

deploy_shopify() {
  local image
  image="$(build_image nova-shopify-mcp apps/shopify-mcp/Dockerfile apps/shopify-mcp)"
  ensure_local_secret_values_for_new_app "$SHOPIFY_APP" SESSION_SECRET REDIS_URL
  create_app_if_missing "$SHOPIFY_APP" "$image" 3005 0.5 1Gi
  update_image "$SHOPIFY_APP" "$image"

  NODE_ENV="${NODE_ENV:-production}"
  PORT="${PORT:-3005}"
  API_URL="${API_URL:-$(url_for "$API_APP")}"
  local CORS_ALLOW_ORIGINS
  CORS_ALLOW_ORIGINS="${SHOPIFY_CORS_ALLOW_ORIGINS:-${CORS_ALLOW_ORIGINS:-$API_URL}}"

  ensure_secret_envs_available "$SHOPIFY_APP" SESSION_SECRET REDIS_URL
  set_secret_envs "$SHOPIFY_APP" SESSION_SECRET REDIS_URL
  set_plain_envs "$SHOPIFY_APP" NODE_ENV PORT CORS_ALLOW_ORIGINS CONFIG_VERSION
  wait_for_latest_revision_running "$SHOPIFY_APP"
}

deploy_strapi() {
  if [[ -z "$STRAPI_ROOT" || ! -f "$STRAPI_ROOT/Dockerfile" ]]; then
    echo "STRAPI_ROOT is not set or does not contain Dockerfile. Set STRAPI_ROOT=/path/to/agentbuilder-strapi." >&2
    exit 1
  fi

  local image
  image="$(build_image nova-strapi "$STRAPI_ROOT/Dockerfile" "$STRAPI_ROOT")"
  AGENTBUILDER_ADMIN_API_KEY="${AGENTBUILDER_ADMIN_API_KEY:-${ADMIN_API_KEY:-}}"
  ensure_local_secret_values_for_new_app "$STRAPI_APP" \
    DATABASE_PASSWORD STRAPI_API_TOKEN APP_KEYS API_TOKEN_SALT ADMIN_JWT_SECRET \
    TRANSFER_TOKEN_SALT ENCRYPTION_KEY JWT_SECRET AGENTBUILDER_ADMIN_API_KEY
  create_app_if_missing "$STRAPI_APP" "$image" 1337 1.0 2Gi
  update_image "$STRAPI_APP" "$image"

  STRAPI_URL="${STRAPI_URL:-$(url_for "$STRAPI_APP")}"
  API_URL="${API_URL:-$(url_for "$API_APP")}"
  NODE_ENV="${NODE_ENV:-production}"
  HOST="${HOST:-0.0.0.0}"
  PORT="${STRAPI_PORT:-1337}"
  PUBLIC_URL="${PUBLIC_URL:-$STRAPI_URL}"
  ADMIN_PUBLIC_URL="${ADMIN_PUBLIC_URL:-$STRAPI_URL/admin}"
  DATABASE_CLIENT="${DATABASE_CLIENT:-postgres}"
  DATABASE_PORT="${DATABASE_PORT:-5432}"
  DATABASE_SCHEMA="${DATABASE_SCHEMA:-public}"
  DATABASE_SSL="${DATABASE_SSL:-true}"
  DATABASE_SSL_REJECT_UNAUTHORIZED="${DATABASE_SSL_REJECT_UNAUTHORIZED:-false}"
  DATABASE_POOL_MIN="${DATABASE_POOL_MIN:-2}"
  DATABASE_POOL_MAX="${DATABASE_POOL_MAX:-10}"
  DATABASE_CONNECTION_TIMEOUT="${DATABASE_CONNECTION_TIMEOUT:-60000}"
  AGENTBUILDER_API_URL="${AGENTBUILDER_API_URL:-$API_URL}"
  REACT_APP_WS_BASE_URL="${REACT_APP_WS_BASE_URL:-${API_URL/https:/wss:}}"

  ensure_secret_envs_available "$STRAPI_APP" \
    DATABASE_PASSWORD STRAPI_API_TOKEN APP_KEYS API_TOKEN_SALT ADMIN_JWT_SECRET \
    TRANSFER_TOKEN_SALT ENCRYPTION_KEY JWT_SECRET AGENTBUILDER_ADMIN_API_KEY

  set_secret_envs "$STRAPI_APP" \
    DATABASE_PASSWORD STRAPI_API_TOKEN APP_KEYS API_TOKEN_SALT ADMIN_JWT_SECRET \
    TRANSFER_TOKEN_SALT ENCRYPTION_KEY JWT_SECRET AGENTBUILDER_ADMIN_API_KEY

  set_plain_envs "$STRAPI_APP" \
    NODE_ENV HOST PORT PUBLIC_URL ADMIN_PUBLIC_URL \
    DATABASE_CLIENT DATABASE_HOST DATABASE_PORT DATABASE_NAME DATABASE_USERNAME \
    DATABASE_SCHEMA DATABASE_SSL DATABASE_SSL_REJECT_UNAUTHORIZED \
    DATABASE_POOL_MIN DATABASE_POOL_MAX DATABASE_CONNECTION_TIMEOUT \
    AGENTBUILDER_API_URL REACT_APP_WS_BASE_URL CONFIG_VERSION

  wait_for_latest_revision_running "$STRAPI_APP"
}

health_check() {
  echo ""
  echo "Deployment URLs:"
  for app in "$API_APP" "$ADMIN_APP" "$WIDGET_APP" "$SHOPIFY_APP" "$STRAPI_APP"; do
    local url
    url="$(url_for "$app")"
    [[ -n "$url" ]] && echo "  $app: $url"
  done

  local api_url admin_url widget_url shopify_url strapi_url
  api_url="$(url_for "$API_APP")"
  admin_url="$(url_for "$ADMIN_APP")"
  widget_url="$(url_for "$WIDGET_APP")"
  shopify_url="$(url_for "$SHOPIFY_APP")"
  strapi_url="$(url_for "$STRAPI_APP")"

  echo ""
  echo "Quick checks:"
  [[ -n "$api_url" ]] && curl -fsS "$api_url/health" >/dev/null && echo "  API health: ok" || true
  [[ -n "$shopify_url" ]] && curl -fsS "$shopify_url/mcp" >/dev/null && echo "  Shopify MCP: ok" || true
  [[ -n "$strapi_url" ]] && curl -fsSI "$strapi_url/admin" >/dev/null && echo "  Strapi admin: ok" || true
  if [[ -n "$strapi_url" && -n "${STRAPI_API_TOKEN:-}" ]]; then
    curl -fsS \
      -H "Authorization: Bearer $STRAPI_API_TOKEN" \
      "$strapi_url/api/session-sync/health" >/dev/null \
      && echo "  Strapi sync auth: ok" || true
  fi
  if [[ -n "$admin_url" && -n "$api_url" ]]; then
    curl -fsS "$admin_url/runtime-config.js" | grep -q "$api_url" \
      && echo "  Admin runtime API URL: ok" || true
  fi
  if [[ -n "$widget_url" && -n "$api_url" ]]; then
    curl -fsS "$widget_url/runtime-config.js" | grep -q "$api_url" \
      && echo "  Widget runtime API URL: ok" || true
  fi
}

case "$SERVICE" in
  api) deploy_api ;;
  admin) deploy_admin ;;
  widget) deploy_widget ;;
  shopify|shopify-mcp) deploy_shopify ;;
  strapi) deploy_strapi ;;
  all)
    deploy_api
    deploy_shopify
    deploy_admin
    deploy_widget
    deploy_strapi
    # Re-apply API CORS and Shopify MCP URL after every app URL exists.
    deploy_api
    ;;
  *)
    echo "Unknown --service '$SERVICE'. Use: all, api, admin, widget, shopify, strapi" >&2
    exit 1
    ;;
esac

health_check

echo ""
echo "Done. Image tag: $TAG"
echo "Tip: rebuild one service with --service api, or reuse a tag with --use-existing-image --tag $TAG"
