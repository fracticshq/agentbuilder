# NOVA Azure Deployment Script

This document explains how to use the Azure Container Apps deployment helper:

```bash
scripts/deploy_to_azure.local.sh
```

The script is safe to track because secrets stay in `.env.azure`, which remains local and ignored. It validates `.env.azure` before touching Azure and can optionally print full values with `--show-secrets` for private troubleshooting.

## What It Deploys

The helper can build, push, and update these NOVA services:

- `api`: FastAPI backend from `apps/api`
- `admin`: AgentBuilder admin UI from `apps/admin`
- `widget`: embeddable chat widget from `apps/widget`
- `shopify`: Shopify MCP service from `apps/shopify-mcp`
- `strapi`: Strapi admin/session service from the sibling `agentbuilder-strapi` repo
- `all`: deploys everything and reapplies API CORS/Shopify URLs after all app URLs exist

Images are built with Azure Container Registry build and deployed to Azure Container Apps.

## Prerequisites

Install and authenticate Azure CLI:

```bash
az login
az account set --subscription "<SUBSCRIPTION_ID>"
```

Azure resources expected by the script:

- Resource group
- Azure Container Registry
- Azure Container Apps environment
- MongoDB Atlas or local MongoDB reachable from Azure
- Redis, recommended for production
- Azure PostgreSQL for Strapi
- Existing Azure OpenAI deployment, if using Azure OpenAI

## Required Shell Variables

Set these before running the script:

```bash
export SUBSCRIPTION_ID="<azure-subscription-id>"
export RESOURCE_GROUP="nova-prod-rg"
export ACR_NAME="novaprodacr001"
export ACA_ENV="nova-prod-env"
```

Optional app names:

```bash
export API_APP="agentbuilder-api"
export ADMIN_APP="agentbuilder-admin"
export WIDGET_APP="agentbuilder-widget"
export SHOPIFY_APP="agentbuilder-shopify"
export STRAPI_APP="agentbuilder-strapi"
export STRAPI_ROOT="/path/to/agentbuilder-strapi"
```

If `STRAPI_ROOT` is not set, the script assumes Strapi is a sibling repo at:

```bash
../agentbuilder-strapi
```

## Local Env File

Create a local `.env.azure` file in the repo root. Do not commit it.

Example shape:

```bash
SECRET_KEY="..."
ADMIN_API_KEY="..."
SETTINGS_ENCRYPTION_KEY="..."
PII_ENCRYPTION_KEY="..."

MONGODB_URI="..."
MONGO_SYSTEM_DB="agent-builder"
MONGODB_DATABASE="agent-builder"

REDIS_URL="rediss://..."

DEFAULT_LLM_PROVIDER="azure_openai"
AZURE_OPENAI_API_KEY="..."
AZURE_OPENAI_MODEL="gpt-5.4-mini"
AZURE_OPENAI_DEPLOYMENT="gpt-5.4-mini"
AZURE_OPENAI_ENDPOINT="https://<resource>.cognitiveservices.azure.com"
AZURE_OPENAI_API_VERSION="2025-04-01-preview"

VOYAGE_API_KEY="..."
VOYAGE_BASE_URL="https://api.voyageai.com/v1"
VOYAGE_MODEL="voyage-3-large"
VOYAGE_RERANK_MODEL="rerank-2.5"

# If you are using a MongoDB Atlas Model API key instead of a native Voyage key,
# set VOYAGE_BASE_URL="https://ai.mongodb.com/v1".

API_CORS_ALLOW_ORIGINS="https://agentbuilder-api.example.com,https://agentbuilder-admin.example.com,https://agentbuilder-widget.example.com,https://agentbuilder-shopify.example.com,https://agentbuilder-strapi.example.com"

VECTOR_BACKEND="atlas"
VECTOR_INDEX_NAME="vector_index"
VECTOR_DIMENSIONS="1024"

DATABASE_HOST="<postgres-server>.postgres.database.azure.com"
DATABASE_NAME="agentbuilder_strapi"
DATABASE_USERNAME="strapiadmin"
DATABASE_PASSWORD="..."

STRAPI_API_TOKEN="..."
AGENTBUILDER_ADMIN_API_KEY="..." # usually the same value as ADMIN_API_KEY
APP_KEYS="..."
API_TOKEN_SALT="..."
ADMIN_JWT_SECRET="..."
TRANSFER_TOKEN_SALT="..."
ENCRYPTION_KEY="..."
JWT_SECRET="..."
```

Sensitive values are written to Azure Container App secrets by the script. Non-sensitive runtime config is written as plain environment variables.

## Deploy Everything

From the `agentbuilder` repo root:

```bash
./scripts/deploy_to_azure.local.sh --service all
```

Recommended production deploy command when secrets already exist in Azure Container Apps:

```bash
./scripts/deploy_to_azure.local.sh --service all --use-existing-secrets
```

Private debugging command when you intentionally want to print the exact values being applied:

```bash
./scripts/deploy_to_azure.local.sh --service all --use-existing-secrets --show-secrets
```

The script will:

1. Validate `.env.azure`.
2. Build service images in ACR.
3. Create missing Container Apps when needed.
4. Update each app image.
5. Apply shared secrets and environment variables.
6. Force fresh service revisions with `CONFIG_VERSION`.
7. Wait for latest revisions to become `Running`.
8. Print service URLs.
9. Run quick health checks.

For `--service all`, the deployment order is:

1. `api`
2. `shopify`
3. `admin`
4. `widget`
5. `strapi`
6. `api` again

The second API pass is intentional. It reapplies final `CORS_ALLOW_ORIGINS` and `SHOPIFY_MCP_URL` after every public app URL exists.

## Validate Without Deploying

```bash
python3 scripts/validate_azure_env.py --env-file .env.azure --service all
```

To print full secret values during private debugging:

```bash
python3 scripts/validate_azure_env.py --env-file .env.azure --service all --show-secrets
```

To make the deploy script validate and stop before Azure changes:

```bash
./scripts/deploy_to_azure.local.sh --service all --dry-run
```

If a secret already exists in Azure Container Apps and you do not want to rotate it from `.env.azure`, use:

```bash
./scripts/deploy_to_azure.local.sh --service all --dry-run --use-existing-secrets
```

This accepts missing local secret values only when the target Container App already has an env var pointing at an Azure secret ref. It will still fail for first-time app creation unless the required secret value is present locally.

## Deploy One Service

Each command below builds the service image, pushes it to ACR, updates the matching Azure Container App, applies env/secrets for that service, waits for the latest revision to become `Running`, and then runs the shared health checks.

API:

```bash
./scripts/deploy_to_azure.local.sh --service api
```

Admin dashboard:

```bash
./scripts/deploy_to_azure.local.sh --service admin
```

Widget:

```bash
./scripts/deploy_to_azure.local.sh --service widget
```

Shopify MCP:

```bash
./scripts/deploy_to_azure.local.sh --service shopify
```

The alias `shopify-mcp` is also accepted:

```bash
./scripts/deploy_to_azure.local.sh --service shopify-mcp
```

Strapi:

```bash
./scripts/deploy_to_azure.local.sh --service strapi
```

For production updates where Azure secrets should be reused rather than overwritten from `.env.azure`, add `--use-existing-secrets`. The script also applies `CONFIG_VERSION` so secret-only updates create fresh revisions:

```bash
./scripts/deploy_to_azure.local.sh --service api --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service admin --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service widget --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service shopify --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service strapi --use-existing-secrets
```

Recommended order when deploying services manually:

1. API first, so backend routes and shared runtime config are available.
2. Shopify MCP, so API can point tools at the MCP endpoint.
3. Admin and widget, so frontend runtime config points at the production API.
4. Strapi, so admin/session sync and websocket settings are refreshed.
5. API again, so final CORS and `SHOPIFY_MCP_URL` include all live URLs.

Copy-paste manual production sequence:

```bash
./scripts/deploy_to_azure.local.sh --service api --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service shopify --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service admin --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service widget --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service strapi --use-existing-secrets
./scripts/deploy_to_azure.local.sh --service api --use-existing-secrets
```

## Reuse An Existing Image

Use this when you only want to reapply env vars or app configuration:

```bash
./scripts/deploy_to_azure.local.sh --service api --use-existing-image --tag <existing-tag>
```

You can combine existing-image and existing-secret mode:

```bash
./scripts/deploy_to_azure.local.sh --service api --use-existing-image --tag <existing-tag> --use-existing-secrets
```

The default tag format is:

```text
YYYYMMDDHHMMSS-<git-sha>
```

## Use A Different Env File

```bash
./scripts/deploy_to_azure.local.sh --service all --env-file .env.azure.production
```

## Print Values While Deploying

By default, validation shows fingerprints for secrets. For a private debugging run where you want to see exact values:

```bash
./scripts/deploy_to_azure.local.sh --service all --show-secrets
```

You can combine this with existing Azure secrets:

```bash
./scripts/deploy_to_azure.local.sh --service all --use-existing-secrets --show-secrets
```

Rotate any secret printed into terminals, logs, or chats after troubleshooting.

## Avoid Creating Apps

Use `--no-create` when the Container Apps must already exist:

```bash
./scripts/deploy_to_azure.local.sh --service api --no-create
```

## Useful Verification Commands

Set URLs from Azure Container Apps:

```bash
export API_URL="https://$(az containerapp show --name agentbuilder-api --resource-group nova-prod-rg --query properties.configuration.ingress.fqdn -o tsv)"
export ADMIN_URL="https://$(az containerapp show --name agentbuilder-admin --resource-group nova-prod-rg --query properties.configuration.ingress.fqdn -o tsv)"
export WIDGET_URL="https://$(az containerapp show --name agentbuilder-widget --resource-group nova-prod-rg --query properties.configuration.ingress.fqdn -o tsv)"
export SHOPIFY_URL="https://$(az containerapp show --name agentbuilder-shopify --resource-group nova-prod-rg --query properties.configuration.ingress.fqdn -o tsv)"
export STRAPI_URL="https://$(az containerapp show --name agentbuilder-strapi --resource-group nova-prod-rg --query properties.configuration.ingress.fqdn -o tsv)"
```

Check latest revisions:

```bash
az containerapp revision list \
  --name agentbuilder-api \
  --resource-group nova-prod-rg \
  -o table
```

Check logs:

```bash
az containerapp logs show \
  --name agentbuilder-api \
  --resource-group nova-prod-rg \
  --tail 100
```

Smoke test service health:

```bash
curl -i "$API_URL/health"
curl -I "$ADMIN_URL"
curl -I "$WIDGET_URL"
curl -i "$SHOPIFY_URL/health"
curl -i "$SHOPIFY_URL/mcp"
curl -I "$STRAPI_URL/admin"
curl -i "$STRAPI_URL/api/session-sync/health" \
  -H "Authorization: Bearer $STRAPI_API_TOKEN"
```

Expected production health signals:

- API `/health` returns `mongodb: healthy` and `redis: healthy`.
- Shopify `/health` returns `OK`.
- Shopify `/mcp` returns JSON with `"status": "ready"`.
- Strapi `/admin` returns HTTP `200`.
- Strapi `/api/session-sync/health` returns `status: ok`, production `agentBuilderApiUrl`, `wss://` `wsBaseUrl`, and `adminApiKeyConfigured: true`.

## Notes

- Rotate any keys that were pasted into terminals, chats, or logs.
- Keep `.env.azure` local.
- API and Strapi must share the same `STRAPI_API_TOKEN`.
- API `ADMIN_API_KEY` and Strapi `AGENTBUILDER_ADMIN_API_KEY` must match for Strapi live admin websocket access.
- The API deploy is run twice when using `--service all` so final CORS and Shopify MCP URLs include the generated app URLs.
- Use `API_CORS_ALLOW_ORIGINS` for the API allowlist. Use `SHOPIFY_CORS_ALLOW_ORIGINS` only when the Shopify MCP service needs a different allowlist.
