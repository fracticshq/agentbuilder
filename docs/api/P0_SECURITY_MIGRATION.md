# P0 security migration and release checklist

This release changes security contracts. Deploy the API, widget, and Shopify
MCP together; a partial deployment can cause rejected requests rather than a
security downgrade.

## Pre-deploy

1. Generate a high-entropy `MCP_SERVICE_AUTH_TOKEN` and place the same value in
   the API and Shopify MCP secret stores. Do not set it in client-side build
   variables.
2. Ensure `SESSION_SECRET`, `SECRET_KEY`, `SETTINGS_ENCRYPTION_KEY`, and
   `PII_ENCRYPTION_KEY` are distinct, non-placeholder secrets. Set `PII_KEY_ID`
   and `PII_KEY_VERSION` if key rotation is managed externally.
3. Give each dashboard operator the smallest viable role and explicit
   `brands` assignment. Validate that a `brand_admin` cannot read or modify a
   second brand.
4. Re-encrypt legacy PII envelopes that lack salt/key-version metadata. They
   are intentionally rejected rather than decrypted with an unsafe fallback.
5. Locate ingestion jobs created without an `agent_id`. They are intentionally
   hidden by the new tenant-safe status routes; use an audited admin migration
   to attach their true owner before exposing them.

## Client changes

| Client | Required action |
| --- | --- |
| Widget | Call `POST /api/v1/messages/session` before sending messages; include `X-Widget-Session` for message, history, public catalog, and activity requests. Update activity calls to tolerate `401` by refreshing the session. |
| Admin dashboard | Send a dashboard JWT, select a scoped brand/agent for all knowledge, ingestion, activity, manifest, catalog, and observability operations. Do not use `X-Admin-Key` in production. |
| Ingestion clients | Supply `agent_id` on all document and manual-chunk requests. Poll status and treat `error` as terminal; no zero-vector or synthetic-success fallback exists. |
| Catalog clients | Use a tenant-scoped JWT/API key. Register only public JSON feeds and canonical `*.myshopify.com` Shopify hosts. |
| Shopify MCP caller | Send `Authorization: Bearer <MCP_SERVICE_AUTH_TOKEN>` for every `/mcp` request. |
| Lal Kitab UI | Render the safe-abstention state without treating it as a prediction. Do not expect birth location, provider URL, or provider error fields in public activity metadata. |

## Deployment verification

Run these checks in staging after secrets are mounted:

1. Start the API with `ENVIRONMENT=production`; it must fail if an expected
   secret is absent or a production admin-key bypass is attempted.
2. Call Shopify MCP `/health`, then call `/mcp` without the service token
   (expect `401`) and with the token (expect JSON-RPC readiness).
3. As a brand administrator for brand A, attempt knowledge/activity/catalog
   access for brand B (expect `404` or `403` per endpoint), then repeat for
   brand A (expect success).
4. Upload a small document and verify its job reaches `completed`; disable the
   embedding provider in a test environment and verify the job reaches `error`
   without a stored vector.
5. Start a widget session, send an activity event with forged user/conversation
   IDs, and verify the stored event has the server-issued identities instead.
6. Exercise a Lal Kitab request with an unavailable chart provider and verify
   deterministic abstention, `validation=false`, and `confidence=0.0`.

## Rollback boundary

Do not roll back only the API after the widget has begun sending signed-session
headers, or only the API after Shopify MCP begins requiring the service token.
If a rollback is required, roll back the API, widget, and Shopify MCP as one
compatibility unit and rotate the MCP secret if it was exposed during incident
handling.

## Remaining work after P0

- Migrate legacy PII envelopes and unscoped ingestion jobs.
- Replace response filtering as the only prompt-injection defense with
  structured tool outputs, source attribution, and claim-level grounding.
- Add dependency/SAST scanning and tenant-isolation integration tests to the
  CI gates introduced in P1.
- Implement durable cross-instance job progress and claim-level evidence
  validation as the next production wave.
