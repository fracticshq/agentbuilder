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

The legacy Strapi conversation mirror is an external processor. It currently
has no authenticated export/delete acknowledgement contract. When configured,
the API reports `pending_contract` and returns HTTP `202`; it never claims a
verified full erasure until that processor implements the contract below.

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
  "external_processors": []
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
brand scope, re-queries every store, revokes live control channels, and records
an audit receipt containing an HMAC subject digest rather than the raw subject
ID.

```json
{
  "id": "privacy_…",
  "schema_version": "v1",
  "status": "completed",
  "deleted": {"conversations": 4, "episodic_facts": 1},
  "verified": {"conversations": true, "episodic_facts": true},
  "tombstoned_sessions": 1,
  "external_processors": [],
  "completed_at": "2026-07-19T00:00:00Z"
}
```

`200` means every first-party store verified zero matching records and no
external processor remains. `202` means local deletion was verified but an
external processor is still pending. `503` means the operation could not be
verified; callers must not treat it as complete.

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

## External processor contract still required

Before declaring privacy lifecycle GA-complete, Strapi (and every future
connector that stores conversation content) must provide:

1. signed `GET /privacy/subjects/{digest}/export` and
   `DELETE /privacy/subjects/{digest}` APIs;
2. an idempotency key and durable request/receipt ID;
3. store-specific deletion counts and independent zero-record verification;
4. no raw content, tokens, or subject IDs in the receipt; and
5. a retention policy acknowledgement tied to the same brand scope.

Until then, integrations must remain visible as `pending_contract` in exports
and deletion receipts.
