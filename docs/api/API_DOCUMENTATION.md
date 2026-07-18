# Agent Builder API reference

This is the integration contract for the production API. The generated OpenAPI
schema at `GET /openapi.json` (and Swagger UI at `GET /docs`) is the endpoint
and field-level source of truth for the deployed build. Regenerate client code
from that schema as part of every release; do not rely on historical examples
or undocumented endpoints.

Base URL: `https://<api-host>`

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
| `POST /api/v1/knowledge/upload` | Multipart form must include the target `brand_id`; the operator must own that brand. |
| `POST /api/v1/knowledge/bulk-upload` | Body contains `brand_id`; the operator must own that brand. |
| `GET /api/v1/knowledge/tree`, document preview/list/delete, folder CRUD, and retrieval preview | Include `brand_id`; cross-tenant access is rejected. |
| `POST /api/v1/ingest/documents?agent_id=...` | `agent_id` is required and controls the only permitted storage destination. |
| `POST /api/v1/ingest/chunks` | Body must include `agent_id`. User metadata cannot choose the destination tenant. |
| `GET /api/v1/ingest/status/{job_id}` and `DELETE /api/v1/ingest/jobs/{job_id}` | The job is authorized through its owning agent. Legacy unscoped jobs are not exposed. |
| `GET /api/v1/ingest/documents?agent_id=...` | `agent_id` is required. |

Ingestion fails closed: an embedding provider failure, malformed/all-zero
vector, or durable-store failure marks the job as an error. Clients must not
treat a `processing` response as proof that searchable content exists; poll the
job status until `completed`.

## Commerce catalog and Shopify

Catalog import, sync configuration, and sync routes require a JWT or API key
whose owner has access to the target `brand_id`. The API rejects private,
loopback, link-local, and otherwise non-public JSON-feed destinations, including
unsafe redirects. Shopify store URLs must be canonical HTTPS
`<shop>.myshopify.com` hosts; credentialed redirects are refused.

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
and `MCP_SERVICE_AUTH_TOKEN`. The Shopify MCP service additionally requires
`SESSION_SECRET`, `REDIS_URL`, and the same `MCP_SERVICE_AUTH_TOKEN`.

See [P0 security migration](./P0_SECURITY_MIGRATION.md) for rollout order,
client-impact checklist, and operational verification, and the
[P1 reliability contract](./P1_RELIABILITY_CONTRACT.md) for client migration
and deployment checks.
