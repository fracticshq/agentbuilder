# P2 production hardening contract

P2 hardens the control plane and final-answer path without changing public
request schemas. Deploy the API changes with the CI security gates enabled.

## Durable ingestion job status

`POST /api/v1/ingest/documents?agent_id=...` creates a job whose progress and
creation-time ownership are stored in the system MongoDB database. Redis is a
best-effort cache, not the authoritative record. Consequently,
`GET /api/v1/ingest/status/{job_id}` and `DELETE /api/v1/ingest/jobs/{job_id}`
continue to work when handled by a different API instance or after an API
restart.

The stored `brand_id` and `agent_id` are immutable. Access is checked against
the job's original brand, so moving an agent between brands cannot transfer
visibility of an existing job. Historical jobs without scope remain hidden from
tenant operators.

Job records are retained for 24 hours and status errors are generic, such as
`Document embedding failed`; provider URLs, credentials, and raw backend errors
are not returned to dashboard clients.

P3 completed the executor boundary: `ingestion-worker` claims queued jobs from
Mongo with leases/fencing, retries safely after interruption, and publishes
through deterministic upserts. FastAPI request handlers do not run embedding
work in `BackgroundTasks`; see the [P3 durable-ingestion contract](P3_DURABLE_INGESTION.md).

## Tenant control-plane rules

- Knowledge endpoints accepting both `brand_id` and `agent_id` resolve the
  agent's canonical brand before service work. A mismatched agent returns `404`.
- Shopify, Firecrawl, and manual catalog sync jobs persist canonical `brand_id`
  before their worker is scheduled. Immediate job polling is therefore
  tenant-safe, including when a caller uses a brand slug alias.
- Catalog job responses redact provider/network error text.

## Claim-evidence safety

Before a generated response is persisted or sent through HTTP/SSE, the API
checks every factual claim against usable retrieved text or structured, validated
tool data. Citation identifiers alone do not qualify as evidence. Number,
price, date, SKU, URL, availability, and entity anchors must be present in the
supporting material, with meaningful lexical overlap.

The validator permits greetings, questions, empathy, clarification requests,
and server-authored safety templates without retrieval. It removes private
source/evidence annotations before delivery. Unsupported generated claims are
replaced by a deterministic safe abstention. Commerce product cards remain
usable when their structured product data supports the answer, even though
commerce citations are deliberately suppressed. Lal Kitab keeps its established
missing-chart abstention; a valid chart with an unsupported interpretation or
remedy receives a distinct verification abstention.

Clients do not receive evidence ledgers, provider payloads, or internal source
IDs. Safe validation counts/reason codes are retained only in internal response
and observability metadata.

## Release verification

1. Create an ingestion job, restart or route the status request to a second API
   instance, and verify the same job status remains readable by its owning brand.
2. Attempt ingestion-status, catalog-job, and knowledge-agent access across two
   brands; expect `404` and no worker/service invocation.
3. Return a generated warranty/price/remedy claim with mismatched tool evidence;
   expect safe abstention in both sync and streaming responses, with no private
   evidence annotation or provider details.
4. Return a supported commerce price/stock claim and verify the answer/cards
   remain available without public citations.
5. Require the `Dependency vulnerabilities` and `SAST (Semgrep)` CI checks in
   branch protection. Follow [CI security gates](../CI_SECURITY_GATES.md) for
   scope, thresholds, and exception policy.
