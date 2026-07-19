# Mongo and worker recovery runbook

Use this runbook for a staging drill and for production incidents involving
MongoDB, ingestion workers, catalog-sync workers, or Redis-backed rate limits.
Never run the fault-injection steps against a tenant without an approved
maintenance window.

## Signals and ownership

Page the on-call service owner when `/ready` is non-200, MongoDB or Redis is
unhealthy, a catalog-sync job reaches `error`, or a durable job remains queued
or running beyond its tenant service objective. Capture the deployment digest,
time window, affected brand IDs, worker revision, and Mongo/Redis status before
changing anything.

The API `/ready` endpoint is the customer-impact signal. The authenticated
status endpoint and Mongo job collections are operator diagnostics; do not
expose their tenant or queue data publicly.

## Safe recovery sequence

1. Stop new deployments and record the current Container App revision/image
   digest. Preserve the release evidence artifact.
2. Check MongoDB reachability, replica-set/Atlas state, connection saturation,
   storage capacity, and the system database. Do not delete job or payload
   documents to clear a queue.
3. Check Redis reachability. With `RATE_LIMIT_FAIL_CLOSED=true` and
   `REQUIRE_REDIS=true`, the API should become unready and reject rate-limited
   work while Redis is unavailable. It must never silently allow unthrottled
   traffic.
4. Restore the dependency first. Confirm `/ready` reports both MongoDB and
   Redis as `healthy` before restarting application workers.
5. Restart one ingestion worker. Its Mongo lease protocol should reclaim only
   expired work; do not scale multiple workers until the first worker is
   healthy. Repeat for the catalog-sync worker.
6. Inspect terminal errors and retry eligibility. Cancel only the intended job
   through its authorized API; cancellation after publish begins may be
   intentionally rejected to preserve atomic publication.
7. If the deployed revision is the suspected cause, roll back every affected
   service to the prior **signed image digest**, then rerun the smoke gate.

## Staging drill acceptance

For a non-production test brand, record each result:

1. Submit an idempotent document upload, interrupt its worker after it is
   leased, then start a replacement worker. Verify exactly one terminal publish
   and no duplicate vectors/chunks.
2. Submit an idempotent Shopify lifecycle job, interrupt the catalog worker,
   then verify lease expiry/reclaim and replay safety.
3. Make Redis unavailable. Verify `/ready` returns `503` and a rate-limited
   request is rejected; restore Redis and verify readiness returns healthy.
4. Make Mongo unavailable. Verify `/ready` returns `503`, new durable writes do
   not report success, and no source payload is orphaned after recovery.
5. Deploy a known-good prior image digest and run
   `scripts/smoke_production.py` against the restored services.

Attach timestamps, logs with secrets redacted, job IDs, revision/digest pairs,
and the smoke report to the drill record. Any duplicate publish, false success,
unscoped job exposure, or fail-open rate limit blocks GA promotion until fixed.
