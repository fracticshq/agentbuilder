# P6 canonical source and API-contract contract

P6 removes the last tested-versus-deployed Python source split and makes the
HTTP integration artefacts generated rather than hand-maintained.

## One shared package tree

`packages/` is the sole source for `commons`, `llm`, `memory`, `retrieval`,
`tools`, and `agent_runtime`. The obsolete `apps/api/packages/` copy was
removed. The API Dockerfile, CI install, test bootstrap, and `apps/api/start.sh`
all use the root tree.

`scripts/verify_canonical_packages.py` is a CI and regression-test gate. It
fails if a source file, package manifest, `README`, or `AGENTS` file appears
under `apps/api/packages/`, or if a canonical root package is incomplete.
Generated Python bytecode left on a developer machine is ignored; it is never a
source or Docker build input.

## Generated API artefacts

| Artefact | Source | Command |
| --- | --- | --- |
| `docs/api/openapi.json` | FastAPI application's OpenAPI 3.1 schema | `python scripts/generate_openapi.py` |
| `docs/api/Agent_Builder_Platform.postman_collection.json` | Committed OpenAPI snapshot | `python scripts/generate_postman_collection.py` |

Both scripts have `--check` modes and run in the API CI job. A route, request
model, response model, tag, or operation-ID change that alters OpenAPI must
include regenerated artefacts in the same commit.

The generated collection applies `{{accessToken}}` as bearer authentication to
operations that FastAPI marks as protected. Set that collection variable to a
valid dashboard or agent API token before executing those requests.

The HTTP schema does not represent WebSocket upgrades. Keep those contracts in
`API_DOCUMENTATION.md` and P4, including the required authentication
subprotocols and the prohibition on query-string credentials.

## Companion production contracts

- [RBAC and brand scope](RBAC_BRAND_SCOPE_MATRIX.md)
- [Realtime SSE/WebSocket events](REALTIME_EVENT_CONTRACT.md)
- [Privacy lifecycle](PRIVACY_LIFECYCLE.md)
- [Canonical evidence and commerce schemas](CANONICAL_SCHEMAS.md)
- [Shopify OAuth contract and current GA gaps](SHOPIFY_OAUTH_CONTRACT.md)
- [Lal Kitab connector versioning](LALKITAB_CONNECTOR_CONTRACT.md)
- [MCP lifecycle/security](MCP_SECURITY_LIFECYCLE.md)
- [Shared HTTP semantics](HTTP_STANDARDS.md)

## Release review

Before promotion, confirm:

1. `python scripts/verify_canonical_packages.py` passes.
2. `python scripts/generate_openapi.py --check` passes.
3. `python scripts/generate_postman_collection.py --check` passes.
4. Any consumer-impacting API change is called out in the release notes and
   exercised with the generated Postman collection.

For digest-pinned deployment, signed release evidence, smoke gates, alerting,
and recovery drills, see the [GA release and operations contract](../operations/GA_RELEASE_OPERATIONS.md).
