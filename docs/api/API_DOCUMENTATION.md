# Agent Builder API reference

This is the integration contract for the production API. The generated OpenAPI
schema at `GET /openapi.json` (and Swagger UI at `GET /docs`) is the endpoint
and field-level source of truth for the deployed build. The committed
[OpenAPI 3.1 snapshot](./openapi.json) and generated
[Postman collection](./Agent_Builder_Platform.postman_collection.json) are
regenerated from FastAPI and freshness-checked in CI. Do not edit either file
by hand.

Base URL: `https://<api-host>`

To intentionally change the public HTTP contract, update the route/schema,
then run from the repository root:

```bash
python scripts/generate_openapi.py
python scripts/generate_postman_collection.py
```

The WebSocket protocols remain documented here and in the P4 contract because
OpenAPI does not model WebSocket upgrades.

## Authentication and tenant scope

There are three distinct trust boundaries:

| Caller | Credential | Permitted surface |
| --- | --- | --- |
| Dashboard operator | `Authorization: Bearer <JWT>` | `/api/v1/admin/*`, knowledge and ingestion operations, activity reads |
| Programmatic tenant client | `Authorization: Bearer <JWT>` or `X-API-Key` where an endpoint advertises it | Catalog import and sync only, within the key owner's brand scope |
| Public widget | Server-issued `X-Widget-Session` token | Widget messages, catalog hydration, and activity event writes |

`X-Admin-Key` is a development-only compatibility path. It is rejected in
production regardless of its value. Do not use it in new integrations.

Every operator route resolves the target resource's `brand_id` and checks both
the caller's permission and brand assignment. A scoped caller receives `404`
for another tenant's resource. Global configuration requires a system-admin
role.

## Widget session contract

1. Start or resume a session with `POST /api/v1/messages/session` and an
   `agent_id` body field.
2. Store the returned `session_token` only in the widget's session state.
3. Send it as `X-Widget-Session` on subsequent message, history, public catalog
   hydration, and activity requests.

The server derives the agent, conversation, user, and actor IDs from that
signed token. Client-supplied values for those fields are not authoritative.

Human-takeover control uses two separate WebSockets and never puts either
credential in a URL query string:

| WebSocket | Required subprotocol pair | Server authorization |
| --- | --- | --- |
| `/api/v1/messages/ws/widget/{conversation_id}` | `widget-session`, `<widget-session-jwt>` | The signed token's conversation/user/agent must match the immutable server-side conversation scope. |
| `/api/v1/messages/ws/admin/{conversation_id}` | `bearer`, `<dashboard-access-jwt>` | The operator must be active, have `message:write`, have Agent Console access, and belong to the stored conversation brand. |

The old `control_secret`, `agent_id`, and `admin_key` query parameters are not
accepted for these channels. The server returns only the non-secret protocol
name in its WebSocket upgrade response.

### Activity events

`POST /api/v1/activity/events` and
`POST /api/v1/activity/events/batch` require `X-Widget-Session`. All events in
a batch must name the same agent. Widget clients may only use `user` or
`agent` as `actor_type`; the server binds the remaining identities.

Activity reads require a dashboard JWT with `message:read` permission and
access to the requested agent's brand:

- `GET /api/v1/activity/conversations/{conversation_id}/events?agent_id=...`
- `GET /api/v1/activity/conversations/{conversation_id}/timeline?agent_id=...`
- `GET /api/v1/activity/users/{user_id}/sessions?agent_id=...`
- `GET /api/v1/activity/analytics?agent_id=...`

## Knowledge and ingestion

All knowledge and ingestion operations are dashboard-only and tenant-scoped.
The permission required matches the operation: `document:read`,
`document:write`, or `document:delete`.

| Endpoint | Required scope / change |
| --- | --- |
| `POST /api/v1/knowledge/upload` | Multipart form must include the target `brand_id`; `agent_id` is optional. The route persists encrypted source/context payloads and a durable job before returning `pending`. |
| `POST /api/v1/knowledge/bulk-upload` | Body contains `brand_id`, optional `agent_id` and `folder_path`; it preserves structured product/dealer fields through the durable worker and returns `pending`. |
| `GET /api/v1/knowledge/jobs/{job_id}` | The job is authorized through its immutable creation-time brand scope. Poll until `completed` before treating the data as searchable. |
| `POST /api/v1/knowledge/documents/{doc_id}/reindex` | Requires `brand_id`, optional `agent_id`, `document:write`, and accepts `Idempotency-Key`. Queues a durable in-place embedding/vector refresh without re-uploading source bytes or duplicating the logical document. |
| `GET /api/v1/knowledge/tree`, document preview/list/delete, folder CRUD, and retrieval preview | Include `brand_id`; cross-tenant access is rejected. |
| `POST /api/v1/ingest/documents?agent_id=...` | `agent_id` is required and controls the only permitted storage destination. Clients should send `Idempotency-Key` when retrying an upload; same key plus different source returns `409`. |
| `POST /api/v1/ingest/chunks` | Body must include `agent_id`. User metadata cannot choose the destination tenant. |
| `GET /api/v1/ingest/status/{job_id}` and `DELETE /api/v1/ingest/jobs/{job_id}` | The job is authorized through its immutable creation-time brand scope. Legacy unscoped jobs are not exposed. |
| `GET /api/v1/ingest/documents?agent_id=...` | `agent_id` is required. |

`POST /api/v1/ingest/documents` returns `pending` only after encrypted source
payloads and an immutable, Mongo-backed job have been persisted. A separate
worker performs staging and deterministic publish retries. Clients must not
treat `pending` or `processing` as proof that searchable content exists; poll
until `completed`, `error`, or `cancelled`.

All three durable upload routes accept `Idempotency-Key`; repeating a matching
submission returns the original job, while divergent source bytes or structured
context under that key return `409 Conflict`. Upload limits are enforced before
the encrypted payload is stored: `MAX_FILE_SIZE_MB` per source,
`MAX_UPLOAD_FILES` and `MAX_UPLOAD_TOTAL_SIZE_MB` for multi-file ingestion,
and bounded DOCX ZIP entry, expansion-size, and compression-ratio limits.
The re-index route has the same idempotency behavior for its document target;
it refreshes existing vectors only. Re-upload a changed document when its text,
structured product data, or chunking configuration must change.

## Commerce catalog and Shopify

Catalog import, sync configuration, and sync routes require a JWT or API key
whose owner has access to the target `brand_id`. The API rejects private,
loopback, link-local, and otherwise non-public JSON-feed destinations, including
unsafe redirects. Production Shopify sync requires a canonical HTTPS
`<shop>.myshopify.com` host and Admin API token; credentialed redirects are
refused. Each brand can have one active Mongo-leased full snapshot, so an
overlapping trigger returns the existing job with `deduplicated: true`.

`POST /api/v1/catalog/shopify/webhooks` is Shopify-signed, not dashboard or
API-key authenticated. It validates the raw-body HMAC, resolves the canonical
shop to one enabled brand, and queues product lifecycle work. The Shopify MCP
bridge verifies then forwards raw signed events to this API endpoint; it never
acknowledges a webhook without a configured forward target. See the
[P5 Shopify lifecycle contract](./P5_SHOPIFY_OPERATIONS.md) for the topic,
retry, uninstall, and polling behavior.

The Shopify MCP bridge is an internal service, not a public client API:

- API → MCP requests send `Authorization: Bearer <MCP_SERVICE_AUTH_TOKEN>`.
- The bridge rejects `/mcp` requests without that token, except when both
  `NODE_ENV=development` and `SHOPIFY_MCP_ALLOW_INSECURE_LOCAL_DEV=true` are
  explicitly set.
- Deployments must set the identical `MCP_SERVICE_AUTH_TOKEN` for the API and
  Shopify MCP service. It is never returned by an API response.

## Administrative routes

- Brand, agent, manifest, connector, observability, and agent-API-key actions
  require a dashboard JWT and operate only within the user's assigned brands.
- Manifest import requires an explicit `brand_id` for non-global operators;
  a portable manifest never grants tenant selection authority.
- Observability summary calls from a tenant operator must provide either an
  `agent_id` or `brand_slug` in that operator's scope.
- Runtime settings and Azure deployment discovery are system-admin operations.

## Lal Kitab safety behavior

For Lal Kitab agents, a failed, empty, malformed, or incomplete chart/required
secondary response produces a deterministic safe abstention. The response has
`validation=false` and `confidence=0.0`; it does not synthesize a prediction or
remedy from unverified input. Public activity metadata omits birth data,
precise location, provider endpoints, and provider diagnostic errors.

## Retrieval, citations, and generation failures (P1)

Message responses and stream terminal metadata may include a safe
`retrieval` object. Its `status` tells clients whether the answer had usable
grounding; it is not a provider-health diagnostic:

| Status | Meaning | Client behavior |
| --- | --- | --- |
| `evidence` | One or more grounded chunks were retrieved. | Render the answer and its citations. |
| `no_evidence` | The available retrieval backends completed successfully but found no applicable chunks. | Treat this as a valid no-match result; do not claim a backend outage. |
| `degraded` | At least one backend was unavailable, while another completed. | Results may be usable; show citations when supplied and offer retry where grounding is important. |
| `error` | No retrieval backend completed successfully. | Treat as retryable unavailability; do not present an ungrounded factual answer as evidence-backed. |

The metadata may also contain bounded `successful_backends` and
`failed_backends` lists and a stable, non-sensitive `reason`. It never exposes
provider credentials, raw exception text, or infrastructure addresses.

Responses may include `citations`, each with the safe shape
`{doc_id, title, url, snippet, confidence}`. URLs are limited to HTTP(S),
citations are deduplicated and bounded, and snippets are abbreviated. Clients
must tolerate a response without citations, especially for `no_evidence` or
commerce-only results.

For a terminal LLM generation failure, the streaming endpoint emits one
terminal `error` event rather than a successful `final_answer`/`done` sequence:

```json
{
  "type": "error",
  "content": "I’m sorry, I couldn’t generate a response right now. Please try again.",
  "metadata": {"code": "generation_failed", "retryable": true}
}
```

Treat it as retryable and do not display any provider-supplied failure detail.

### Runtime settings and Azure deployment discovery

Runtime settings use environment defaults only when the settings persistence
layer is unavailable. Invalid or unexpected persistence data is an error rather
than a silent fallback. Azure deployment discovery requires its configured ARM
settings; missing ARM configuration returns `503 Service Unavailable` instead
of a synthetic successful deployment list.

## Production configuration required by this contract

Production API startup requires, at minimum, `SECRET_KEY`, `ADMIN_API_KEY`,
`SETTINGS_ENCRYPTION_KEY`, `PII_ENCRYPTION_KEY`, `MONGODB_URI`, `REDIS_URL`,
and `MCP_SERVICE_AUTH_TOKEN`. `RATE_LIMIT_FAIL_CLOSED` must be true. When
`VECTOR_BACKEND=qdrant`, `QDRANT_API_KEY` is required and `QDRANT_URL` must
not point at loopback. The Shopify MCP service additionally requires
`SESSION_SECRET`, `REDIS_URL`, and the same `MCP_SERVICE_AUTH_TOKEN`.
Durable uploads additionally require a private ClamAV-compatible scanner
(`MALWARE_SCAN_MODE=clamav`) in production; an infected source is rejected and
an unavailable scanner causes a retryable `503`, never an unscanned upload.

See [P0 security migration](./P0_SECURITY_MIGRATION.md) for rollout order,
client-impact checklist, and operational verification, and the
[P1 reliability contract](./P1_RELIABILITY_CONTRACT.md) for client migration
and deployment checks. See the [P2 production hardening contract](./P2_PRODUCTION_HARDENING.md)
for tenant-control-plane and evidence-validation behavior, and the
[P3 durable-ingestion contract](./P3_DURABLE_INGESTION.md) for queue, retry,
worker, and source-payload behavior, and the [P4 edge and knowledge
hardening contract](./P4_EDGE_AND_KNOWLEDGE_HARDENING.md) for WebSocket,
rate-limit, Qdrant, and legacy knowledge-upload requirements.
See the [P5 Shopify lifecycle and release-evidence contract](./P5_SHOPIFY_OPERATIONS.md)
for durable catalog sync, webhook, SBOM, and operational requirements.
See the [P6 canonical source and API-contract contract](./P6_CANONICAL_SOURCE_AND_API_CONTRACT.md)
for shared-package ownership and generated API artefacts.
