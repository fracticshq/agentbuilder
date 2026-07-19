# Staging-quality evaluation evidence contract

## Scope and deployment gate

This API stores only privacy-safe evidence from the repository's offline v2
staging-quality contract. It is not an evaluation runner and must not be used
against production data, customer traffic, or provider endpoints.

All of the following are required before the routes exist at runtime:

1. Set `EVAL_STAGING_ENABLED=true` explicitly. Its default is `false`; the API
   never treats `ENVIRONMENT=staging` as authorization.
2. Set `EVAL_STAGING_TARGET_ALLOWLIST` to the exact protected profile(s), for
   example `synthetic-external-staging`. Every target must be declared by the
   v2 fixture as `synthetic_only` and `read_only`.
3. Set a bounded `EVAL_STAGING_MAX_CASES` and `EVAL_RESULT_TTL_SECONDS`. Mongo
   adds a TTL index on `expires_at`; the first-party privacy retention worker
   also deletes older `quality_evaluation_runs` rows by the brand policy.
4. Issue a distinct, non-default Agent API key bound to exactly one agent and
   one brand, with `evaluations:write` as its only evaluation scope. Treat the
   full key as a secret and inject it through the deployment's approved secret
   manager. Generic dashboard credentials and global admin keys cannot ingest.

Production still rejects report ingestion unless the explicit flag and a
matching allowlisted profile are present. The route does not use a live model,
LLM provider, browser, connector, or network target.

## Ingestion

`POST /api/v1/admin/evaluations/runs` requires `X-Agent-API-Key` (or an
equivalent bearer form) for an agent API key with `evaluations:write`. The key
must carry both `agent_id` and `brand_id`; those are resolved from the server,
and must equal the request body. The server resolves the owning brand's slug
before choosing the Mongo database.

The body contains only:

```json
{
  "agent_id": "agent-opaque-id",
  "brand_id": "brand-opaque-id",
  "target_profile": {
    "profile": "synthetic-external-staging",
    "data_classification": "synthetic_only",
    "access_mode": "read_only"
  },
  "report": {"...": "the exact v2 sanitized summary"}
}
```

The API reloads and validates the checked-in case/review fixtures, then
requires `report` to equal their aggregate-only `sanitized_summary`. It rejects
unknown fields and any raw turns/rationales, customer or conversation IDs,
URLs (including credential-bearing/query URLs), secrets, birth-data fields,
and provider/connector payloads. Results are written only to the brand's
`quality_evaluation_runs` collection with immutable `brand_id`, `brand_slug`,
and `agent_id` ownership.

## Dashboard review

All dashboard responses set `Cache-Control: no-store`.

| Route | Permission | Purpose |
| --- | --- | --- |
| `GET /api/v1/admin/brands/{brand_id}/evaluations/runs` | `evaluation:read` | List only that brand's redacted runs. |
| `GET /api/v1/admin/brands/{brand_id}/evaluations/runs/{run_id}` | `evaluation:read` | Read one run, scoped by brand in its immutable database. |
| `POST /api/v1/admin/brands/{brand_id}/evaluations/runs/{run_id}/reviews` | `evaluation:review` | Append a contract-validated, redacted review. |

Reviews contain dimensions/outcome, a `[redacted] opaque_tag` rationale, and
immutable fixture/rubric/protocol hashes. Human reviewers are primary: their
identity is represented by a server-derived opaque reference, not an email or
display name. A `pinned_model` review is optional declared metadata only; it
requires a preceding human review for the same case and a pinned model hash.
The endpoint never invokes the pinned model and cannot use it to override the
human decision.

## Operational verification

Use the offline test command from the repository root:

```bash
USE_AZURE_KEYVAULT=false python -m pytest -q \
  apps/api/tests/test_staging_evaluation_routes.py \
  apps/api/tests/test_staging_evaluation_store.py \
  apps/api/tests/test_privacy_lifecycle_routes.py \
  apps/api/tests/test_production_hardening_config.py
```

After any route/schema change regenerate the committed API contract:

```bash
python scripts/generate_openapi.py
python scripts/generate_postman_collection.py
```
