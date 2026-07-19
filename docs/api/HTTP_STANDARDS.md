# Shared HTTP standards (v1)

## Errors

Errors use HTTP status plus a stable, safe `detail`. Public routes never return
exception strings, provider diagnostics, credentials, raw documents, or tenant
existence information. `401` means missing/invalid identity; tenant-scope
denials use `404` on dashboard resources; transient authoritative-store or
provider conditions use `503`.

## Pagination

Existing offset endpoints accept bounded `limit` and `offset` and return
`total`. New high-volume APIs should use opaque cursors rather than expose
database IDs. Subject exports intentionally do not paginate: they are
no-store, bounded portability documents and require an asynchronous delivery
contract before exceeding `PRIVACY_EXPORT_MAX_RECORDS`.

## Retries and idempotency

Clients may retry `429`, `502`, `503`, and explicitly retryable terminal
stream errors with exponential backoff and jitter. Do not automatically retry
commerce mutations. Upload, re-index, catalog-sync, webhook, and deletion APIs
that perform durable work require/accept an `Idempotency-Key` where documented;
the key is tenant-scoped and divergent reuse returns `409`.

## Rate limits

`429` responses include `Retry-After`, `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, and `X-RateLimit-Reset` where a HTTP limiter decision
is available. Redis loss fails closed in production; callers must treat a
limiter-unavailable response as a retryable availability condition, not as a
signal to bypass a limit.

## Retention, export, deletion

See [privacy lifecycle](PRIVACY_LIFECYCLE.md). Responses containing a subject
export/deletion receipt include `Cache-Control: no-store`. A `202` deletion is
not verified complete: an external processor still needs its acknowledgement.
