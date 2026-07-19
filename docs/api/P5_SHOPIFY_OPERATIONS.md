# P5 Shopify lifecycle and release-evidence contract

P5 makes Shopify catalog state restart-safe and operationally observable. It
applies only to the commerce/catalog integration; the normalized product,
variant, `price_minor`, currency, image, and provenance fields remain the
existing canonical commerce contract.

## Catalog sync lifecycle

`POST /api/v1/catalog/import/shopify` and `POST /api/v1/catalog/sync/{brand_id}`
now create a Mongo-backed catalog job. The API returns only after the immutable
brand/source scope and encrypted access-token snapshot are persisted. A
`catalog-sync-worker` claims it with a time-bound Mongo lease and retries a
failed job up to `CATALOG_SYNC_MAX_ATTEMPTS`.

The worker renews its fenced lease while it traverses Admin GraphQL product and
variant cursors. A reclaimed worker cannot renew or complete the job; the
catalog writer's deterministic source-key upserts make the replay safe.

The worker preserves the existing product upsert semantics and marks products
absent from a successful full snapshot inactive. A brand has only one active
full Shopify snapshot: overlapping manual or webhook syncs return its existing
`job_id` with `deduplicated: true` rather than running concurrent snapshots.
When `catalog_sync.auto_sync=true`, the worker also evaluates `daily` and
`weekly` `sync_frequency` values every `CATALOG_SYNC_SCHEDULER_POLL_SECONDS` and
queues a due snapshot through that same coalescing key. `manual` never schedules
work on its own.

Production Shopify sync requirements:

- An Admin API token with `read_products` and `read_inventory`, and a canonical
  HTTPS `<shop>.myshopify.com` host, are required. Public/custom-domain import
  is no longer a production sync path.
- The platform refuses to associate the same canonical Shopify shop with two
  brands.
- The access token is stored encrypted in the brand configuration and is
  snapshotted encrypted in the queued job. It is never in an API response or
  legacy catalog progress row.
- `SHOPIFY_ADMIN_API_VERSION` defaults to `2026-04`; set it deliberately during
  Shopify version upgrades and verify the sync regression suite before changing
  it.
- The worker reads only the Admin GraphQL endpoint
  `/admin/api/<version>/graphql.json`; REST `shop.json` and `products.json`
  are not a production catalog-sync path. GraphQL `200` responses containing
  `errors`, malformed cursor pages, and missing inventory access fail the
  snapshot before stale products can be deactivated.
- GraphQL IDs are adapted to Shopify `legacyResourceId` values before the
  canonical writer. This preserves numeric product/variant source keys and
  delete-webhook matching across the REST-to-GraphQL migration. Product and
  variant cursors are fully exhausted before a snapshot is published; throttled
  requests use bounded retry and a partial snapshot is never published.

### Job polling

Poll `GET /api/v1/catalog/jobs/{job_id}?brand_id=<brand-id>`. The caller must
have catalog-manager access to that brand. Terminal states are `completed`,
`error`, and `cancelled`; failed provider detail is intentionally not returned.
`completed` means the catalog writer finished its snapshot, not merely that an
HTTP request was accepted.

## Shopify webhooks

Configure the Shopify app callback to the externally reachable Shopify MCP
bridge `/webhooks`. The bridge verifies `X-Shopify-Hmac-SHA256` over the raw
body and forwards the unchanged signed payload to:

`POST /api/v1/catalog/shopify/webhooks`

The API verifies the signature a second time, canonicalizes
`X-Shopify-Shop-Domain`, looks up exactly one enabled brand's `shop_domain`,
and persists an idempotent lifecycle job. It returns no tenant information for
unknown or disabled shops.

| Shopify topic | Durable result |
| --- | --- |
| `products/create`, `products/update`, `products/publish`, `products/unpublish`, `inventory_levels/update` | Coalesced full snapshot sync. |
| `products/delete` | Product rows are set `source_active=false`, `in_stock=false`, and `catalog_source.active=false`; audit rows are retained. |
| `app/uninstalled` | Sync is disabled, encrypted token material is removed, then all catalog rows from that Shopify source are deactivated. |

Set these settings before registering a webhook:

```env
SHOPIFY_WEBHOOKS_ENABLED=true
SHOPIFY_WEBHOOK_SECRET=<Shopify app signing secret>
SHOPIFY_WEBHOOK_MAX_BODY_BYTES=1048576
```

`SHOPIFY_WEBHOOK_SECRET` is required at production API startup when webhooks are
enabled. An unavailable queue returns a retryable `503`; do not acknowledge and
discard webhook events.

## Provider capability truthfulness

HubSpot, Salesforce, Zendesk, Slack, Google Sheets, Airtable, Notion, Zapier,
and n8n are not exposed by the Agent Tools API or admin capability UI in this
release. Their old configuration schemas remain internal only to keep existing
encrypted credentials masked during a migration; they are never registered as
runtime tools. Use the separately implemented, tenant-scoped HTTP or MCP
Context Connector path for supported external integrations.

## Operations and alerts

`/metrics` exposes `catalog_sync_jobs_total{action,status}` and
`catalog_sync_job_duration_seconds{action}`. The status service's
`catalog_sync` block reports queued, running, and terminal-failed job counts.
Alert when failed jobs are non-zero for an active commerce tenant, or when jobs
remain queued/running beyond the normal full-sync window.
Detailed `/api/v1/status` and `/api/v1/status/metrics` views require a
platform-admin identity; public health responses intentionally omit queue and
infrastructure detail.

## Release evidence

CI generates a deterministic CycloneDX 1.5 SBOM from each deployed Python and
Node manifest and verifies that CI actions and runtime Docker base images remain
immutably pinned. The release system must attach that generated SBOM to the
release record together with the build commit, image digest, CI run URL, and
approval before deployment. See [CI security gates](../CI_SECURITY_GATES.md).
