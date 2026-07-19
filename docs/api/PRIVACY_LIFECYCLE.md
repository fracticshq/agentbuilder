# Privacy lifecycle API contract (v1)

This contract covers first-party widget conversation data. A data subject is
identified only through a server-issued widget session; client-supplied agent,
brand, user, and conversation IDs are never authorization inputs.

## Data stores in scope

The service exports, retains, and deletes these first-party brand-database
collections:

- `conversations` and `short_term_summaries`
- `episodic_memory` (long-term facts)
- `activity_events`
- `observability_events`

It also revokes the corresponding Mongo conversation scope and Redis takeover
state. Scope records are tombstoned without the raw `user_id`, so a still-valid
widget token cannot resume an erased conversation.

The legacy Strapi conversation mirror is an external processor. Its existing
dashboard-sync endpoints are not a privacy protocol and are never used for
export or deletion. Every first-party deletion creates (or reuses) an opaque,
tenant-scoped operation in the system-DB `strapi_privacy_requests` outbox before
the API reports its local receipt. That row contains no raw subject ID,
conversation ID, content, token, or dashboard-sync credential.

`STRAPI_PRIVACY_MODE` is explicit and defaults to `contract_pending`; it is
never inferred from `STRAPI_URL` or `STRAPI_API_TOKEN`.

- `contract_pending` (the default) persists/reuses the operation with state
  `pending_contract` and performs no network I/O.
- `active` permits the separate privacy worker to send the canonical signed
  request described below. It requires a dedicated endpoint, request key, and
  pinned receipt public key at configuration validation time.
- `disabled` still records the operation as `disabled` so the API cannot claim
  an external erasure that was never verified.

In every non-receipted state, the deletion response is `202`; no Strapi URL or
successful HTTP status alone can turn it into a completed erasure.

## Widget consent

`PUT /api/v1/messages/privacy/consent`

Authentication: `X-Widget-Session: <signed token>`.

```json
{
  "long_term_memory_consent": true,
  "policy_version": "privacy-v1"
}
```

Consent is session-bound and controls only episodic/long-term memory. It does
not disable the short-term conversation needed to operate the widget. Until
explicit consent is `true`, long-term fact retrieval and extraction fail closed.
Withdrawing consent deletes and re-queries `episodic_memory` for that subject
before returning success.

```json
{
  "schema_version": "v1",
  "long_term_memory_consent": "withdrawn",
  "withdrawal": {"deleted": 3, "verified": true}
}
```

## Subject export

`GET /api/v1/messages/privacy/export`

Authentication: `X-Widget-Session: <signed token>`. Response header:
`Cache-Control: no-store`.

The response is a portable JSON document:

```json
{
  "schema_version": "v1",
  "generated_at": "2026-07-19T00:00:00Z",
  "subject": {"id": "user_…", "conversation_ids": ["conv_…"]},
  "data": {
    "conversations": [],
    "summaries": [],
    "episodic_facts": [],
    "activity_events": [],
    "observability_events": []
  },
  "external_processors": [
    {"name": "strapi", "status": "pending_contract"}
  ]
}
```

The platform caps each exported collection at `PRIVACY_EXPORT_MAX_RECORDS`
(default `10000`). Larger exports require an asynchronous, signed delivery
workflow before production use; do not silently paginate a subject export.

## Subject deletion and verification

`DELETE /api/v1/messages/privacy`

Authentication: `X-Widget-Session: <signed token>`. Response header:
`Cache-Control: no-store`.

The endpoint deletes all known first-party subject data within the immutable
brand scope, re-queries every store, revokes live control channels, then creates
or reuses the durable Strapi external operation before it records an audit
receipt. The operation uses a dedicated `STRAPI_PRIVACY_SUBJECT_HMAC_KEY` to
derive a domain-separated HMAC subject reference bound to the brand; it does
not reuse `SECRET_KEY`.

```json
{
  "id": "privacy_…",
  "schema_version": "v1",
  "status": "pending",
  "deleted": {"conversations": 4, "episodic_facts": 1},
  "verified": {"conversations": true, "episodic_facts": true},
  "tombstoned_sessions": 1,
  "external_processors": [{
    "name": "strapi",
    "status": "pending_contract",
    "request_id": "strapi_privacy_…",
    "receipt_verified": false
  }],
  "requested_at": "2026-07-19T00:00:00Z"
}
```

`200` means every first-party store verified zero matching records **and** the
same durable Strapi operation carries a locally verified, correlated, signed
external receipt. `202` means local deletion was verified but the external
operation is `pending_contract`, queued, running, failed, or disabled. `503`
means the operation could not be verified or its durable evidence could not be
recorded; callers must not treat it as complete.

## Operator lifecycle controls

All operator routes require dashboard authentication, a dedicated privacy
permission, and creation-time brand scope:

| Route | Permission |
| --- | --- |
| `GET /api/v1/admin/brands/{brand_id}/privacy/retention` | `privacy:read` |
| `PUT /api/v1/admin/brands/{brand_id}/privacy/retention` | `privacy:write` |
| `POST /api/v1/admin/brands/{brand_id}/privacy/retention/run` | `privacy:write` |
| `GET /api/v1/admin/brands/{brand_id}/privacy/subjects/{subject_id}/export` | `privacy:read` |
| `DELETE /api/v1/admin/brands/{brand_id}/privacy/subjects/{subject_id}` | `privacy:delete` |

Retention is configured per brand, from 1 to 3650 days. The
`privacy-retention-worker` applies the policy periodically
(`PRIVACY_RETENTION_POLL_SECONDS`, default hourly) to the first-party stores
above. Its manual `run` counterpart is for audited recovery and validation.

## Strapi deletion contract and remote prerequisites

This repository implements only the local caller, outbox, and verifier. It
does **not** claim that a remote Strapi route, subject mapping, or data erasure
implementation exists. The legacy `/api/session-save` and `/api/chat-save`
mirror paths remain unmapped to privacy subjects and cannot be retroactively
treated as deletion coverage.

Before setting `STRAPI_PRIVACY_MODE=active`, the remote Strapi deployment must
provide all of the following:

1. `POST /api/privacy/deletions` on the dedicated HTTPS
   `STRAPI_PRIVACY_URL`, with no redirect and no reliance on the dashboard
   bearer token;
2. a durable tenant-and-subject mapping for the opaque `tenant_id` and
   `subject_reference`, including all mirrored data that can be deleted;
3. idempotent processing keyed by the immutable `request_id` and
   `idempotency_key`, plus remote deletion and independent zero-record
   verification; and
4. an Ed25519 signing key whose pinned public key is configured locally as
   `STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY`.

The client sends compact UTF-8 JSON with sorted object keys and no whitespace:

```json
{
  "idempotency_key": "spid_…",
  "request_id": "strapi_privacy_…",
  "schema_version": "strapi-privacy-request-v1",
  "subject_reference": "<64 lowercase hex characters>",
  "tenant_id": "brand_…"
}
```

It signs the following UTF-8, newline-delimited canonical material with
HMAC-SHA-256 using `STRAPI_PRIVACY_REQUEST_SIGNING_KEY`:

```text
strapi-privacy-request-v1
POST
/api/privacy/deletions
<X-Strapi-Privacy-Timestamp>
<request_id>
<idempotency_key>
<sha256 of canonical request JSON>
```

The request includes `X-Strapi-Privacy-Schema`,
`X-Strapi-Privacy-Key-Id`, `X-Strapi-Privacy-Request-Id`,
`X-Strapi-Privacy-Idempotency-Key`, `X-Strapi-Privacy-Timestamp`, and the hex
`X-Strapi-Privacy-Signature`. The Strapi side must check freshness, key ID,
signature, request/body correlation, and replay/idempotency before erasing.

A successful HTTP response is insufficient. The response must be an exact
JSON object with these signed fields plus base64 `signature`:

```json
{
  "schema_version": "strapi-privacy-receipt-v1",
  "receipt_id": "remote-receipt-id",
  "request_id": "strapi_privacy_…",
  "idempotency_key": "spid_…",
  "tenant_id": "brand_…",
  "subject_reference": "<64 lowercase hex characters>",
  "status": "completed",
  "deletion_verified": true,
  "completed_at": "2026-07-20T00:00:00Z",
  "signature": "<base64 Ed25519 signature>"
}
```

`signature` is an Ed25519 signature over the canonical compact/sorted JSON of
all fields above except `signature`. The client rejects absent, malformed,
extra, unsigned, invalid, or request/tenant/subject-mismatched receipts. Only
the verified receipt summary and signature fingerprint are stored locally.

Required local configuration:

```text
STRAPI_PRIVACY_MODE=active
STRAPI_PRIVACY_SUBJECT_HMAC_KEY=<unique 32+ character secret>
STRAPI_PRIVACY_URL=https://strapi.example.com
STRAPI_PRIVACY_REQUEST_SIGNING_KEY=<unique 32+ character secret>
STRAPI_PRIVACY_REQUEST_KEY_ID=<remote-recognized-key-id>
STRAPI_PRIVACY_RECEIPT_PUBLIC_KEY=<PEM or base64 raw Ed25519 public key>
```

The `strapi-privacy-worker` Compose service is safe to run while
`contract_pending`: it does not construct a network client or claim requests.
Use `active` only after the remote prerequisite checklist is demonstrably
complete.

### Key rotation

Keep `STRAPI_PRIVACY_SUBJECT_HMAC_KEY` independent from `SECRET_KEY` and from
the request-signing secret. Rotating it changes the deterministic subject and
idempotency references; with the current single-key local protocol, do not
rotate it while an operation is outstanding unless a migration preserves and
continues processing the existing durable rows. Coordinate request-key rotation
through `STRAPI_PRIVACY_REQUEST_KEY_ID`: the remote service should accept old
and new keys during rollout. Rotate the receipt signing key only after the
remote and local pinned public key transition has a plan for all in-flight
requests; a receipt signed by an unpinned key is intentionally rejected and
remains pending.
