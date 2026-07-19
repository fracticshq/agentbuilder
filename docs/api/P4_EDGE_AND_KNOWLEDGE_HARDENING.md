# P4 edge, real-time, and knowledge-ingestion hardening

P4 closes the remaining public-edge and in-process ingestion gaps before a
multi-tenant production rollout.

## Rate limiting and readiness

`RATE_LIMIT_FAIL_CLOSED` defaults to `true` and must remain true in production.
If Redis cannot enforce an HTTP or WebSocket bucket, the request is rejected
instead of receiving an unthrottled fallback. The API Compose service also
requires Redis for readiness by default (`REQUIRE_REDIS=true`).

## Tenant-scoped takeover channels

Starting a public widget session now persists an immutable, TTL-bound
conversation scope in `system.widget_conversation_scopes`:

```text
conversation_id -> user_id, agent_id, brand_id, brand_slug, expires_at
```

The record is created before `POST /api/v1/messages/session` returns. A
session cannot be used for human-takeover control unless its signed token and
this server-side scope agree.

### Widget control WebSocket

`WS /api/v1/messages/ws/widget/{conversation_id}` requires the widget session
in a WebSocket subprotocol pair:

```text
Sec-WebSocket-Protocol: widget-session, <widget-session-jwt>
```

The URL no longer accepts `agent_id` or `control_secret`. The former
first-use-secret (TOFU) flow was removed. A caller must own the exact signed
conversation and match the persisted agent/brand scope.

### Operator takeover WebSocket

`WS /api/v1/messages/ws/admin/{conversation_id}` requires a dashboard access
JWT in the corresponding subprotocol pair:

```text
Sec-WebSocket-Protocol: bearer, <dashboard-access-jwt>
```

Only an active Agent Console operator with `message:write` and access to the
stored conversation `brand_id` may connect. `admin_key` query parameters,
global admin-key authentication, trusted-origin bypasses, and caller-supplied
agent identifiers are not accepted for this channel. The server selects only
the non-secret `widget-session` or `bearer` protocol during the upgrade, so a
JWT is never echoed back.

## Durable knowledge uploads

`POST /api/v1/knowledge/upload` and
`POST /api/v1/knowledge/bulk-upload` now use the same Mongo-backed v2 worker
protocol as `/api/v1/ingest/documents`.

- Source bytes and structured context (folder path, product/dealer metadata)
  are encrypted separately in `system.ingestion_payloads`.
- The queued job keeps opaque payload references, a source/context hash
  manifest, immutable brand scope, and only bounded public job metadata.
- Both agent-scoped and workspace/brand-scoped knowledge are supported. An
  agent-scoped submission snapshots the agent's chunking configuration; a
  workspace submission uses the server defaults.
- Bulk product uploads retain variants, group IDs, SKU provenance, price-unit,
  and inventory fields rather than converting them into generic text only.
- `Idempotency-Key` is supported on both endpoints. Matching retries return
  the original job; a different source/context under the same tenant scope
  returns `409 Conflict`.

The public upload response is `pending` after the durable write completes.
Poll `GET /api/v1/knowledge/jobs/{job_id}` until `completed` before treating
the source as searchable.

## Upload and archive limits

| Setting | Default | Applies to |
| --- | ---: | --- |
| `MAX_FILE_SIZE_MB` | 10 | Every uploaded source and serialized bulk payload |
| `MAX_UPLOAD_FILES` | 20 | `/api/v1/ingest/documents` file count |
| `MAX_UPLOAD_TOTAL_SIZE_MB` | 50 | `/api/v1/ingest/documents` aggregate bytes |
| `MAX_ARCHIVE_FILES` | 5000 | Entries in a DOCX ZIP container |
| `MAX_ARCHIVE_UNCOMPRESSED_SIZE_MB` | 100 | DOCX uncompressed expansion |
| `MAX_ARCHIVE_COMPRESSION_RATIO` | 100 | DOCX ZIP expansion ratio |

ZIP uploads are not an accepted source type. DOCX is validated as a ZIP
container before extraction so a compressed document cannot exhaust worker
memory or CPU.

## Qdrant containment and resource limits

The Compose Qdrant service no longer publishes port `6333` to the host. It is
reachable only on the Compose network and requires `QDRANT_API_KEY` through
`QDRANT__SERVICE__API_KEY`. The API client already sends this key via
`QDRANT_API_KEY`.

Production startup rejects a Qdrant deployment without an API key, a Qdrant
URL pointing at loopback, or a fail-open rate-limit configuration. Compose
declares CPU and memory limits for API, worker, frontend, Shopify, MongoDB,
Redis, and Qdrant; production orchestrators must enforce equivalent or
stricter limits.
