# Server Startup Guide

This guide explains the current supported startup paths for the Agent Builder Platform.

## Recommended path: Docker Compose

Use Docker Compose for the easiest deployment and the most accurate production-like setup.

### Configure runtime env

Backend secrets belong in `.env.docker`.
Frontend API targets are injected at runtime through container env vars, so you can switch local vs production URLs without rebuilding frontend images.

Key variables:

```env
ENVIRONMENT=production
DEBUG=false
ALLOW_ADMIN_KEY_BYPASS=false
SESSION_SECRET=<openssl rand -hex 32>
ADMIN_API_BASE_URL=http://localhost:8000
WIDGET_API_BASE_URL=http://localhost:8000
```

### Start the stack

```bash
docker compose build
docker compose up -d
```

### Verify

```bash
curl http://localhost:8000/live
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

### Access URLs

- API: http://localhost:8000
- Admin: http://localhost:3000
- Widget: http://localhost:5174
- Shopify MCP: http://localhost:3005/health

## Azure Authentication for Key Vault

If you enable Azure Key Vault, the API can authenticate using either:

1. `az login` for local interactive use
2. Service principal env vars:

```env
AZURE_CLIENT_ID=<appId>
AZURE_CLIENT_SECRET=<password>
AZURE_TENANT_ID=<tenant>
```

## Direct local development

If you are iterating locally without Docker, run each app in its own terminal:

```bash
cd apps/api && python run.py
cd apps/admin && npm start
cd apps/widget && npm run dev
cd apps/shopify-mcp && npm start
```

Widget runs on port `5174`, not `5173`.

## Notes

- `/live` is process liveness.
- `/ready` is deployment readiness and returns `503` if required dependencies are unavailable.
- `/health` returns dependency status details.
- In production, keep `DEBUG=false`, avoid wildcard CORS, and set `ADMIN_API_KEY`.
- Frontend runtime config is generated at container startup from environment variables.

## Legacy notes

Older instructions in this repo referenced outdated paths and widget port `5173`. Those are no longer the recommended setup.
