# MCP lifecycle and security contract (v1)

MCP is a tenant-scoped connector boundary, not an unrestricted model network
path. Every configured connector records its owner brand, enabled state, and
allowed endpoint configuration. Secrets remain encrypted in runtime settings
and are not returned through agent/configuration APIs.

1. **Register:** an operator with agent-write scope configures a connector.
   The endpoint is validated against its connector policy; SSRF/private-network
   destinations are rejected unless a deployment-owned private connector policy
   explicitly permits them.
2. **Discover:** the runtime uses a stable service identity and tenant-scoped
   headers. Discovery must return a valid catalogue. Transport, JSON-RPC, or
   invalid-catalogue failures are `mcp_discovery_unavailable`, not an empty
   successful tool list.
3. **Execute:** only discovered, enabled tools may run. Tool output is treated
   as untrusted data. Raw exception, credential, endpoint, and remote error
   text stays in private logs and never enters LLM system context or a public
   response.
4. **Rotate/revoke:** disabling or revoking a connector prevents future
   discovery/execution. Rotate secrets through encrypted settings; do not add
   them to agent records, logs, URLs, or job progress.
5. **Audit:** retain only tenant scope, opaque connector/tool IDs, stable
   outcome code, and timestamps. Subject-content retention follows the privacy
   lifecycle contract.

The Shopify MCP bridge additionally requires the internal
`MCP_SERVICE_AUTH_TOKEN`, canonical `*.myshopify.com` host validation, and no
URL credential transport. See [P5 operations](P5_SHOPIFY_OPERATIONS.md).
