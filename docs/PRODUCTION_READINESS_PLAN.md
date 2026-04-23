# Production Readiness Plan
**Date:** 2026-04-06  
**Scope:** All 4 apps — `admin`, `api`, `widget`, `shopify-mcp`  
**Changelog:** `docs/CHANGELOG_PROD_HARDENING.md`

---

## P0 — Will Break on First Deploy

### 1. Hardcoded localhost URLs — ✅ DONE

All 6 hardcoded URLs replaced with env vars. See changelog for file-by-file detail.

### 2. Secrets committed to git — ⚠️ MANUAL ACTION REQUIRED

`.env` and `.env.docker` are already in `.gitignore` — they won't be committed going forward.

**You must manually rotate these credentials** (they were in git history):

| Secret | Where to rotate |
|---|---|
| Azure Client Secret + Client ID + Tenant ID | Azure Portal → App Registrations → Certificates & Secrets |
| Strapi API Token | Strapi admin → Settings → API Tokens |
| MongoDB Atlas URI credentials | Atlas → Database Access → Edit user |
| Firecrawl API Key | Firecrawl dashboard → API Keys |

> Until these are rotated, anyone with repo read access can use them.

---

## P1 — Security Risk / Breaks Under Real Traffic

### 3. Auth wiring — ✅ DONE (partial)

All admin + ingestion write routes (POST/PUT/DELETE) are now protected by `require_admin_key` dependency (`X-Admin-Key` header, checked against `ADMIN_API_KEY` env var).

GET routes are intentionally left public — the widget calls them to bootstrap.

**Still pending:**
- `POST /api/v1/messages/stream` — currently public. Acceptable for widget chat; consider API key per-agent if abuse becomes a concern.
- `POST /mcp` on shopify-mcp — no auth. Low priority until shopify-mcp is externally exposed.

### 4. Multi-instance state — ✅ DONE (partial)

| Component | Status |
|---|---|
| `ingestion_service.py` active_jobs | ✅ Migrated to Redis-backed `JobStore` |
| `knowledge_service.py` active_jobs | ✅ Migrated to Redis-backed `JobStore` |
| `shopify-mcp` MemoryStore sessions | ✅ Redis store in production, MemoryStore fallback in dev |
| `websocket_manager.py` in-process connections | ⏳ Documented with TODO — needs Redis pub/sub (bigger refactor) |
| `catalog_service.py` module-level `_jobs` dict | ❌ NOT DONE — same pattern as ingestion/knowledge, needs `JobStore` |

### 5. Security hardening — ✅ DONE (partial)

| Issue | Status |
|---|---|
| `SECRET_KEY` default removed — now required | ✅ Done |
| `SESSION_SECRET` default removed — exit(1) if missing | ✅ Done |
| shopify-mcp CORS locked to `CORS_ALLOW_ORIGINS` | ✅ Done |
| FastAPI CORS methods + headers locked | ✅ Done |
| Session cookies `secure: true` in production | ✅ Done |
| Raw `err.message` gated in production | ✅ Done |
| MongoDB port 27017 exposed to host | ❌ NOT DONE — `docker-compose.yml:84` |
| Redis port 6379 exposed to host | ❌ NOT DONE — `docker-compose.yml:101` |
| No Shopify HMAC webhook verification | ❌ NOT DONE — no webhook endpoint exists yet; implement when webhooks are added |
| No 429/rate-limit handling on Shopify API calls | ❌ NOT DONE — `shopify-mcp/src/shopify.js:85–107` needs retry + backoff |

---

## P2 — Operational Debt

| Issue | Status |
|---|---|
| Source maps in production (admin + widget) | ✅ Done — `GENERATE_SOURCEMAP=false` + `build.sourcemap: false` |
| Raw error in shopify-mcp 500 | ✅ Done |
| 17+ `console.log` in `widget/src/utils/apiClient.ts` | ❌ NOT DONE — logs full request bodies + chunk content |
| 50+ `console.log` across admin components | ❌ NOT DONE |
| Rate limiter fails open when Redis is down | ❌ NOT DONE — `security/rate_limiter.py:111` — needs decision + documentation |

---

## P3 — Nice to Have

| Issue | Status |
|---|---|
| Unused `@shopify/shopify-api` dependency | ✅ Done — removed from package.json |
| 3 stale Vite timestamp files | ✅ Done — deleted + added to .gitignore |
| Admin + widget Docker healthchecks | ❌ NOT DONE — `docker-compose.yml` (nginx services have no healthcheck) |

---

## Remaining Work (ordered by priority)

| Priority | Item | File | Notes |
|---|---|---|---|
| P0 | Rotate leaked secrets | Manual | Azure, MongoDB, Strapi, Firecrawl — **do this now** |
| P1 | ~~`catalog_service.py` job dict → `JobStore`~~ | — | ✅ Done (Pass 3) |
| P1 | ~~Remove exposed DB ports from docker-compose~~ | — | ✅ Done (Pass 3) |
| P1 | ~~Shopify rate limit retry~~ | — | ✅ Done (Pass 3) |
| P2 | ~~`console.log` cleanup in widget~~ | — | ✅ Done (Pass 3) |
| P2 | ~~`console.log` cleanup in admin~~ | — | ✅ Done (Pass 3) |
| P1 | ~~WebSocket manager → Redis pub/sub~~ | — | ✅ Done (Pass 4) |
| P2 | ~~Rate limiter fail-open documentation~~ | — | ✅ Done (Pass 4) |
| P1 | ~~HMAC webhook verification~~ | — | ✅ Done (Pass 4) |
| P3 | ~~Docker healthchecks for admin + widget~~ | — | ✅ Done (Pass 4) |
