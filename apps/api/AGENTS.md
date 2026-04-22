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
