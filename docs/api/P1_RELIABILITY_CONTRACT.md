# P1 reliability contract and deployment checklist

P1 makes retrieval availability, evidence metadata, and generation failures
explicit client contracts. Deploy API and widget updates together so the widget
can distinguish an empty search from a temporary grounding outage.

## Client response contract

`MessageResponse.metadata.retrieval` and the equivalent SSE terminal metadata
may contain:

```json
{
  "status": "evidence | no_evidence | degraded | error",
  "reason": "safe stable reason",
  "backend_status": "success | unavailable",
  "successful_backends": ["atlas", "bm25"],
  "failed_backends": ["qdrant"]
}
```

Fields are optional to preserve compatibility with agents that did not execute
retrieval. Consumers must ignore unknown fields and never render diagnostic
exception text.

| Condition | API meaning | Recommended UX |
| --- | --- | --- |
| `evidence` | Grounded chunks are available. | Show normal response and citations. |
| `no_evidence` | Search completed but has no relevant data. | Say no matching information was found; avoid outage messaging. |
| `degraded` | A partial backend failure occurred. | Use available citations/results, mark limited availability where grounded answers are required, and permit retry. |
| `error` | No retrieval backend was usable. | Show a retry affordance; do not label a generated fallback as sourced knowledge. |

Citation objects are bounded and safe:

```json
{
  "doc_id": "string",
  "title": "string",
  "url": "https://example.com/source",
  "snippet": "short source excerpt",
  "confidence": 0.91
}
```

Only HTTP(S) URLs are exposed. Treat all fields as optional presentation data;
the API deliberately suppresses malformed URLs, raw documents, credentials,
provider information, and error strings.

## Streaming failure contract

When LLM generation cannot complete, `POST /api/v1/messages/stream` sends a
single terminal `error` event with `metadata.code = "generation_failed"` and
`metadata.retryable = true`. It does not send a successful `final_answer` or
`done` event afterward. The content is a generic retry message, never a raw
LLM/provider exception.

This rule also applies to the HTTP streaming wrapper and the widget WebSocket
wrapper: no provider, MCP, database, authorization, or exception text may be
serialized to an unauthenticated widget client. WebSocket errors use the same
`generation_failed` metadata and a generic retry message.

## Admin operational contract

- Azure deployment discovery requires valid ARM configuration. Missing ARM
  configuration returns HTTP `503`, so dashboards should render unavailable
  configuration rather than an empty-but-successful deployment list.
- Runtime settings fall back to environment values only when persistence is
  unavailable. A malformed or unexpected persistence response is surfaced as
  an error and needs operator attention.

## Release verification

1. Query known knowledge and confirm `status=evidence` plus safe citations.
2. Query an absent topic and confirm `status=no_evidence`, not `error`.
3. Disable one retrieval backend in staging and confirm `status=degraded`.
4. Disable every retrieval backend in staging and confirm `status=error`, a
   generic retryable message, and no fabricated citation.
5. Force an LLM generation failure and confirm exactly one terminal SSE
   `error` event with `generation_failed` metadata.
6. Remove Azure ARM configuration and confirm the deployment endpoint returns
   `503`.

## CI baseline

The repository CI workflow validates the API suite, widget lint/test/build,
Shopify MCP tests, admin production build, container builds, and compose
configuration. Dependabot opens weekly dependency updates for Python, npm, and
Docker manifests. Add SAST, dependency-vulnerability enforcement, and deployed
tenant-isolation tests before declaring a fully mature production release.
