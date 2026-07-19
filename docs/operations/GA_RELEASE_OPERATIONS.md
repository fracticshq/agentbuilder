# GA release and operations contract

This contract is the release gate for an external multi-tenant deployment. It
supplements CI: a passing unit/build/security workflow does not authorize a
production deployment on its own.

## Protected deployment flow

`.github/workflows/release.yml` is manually dispatched for one service at a
time. It is deliberately separate from PR CI and is the only repository-owned
deployment path. It performs these fail-closed steps:

1. GitHub Environment approval selects `staging` or `production`.
2. A GitHub OIDC token logs into Azure; no Azure client secret is stored in
   GitHub.
3. ACR builds the selected service, then the deployment script resolves its
   tag to an OCI `@sha256:` digest before Container Apps receives the image.
4. The deployment script refuses to create an application or substitute a
   missing secret. Existing Container App secret references must already be in
   place.
5. `/live`, `/ready`, `/config-check`, optional frontend runtime configuration,
   and Shopify MCP health must pass through `scripts/smoke_production.py`.
6. A bounded, read-only `/ready` capacity probe must meet its P95/error-rate
   threshold.
7. The workflow keylessly signs each immutable image with Cosign and attaches a
   signed release-evidence predicate containing the commit, SBOM, image digest,
   approver, CI run, smoke report, and capacity result.
8. The SBOM, smoke report, capacity result, and release-evidence record are retained as a
   release artifact for 365 days.

The release workflow intentionally excludes Strapi because that application is
owned and released from `agentbuilder-strapi`. A platform release must record
the compatible Strapi revision separately.

## One-time cloud setup

Before enabling the workflow, configure both GitHub Environments:

| Setting | `staging` | `production` |
| --- | --- | --- |
| Deployment branches | protected integration branch | protected `main` release branch only |
| Required reviewers | service owner | service owner and security/release owner |
| Wait timer | optional | required by the release policy |
| Environment variables | Azure identifiers below | separate production Azure identifiers below |

Set these non-secret Environment variables:

```text
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
AZURE_RESOURCE_GROUP
AZURE_ACR_NAME
AZURE_CONTAINERAPPS_ENV
```

Create an Entra application or user-assigned managed identity with a federated
credential that accepts only this repository's protected
`.github/workflows/release.yml` subject. Grant the minimum Azure roles needed
to build in ACR, read the resolved image digest, update the selected Container
App, read its revision/FQDN, and obtain ACR registry access. Do not grant Owner
or use an Azure client-secret fallback.

Provision each Container App and its secret references before the first
workflow run. At minimum the API and Shopify MCP share one
`MCP_SERVICE_AUTH_TOKEN`; API production also needs the P0/P4 secrets listed in
the API contract. `QDRANT_API_KEY` is a Container App secret, never a plain
environment value. The deployment command uses `--no-create` and
`--use-existing-secrets` to make a missing secret or missing app a release
failure rather than an implicit bootstrap.

Pre-provision the Container Apps with their registry pull identity. A protected
OIDC release does not retrieve an ACR admin password; that credential is only
used by the separate local bootstrap path when it creates a new application.

The protected runner must include a supported `cosign` binary. The workflow
fails if it is unavailable, so signing cannot silently be skipped. Keep that
runner image/version under infrastructure change control and test a staging
signature before promoting it.

## Release evidence

`scripts/release_evidence.py` is the machine-checkable release record. It
rejects mutable image tags and validates checksums for the SBOM and smoke
report. Use it outside GitHub only with a real CI URL and a named approver:

```bash
python scripts/release_evidence.py create \
  --output /tmp/release-evidence.json \
  --sbom /tmp/agentbuilder.sbom.cdx.json \
  --smoke-report /tmp/release-evidence.smoke.json \
  --image api=registry.example/agentbuilder-api@sha256:<64-hex-digest> \
  --commit "$(git rev-parse HEAD)" \
  --environment production \
  --ci-run-url https://github.example/org/repo/actions/runs/123 \
  --approved-by release-owner

python scripts/release_evidence.py validate \
  --evidence /tmp/release-evidence.json \
  --expected-commit "$(git rev-parse HEAD)" \
  --require-attestations \
  --require-smoke
```

The second command intentionally fails until a release signer has published
and recorded both Cosign signature and provenance evidence for every image.
This prevents a digest-only deployment from being misrepresented as a signed
release.

## SLOs and alerts

| Indicator | Initial GA objective | Page condition |
| --- | --- | --- |
| API readiness | 99.9% successful `/ready` checks per calendar month | Two consecutive black-box probe failures or any production dependency outage lasting five minutes |
| API latency | P95 non-streaming HTTP latency ≤ 3 s | P95 exceeds 3 s for 15 minutes |
| Server errors | <1% 5xx responses over five minutes | ≥1% 5xx for five minutes |
| Retrieval grounding | Citation coverage ≥95% for grounded-answer traffic | Daily evaluation below target or a material drop from baseline |
| Durable ingestion | 99% terminal completion within the service objective agreed per tenant | Queue age/retry failures exceed the agreed tenant window |
| Shopify sync | Zero terminal failures for an active commerce tenant | Any terminal `catalog_sync` failure or a job stuck past its full-sync window |

Install [the supplied Prometheus rules](../../ops/prometheus/agentbuilder-alerts.yml)
and [Grafana overview dashboard](../../ops/grafana/agentbuilder-overview.dashboard.json)
with an external black-box probe for `https://<api>/ready`. The catalog rules
use existing API metrics. Durable-ingestion queue depth must also be polled
from the authenticated status surface until a dedicated worker metric exporter
is introduced; do not infer queue health from API liveness.

Build dashboards for readiness/dependency state, request latency and error
ratio, rate-limit blocks, catalog job failures/duration, ingestion queue age,
and deployment revision/digest. Each dashboard must link its owning runbook.

Run the bounded edge-capacity probe after a staging deployment and retain its
report with the release evidence. It is intentionally read-only and is not a
substitute for an authenticated RAG/commerce workload evaluation:

```bash
python scripts/load_probe.py \
  --url https://<api-host>/ready \
  --requests 500 \
  --concurrency 25 \
  --max-p95-ms 3000 \
  --max-error-rate 0.01 \
  --report /tmp/agentbuilder-ready-load.json
```

## Recovery drills and runbook

Run the [Mongo and worker recovery drill](MONGO_AND_WORKER_RECOVERY_RUNBOOK.md)
in staging before GA and at least quarterly thereafter. Record the evidence
alongside the release artifact. The drill verifies Mongo lease recovery,
duplicate-worker fencing, Redis fail-closed behavior, worker restart safety,
and rollback to the prior signed image digest.

## What this repository cannot prove alone

This codebase cannot configure GitHub Environment reviewers, Entra federated
credentials, Azure RBAC, private endpoints, Prometheus/Alertmanager routing,
or execute a real Shopify webhook against a partner store. Those are mandatory
environment actions, not optional documentation follow-ups. The release
workflow and smoke/evidence files make their absence visible and block a
repository-owned release path rather than claiming GA readiness without proof.
