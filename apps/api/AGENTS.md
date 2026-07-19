# AGENTS.md — FastAPI Backend (apps/api)

> **Scope:** FastAPI backend application for the Agent Builder Platform

---

## 1. Application Overview
This is the core FastAPI backend providing:
- **Messages API** with WebSocket + SSE streaming
- **Ingestion API** with document chunking pipeline
- **Health checks** and monitoring endpoints
- **CORS** and security middleware

### Architecture
- **FastAPI** with async/await support
- **WebSockets** for real-time streaming
- **SSE** (Server-Sent Events) for message streaming
- **Pydantic** for request/response validation
- **OpenTelemetry** for tracing and observability

---

## 2. Environment Variables

| Key | Required | Example | Notes |
| --- | --- | --- | --- |
| `API_LOG_LEVEL` | No | `info` | `debug` \| `info` \| `warn` \| `error` |
| `API_HOST` | No | `0.0.0.0` | Bind address |
| `API_PORT` | No | `8000` | Server port |
| `CORS_ALLOW_ORIGINS` | No | `*` | Comma-separated origins |
| `REDIS_URL` | Yes | `redis://localhost:6379` | Cache backend |
| `MONGO_URI` | Yes | `mongodb://...` | Database connection |
| `DEFAULT_LLM_PROVIDER` | Yes | `openai` or `azure_openai` | Active LLM adapter |
| `AZURE_OPENAI_ENDPOINT` | If `azure_openai` | `https://<resource>.openai.azure.com/` | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_VERSION` | If `azure_openai` | `2025-...` | Azure API version to call |
| `AZURE_OPENAI_DEPLOYMENT` | Optional | `gpt-5.4-mini` | Defaults to the configured Azure model |
| `AZURE_SUBSCRIPTION_ID` | For admin Azure discovery | `00000000-...` | Azure subscription used for ARM deployment discovery |
| `AZURE_RESOURCE_GROUP` | For admin Azure discovery | `agentbuilder-rg` | Resource group containing the Azure OpenAI account |
| `AZURE_OPENAI_ACCOUNT_NAME` | For admin Azure discovery | `anant-resource` | Azure OpenAI account name used on the ARM deployments route |
| `SETTINGS_ENCRYPTION_KEY` | Recommended | `random-32-char-string` | Encrypts runtime settings stored in MongoDB. Falls back to `PII_ENCRYPTION_KEY`, then `SECRET_KEY`. |

---

## 3. API Endpoints

### Health & Status
- `GET /health` - Health check
- `GET /api/v1/status` - System status

### Messages API
- `POST /api/v1/messages` - Send message (streaming response)
- `WS /api/v1/messages/ws` - WebSocket connection
- `GET /api/v1/messages/stream` - SSE stream

### Ingestion API
- `POST /api/v1/ingest/documents` - Upload documents
- `POST /api/v1/ingest/chunks` - Process chunks
- `GET /api/v1/ingest/status/{job_id}` - Check ingestion status

### Admin LLM API
- `GET /api/v1/admin/llm/azure/deployments` - List Azure OpenAI deployments for the admin dashboard picker

### Admin Runtime Settings API
- `GET /api/v1/admin/settings/runtime` - Read masked runtime settings for the admin dashboard
- `PUT /api/v1/admin/settings/runtime` - Create/update/clear encrypted runtime settings
- `POST /api/v1/admin/settings/runtime/test` - Validate Azure OpenAI and Voyage connectivity without exposing plaintext secrets

---

## 4. Development

### Local Development
```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Testing
```bash
pytest tests/ -v
curl http://localhost:8000/health
```

---

## 5. Integration Notes

- Uses shared packages: `commons`, `memory`, `retrieval`, `llm`
- Implements SLOs: P95 latency ≤ 3s, citation coverage 100%
- Follows "No source → No answer" principle
- All responses include citation tracking
- Azure deployment discovery for the admin UI uses ARM + `DefaultAzureCredential`; if the ARM env vars are missing, the endpoint returns `503`
- Runtime provider secrets are resolved from encrypted records in the system DB first, then from environment variables as bootstrap/fallback
- Strapi dashboard provisioning for agents must be best-effort and non-blocking; agent create/update/delete should not fail after Mongo writes because Strapi is unavailable
- Generated factual answers must pass the deterministic claim-evidence gate before persistence or delivery. Server-owned safety templates and non-factual clarification may bypass it; raw evidence/provider data must never reach public metadata.
- Ingestion job state and worker leases are owned by the system MongoDB store; Redis is a non-authoritative read cache only. `POST /ingest/documents` stores encrypted, TTL-bound source payloads plus an immutable creation-time agent/brand/chunking snapshot before responding. `Idempotency-Key` is scoped to that agent and brand: the same source reuses its job while divergent source content is rejected. The `ingestion-worker` compose service claims only v2 jobs with Mongo leases, always publishes to the snapshotted `brand_slug`, and uses deterministic upserts after a pre-publish staging boundary. Status/cancel authorization uses the immutable creation-time brand scope.
- `POST /knowledge/upload` and `POST /knowledge/bulk-upload` use the same durable worker protocol. Their source bytes plus folder/product/dealer context are encrypted before a job is queued; do not reintroduce `BackgroundTasks` for any route that produces embeddings or vectors. Keep product/variant fields intact when extending this path.
- Public takeover channels are scoped by a Mongo-backed widget conversation record. Widget control uses `Sec-WebSocket-Protocol: widget-session, <token>` and operator control uses `Sec-WebSocket-Protocol: bearer, <dashboard-token>`; never add credentials, agent IDs, or control secrets to a WebSocket URL. Dashboard control must verify both `message:write` and the stored brand scope.
- Rate limits fail closed by default. Production Qdrant must remain private/authenticated (`QDRANT_API_KEY`) and upload paths must enforce per-file, aggregate, and DOCX archive-expansion limits before durable storage.
- Production upload paths require a private ClamAV-compatible scanner (`MALWARE_SCAN_MODE=clamav`) before source bytes enter encrypted durable storage. Scanner errors fail closed; local development may use the explicitly disabled mode only for fixtures.
- The repository-root `packages/` directory is the sole canonical shared-package source. Do not add or restore `apps/api/packages`; Docker, CI, tests, and local startup must resolve `commons`, `llm`, `memory`, `retrieval`, `tools`, and `agent_runtime` only from the root tree.
