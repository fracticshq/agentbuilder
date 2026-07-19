# Realtime event contract (v1)

This document defines the HTTP streaming and takeover-control contracts that
are intentionally outside OpenAPI.

## Widget SSE

`POST /api/v1/messages/stream` requires `X-Widget-Session`. The signed session
is checked against its immutable conversation and tenant scope before the
response starts. A client may reconnect with the same valid session and repeat
its request only when its application-level idempotency design can tolerate a
new model turn; SSE itself has no server replay cursor today.

Each event uses `data: <JSON>\n\n`. Event payloads are
`StreamingMessageResponse` objects with `type` such as `activity`, `content`,
`tool_result`, `metadata`, or terminal `error`.

On any generation/wrapper failure, the only terminal failure payload is:

```json
{
  "type": "error",
  "content": "Unable to complete this response. Please try again.",
  "metadata": {"code": "generation_failed", "retryable": true}
}
```

Clients must not render exception text, treat a terminal error as a completed
answer, or retry an action-bearing commerce prompt automatically.

## Widget chat WebSocket

`WS /api/v1/messages/ws` accepts a message-local `session_token`; IDs supplied
in the message body are overwritten by the signed token. The server re-checks
the immutable tenant scope for every message. If the session expired, was
deleted, or its agent moved brands, it sends a generic error and the client
must start a new session.

The WebSocket must never carry a JWT/session in its URL. The human-takeover
control channels use subprotocol credentials instead:

```text
WS /api/v1/messages/ws/widget/{conversation_id}
Sec-WebSocket-Protocol: widget-session, <widget-session-jwt>

WS /api/v1/messages/ws/admin/{conversation_id}
Sec-WebSocket-Protocol: bearer, <dashboard-access-jwt>
```

Only the non-secret `widget-session` or `bearer` protocol is selected by the
server; the credential is not reflected in upgrade headers or URLs.

## Human-control events

The operator channel may send `take_control`, `release_control`, and
`admin_message`. The server emits these application events to both authorized
peers:

| Event | Payload | Meaning |
| --- | --- | --- |
| `control_status` | `{ "is_human_in_control": boolean }` | Authoritative takeover state. |
| `system_notice` | `{ "content": string }` | Safe operator/widget status text. |
| `admin_message` | `{ "role": "assistant", "content": string }` | Human agent reply during takeover. |
| `rate_limit` | `{ "retry_after": number, "policy": string }` | Channel is being closed due to a limit. |

On `release_control`, client UI must wait for `control_status=false` before
accepting an AI response. A persistence failure leaves human control active and
sends an operator retry notice; clients must not infer a release from their own
button click.

## Close/error rules

- Policy/authentication violations close with `1008` and a generic reason.
- Internal control-channel failures close with `1011`; diagnostic detail stays
  in structured server logs only.
- Redis/Mongo authorization failures are availability failures, not permission
  grants. Clients can reconnect after the service-health condition clears.
