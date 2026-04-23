# Production Hardening Changelog
**Session date:** 2026-04-06  
**Branch:** main  
**Scope:** All 4 apps — admin, api, widget, shopify-mcp

---

## Summary

Two-pass hardening session addressing P0, P1, P2, and P3 items from `docs/PRODUCTION_READINESS_PLAN.md`.

---

## Pass 1 — P0 URL Migrations + P1 Security + P2 Operational

### P0 — Hardcoded localhost URLs fixed

| File | Change |
|---|---|
| `apps/widget/src/utils/activityClient.ts:6` | `'http://localhost:8000'` → `import.meta.env.VITE_API_BASE_URL` |
| `apps/widget/src/main.tsx:9` | `apiUrl: 'http://localhost:8000'` → `import.meta.env.VITE_API_BASE_URL` |
| `apps/admin/.env.example:9` | `REACT_APP_API_BASE_URL` → `REACT_APP_API_URL` (name mismatch with code) |
| `apps/shopify-mcp/src/index.js:113,138` | `http://localhost:3005/auth/callback` → `process.env.SHOPIFY_REDIRECT_URI` |
| `apps/shopify-mcp/src/mcp.js:7` | `http://localhost:3005/auth/login` → `process.env.SHOPIFY_BASE_URL` |

> Note: `apps/widget/src/App.tsx` was already using `VITE_API_BASE_URL` (fixed in a prior commit).

### P0 — Secret defaults removed

| File | Change |
|---|---|
| `apps/api/app/config.py:158` | `SECRET_KEY` default `"your-secret-key-change-in-production"` removed — now a required field; app fails to start if unset |
| `apps/shopify-mcp/src/index.js:20` | `SESSION_SECRET` fallback `'shopify-mcp-secret'` removed — `process.exit(1)` if `SESSION_SECRET` env var is missing |

### P1 — CORS hardening

| File | Change |
|---|---|
| `apps/api/app/main.py:122–123` | `allow_methods=["*"]` → explicit list: `GET, POST, PUT, DELETE, OPTIONS` |
| `apps/api/app/main.py:123` | `allow_headers=["*"]` → explicit list: `Content-Type, Authorization, X-API-Key, X-Request-ID` |
| `apps/shopify-mcp/src/index.js:16` | `cors()` (fully open) → `cors({ origin: allowedOrigins, credentials: true })` where `allowedOrigins` comes from `CORS_ALLOW_ORIGINS` env var |

### P1 — Session cookie security

| File | Change |
|---|---|
| `apps/shopify-mcp/src/index.js:23` | `secure: false` → `secure: process.env.NODE_ENV === 'production'` |
| `apps/shopify-mcp/src/index.js:23` | Added `sameSite: 'lax'` |

### P1 — Error message leakage

| File | Change |
|---|---|
| `apps/shopify-mcp/src/index.js:75–79` | Raw `err.message` in 500 response → `isDev ? err.message : 'Internal server error'` |

### P2 — Source maps disabled in production builds

| File | Change |
|---|---|
| `apps/widget/vite.config.ts` | Added `build: { sourcemap: false }` |
| `apps/admin/Dockerfile` | Added `ENV GENERATE_SOURCEMAP=false` |

### P2 — Stale files removed

| File | Change |
|---|---|
| `apps/widget/vite.config.ts.timestamp-*.mjs` (3 files) | Deleted |
| `.gitignore` | Added `vite.config.ts.timestamp-*.mjs` pattern |

### P3 — Unused dependency removed

| File | Change |
|---|---|
| `apps/shopify-mcp/package.json` | Removed `@shopify/shopify-api` v10 (imported nowhere in source) |

### New/updated .env.example files

| File | Change |
|---|---|
| `apps/shopify-mcp/.env.example` | Created (was missing entirely) — covers `SESSION_SECRET`, `SHOPIFY_REDIRECT_URI`, `SHOPIFY_BASE_URL`, `CORS_ALLOW_ORIGINS`, `REDIS_URL` |
| `apps/api/.env.example` | Updated `SECRET_KEY` to blank (no placeholder value), added `CORS_ALLOW_ORIGINS` with production domain placeholders, added `STRAPI_URL`, `SHOPIFY_MCP_URL`, `FIRECRAWL_API_KEY` |
| `apps/admin/.env.example` | Fixed `REACT_APP_API_BASE_URL` → `REACT_APP_API_URL` |

---

## Pass 2 — P1 Auth Wiring + Multi-instance State + Redis Sessions

### P1 — Admin write routes protected

New file: `apps/api/app/auth/admin_key.py`

A lightweight `require_admin_key` FastAPI dependency that checks the `X-Admin-Key` header against the `ADMIN_API_KEY` env var using `secrets.compare_digest`. Bypassed automatically when `ADMIN_API_KEY` is not set (dev convenience). Uses `process.exit`-equivalent: if the key is set and the header is missing or wrong, returns 401/403.

Routes now protected (POST, PUT, DELETE only — GETs remain public for widget bootstrap):

| Router | Protected methods |
|---|---|
| `apps/api/app/api/v1/admin/brands.py` | POST `/`, PUT `/{id}`, DELETE `/{id}` |
| `apps/api/app/api/v1/admin/agents.py` | POST `/`, PUT `/{id}`, DELETE `/{id}` |
| `apps/api/app/api/v1/endpoints/ingestion.py` | POST `/documents`, POST `/chunks`, DELETE `/jobs/{id}` |

Admin UI change: `apps/admin/src/api/client.ts` reads `REACT_APP_ADMIN_API_KEY` and sends it as `X-Admin-Key` on every request. Added to `apps/admin/.env.example` and `apps/admin/Dockerfile` as a build arg.

### P1 — Multi-instance job state migrated to Redis

New file: `apps/api/app/services/job_store.py`

`JobStore` class: async get/set/update/delete backed by Redis with 24h TTL. Falls back to in-memory dict if Redis is unavailable (allows local dev without Redis). Uses the existing `connection_manager.redis_client`.

Updated services:

| Service | Change |
|---|---|
| `apps/api/app/services/ingestion_service.py` | `self.active_jobs = {}` → `self.job_store = JobStore()`. All dict access replaced with `await self.job_store.set/update/get` |
| `apps/api/app/services/knowledge_service.py` | Same — including inner methods `_process_product_item` and `_process_dealer_item` |

### P1 — Redis sessions for shopify-mcp

| File | Change |
|---|---|
| `apps/shopify-mcp/package.json` | Added `connect-redis ^7.1.1` and `redis ^4.6.14` |
| `apps/shopify-mcp/src/index.js` | In `NODE_ENV=production`: creates Redis client from `REDIS_URL`, uses `RedisStore`. In dev: keeps `MemoryStore` |
| `apps/shopify-mcp/.env.example` | Added `REDIS_URL` |

### P1 — WebSocket manager (documented, not yet refactored)

`apps/api/app/websocket_manager.py`: Added detailed TODO comment explaining the Redis pub/sub migration required before running >1 API replica. The in-process dict remains functional for single-instance deployments.

---

---

## Pass 3 — Catalog JobStore, DB Port Lockdown, Shopify Retry, Console.log Cleanup

### P1 — `catalog_service.py` job dict → Redis-backed `JobStore`

`catalog_service.py` had a module-level `_jobs: Dict[str, Dict]` that shared the same multi-instance bug as ingestion/knowledge.

- `create_job(job_id, job_type)` → `async create_job(job_id, job_type, total=0)` backed by `_job_store = JobStore()`
- `get_job(job_id)` → `async get_job(job_id)`
- All in-place `job["field"] = value` mutations in `fetch_shopify_products` and `run_firecrawl_scrape` replaced with `await _job_store.update(job_id, {...})`
- `apps/api/app/api/v1/endpoints/catalog.py` updated: `create_job` and `get_job` calls are now `await`ed

### P1 — Exposed database ports removed from docker-compose

| Service | Before | After |
|---|---|---|
| MongoDB | `ports: ["27017:27017"]` — host-exposed | Port binding removed; comment explains how to temporarily re-add for Compass |
| Redis | `ports: ["6379:6379"]` — host-exposed | Port binding removed; same comment |

Both services remain accessible internally to other containers via Docker networking.

### P1 — Shopify 429 rate-limit retry in `shopify.js`

`forwardMcpRequest` previously threw immediately on any non-OK response. Now:
- Retries up to 3 times on HTTP 429
- Respects `Retry-After` response header; falls back to `attempt × 1000ms` if header is absent
- Non-OK responses (non-429) throw a typed error with `.status` property for caller inspection

### P2 — All `console.log` calls gated in production

**Widget** (`apps/widget/src/utils/apiClient.ts`):
- Added `const isDev = import.meta.env.DEV;` at top of file
- All 17 `console.log` / `console.warn` calls in the streaming path wrapped with `isDev &&`
- `console.error` calls left untouched (intentional error reporting)

**Admin** (9 files, 74 calls total):
- Added `const isDev = process.env.NODE_ENV !== 'production';` to each affected file
- Every `console.log` call wrapped with `isDev &&`
- `console.error` and `console.warn` left untouched

Files updated: `AgentWizard.tsx`, `AgentDetail.tsx`, `StepKnowledgeBase.tsx`, `StepReview.tsx`, `DocumentUploadWizard.tsx`, `DocumentsList.tsx`, `JsonFieldMapper.tsx`, `JsonUpload.tsx`, `api/client.ts`

---

## Pass 4 — WebSocket Redis Pub/Sub + Shopify HMAC Webhook Verification

### P1 — Shopify HMAC webhook verification

New endpoint: `POST /webhooks` in `apps/shopify-mcp/src/index.js`

- `express.json()` now runs with a `verify` callback that captures `req.rawBody` (required — HMAC must be computed over the raw bytes, not the parsed JSON)
- Handler verifies `X-Shopify-Hmac-SHA256` header: HMAC-SHA256 over raw body using `SHOPIFY_WEBHOOK_SECRET`, base64-encoded, compared with `crypto.timingSafeEqual` (constant-time)
- Returns 401 on missing header or invalid signature — Shopify will retry on non-2xx
- Returns 500 if `SHOPIFY_WEBHOOK_SECRET` is not configured (warns operator rather than silently accepting)
- Logs `x-shopify-topic` and `x-shopify-shop-domain` on success; leaves a TODO for topic-specific dispatch handlers
- `SHOPIFY_WEBHOOK_SECRET` added to `apps/shopify-mcp/.env.example` with instructions to copy from Shopify Partner Dashboard

### P2 — Rate limiter fail-open behavior documented and alerted

`apps/api/app/security/rate_limiter.py`

- Added module-level docstring explaining the fail-open policy: when Redis is unavailable, all requests are allowed through (availability over security trade-off)
- Documents the security implication: an attacker who triggers a Redis failure bypasses rate limiting
- Documents how to harden if needed (replace fail-open return with a 503 raise)
- Upgraded the exception log from `logger.error("rate_limit_check_failed", ...)` to `logger.warning("rate_limiter_fail_open", event="rate_limiter_fail_open", ..., note="rate limiting bypassed — Redis unreachable")` — the structured `event` field makes it trivially filterable in log aggregators for alerting

### P3 — Docker healthchecks for admin and widget

`docker-compose.yml` — both nginx services now have healthchecks matching the pattern already used by `shopify`:

- `admin`: `wget --spider http://localhost:3000/` — 30s interval, 10s timeout, 3 retries, 10s start_period
- `widget`: `wget --spider http://localhost:5174/` — same settings

Both services now participate in Docker health monitoring. Dependent services (or orchestrators like ECS/Kubernetes) can gate on `service_healthy` condition if desired.

### P1 — WebSocket manager fully migrated to Redis pub/sub

`apps/api/app/websocket_manager.py` — complete rewrite.

**Before:** In-process dicts for connections and all shared state (human control, agent_id, takeover buffer). Broke on >1 API replica — different instances couldn't deliver messages across processes.

**After:**
- Local per-instance WebSocket dicts (WebSocket objects can't be serialized across processes — correct)
- Cross-instance fanout via Redis pub/sub: `send_to_widget` / `send_to_admin` publish to `conv:{conv_id}:widget` / `conv:{conv_id}:admin` channels
- `_subscribe_loop` — async background task per connection; subscribes to Redis channel, forwards arriving messages to local WebSocket connections
- `_start_sub` / `_stop_sub` — task lifecycle tied to connection connect/disconnect
- Shared state (human control flag, agent_id, takeover buffer) stored in Redis hash `conv:{conv_id}:state` and list `conv:{conv_id}:buffer` with 24h TTL
- Full in-process fallback when Redis is unavailable (same `connection_manager.redis_client` pattern as `JobStore`)

Methods now `async`: `set_human_control`, `is_human_in_control`, `register_agent_id`, `get_agent_id`, `buffer_takeover_message`, `pop_takeover_buffer`, `disconnect_widget`, `disconnect_admin`

`apps/api/app/api/v1/endpoints/messages.py` — all 10 `ws_manager.*` call sites updated with `await`:
- `await ws_manager.set_human_control(...)` (×2 — take_control, release_control)
- `await ws_manager.pop_takeover_buffer(...)`
- `await ws_manager.get_agent_id(...)`
- `await ws_manager.buffer_takeover_message(...)` (×2 — admin_message, user_message)
- `await ws_manager.register_agent_id(...)`
- `if await ws_manager.is_human_in_control(...):`
- `await ws_manager.disconnect_admin(...)` (finally block)
- `await ws_manager.disconnect_widget(...)` (finally block)

---

## New env vars introduced

| App | Variable | Purpose |
|---|---|---|
| api | `ADMIN_API_KEY` | Guards admin write operations — must match `REACT_APP_ADMIN_API_KEY` in admin |
| admin | `REACT_APP_ADMIN_API_KEY` | Sent as `X-Admin-Key` header on all API mutations |
| shopify-mcp | `SHOPIFY_REDIRECT_URI` | OAuth callback URL (replaces hardcoded localhost) |
| shopify-mcp | `SHOPIFY_BASE_URL` | Base URL for auth login links in error responses |
| shopify-mcp | `CORS_ALLOW_ORIGINS` | Comma-separated allowed CORS origins |
| shopify-mcp | `REDIS_URL` | Redis connection for session store in production |
| shopify-mcp | `SHOPIFY_WEBHOOK_SECRET` | Signing secret for `POST /webhooks` HMAC verification |
