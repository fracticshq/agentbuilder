# Shopify OAuth contract and migration requirements

The deployed catalog-sync path uses an encrypted per-brand Admin API token and
Admin GraphQL. The Shopify MCP bridge also supports customer-account PKCE for
customer-facing MCP actions. These are distinct authority models and must not
be conflated.

## Current customer-account flow

1. The internal MCP bridge receives a canonical `*.myshopify.com` shop and a
   stable opaque session ID.
2. It discovers Shopify customer-account endpoints, generates PKCE verifier,
   challenge, and state, then redirects the customer to Shopify.
3. The callback validates state and exchanges the authorization code at the
   validated token endpoint.
4. The access token remains in the bridge's server-side session store and is
   forwarded only to the validated customer-account MCP endpoint.

Redirect URIs must be pre-registered HTTPS production URLs. Never accept a
customer token, OAuth code, verifier, or state in a widget URL, logs, agent
configuration, Mongo job, or LLM prompt.

## GA gaps before declaring OAuth complete

- Persist OAuth grants with tenant, shop, granted scopes, expiry, rotation, and
  revocation state in encrypted durable storage; current bridge-session storage
  is not an operator-visible lifecycle record.
- Add explicit start/callback/revoke/status API contracts, CSRF/session binding,
  consent text, and audit receipts.
- Reconcile webhook/app-uninstall events with OAuth grant revocation and catalog
  token deletion.
- Add replay, token-refresh, expired-grant, cross-brand, and callback-origin
  end-to-end tests.

Until these are implemented, advertise the flow as a constrained bridge feature
instead of a completed multi-tenant Shopify OAuth integration.
