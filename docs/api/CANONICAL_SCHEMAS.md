# Canonical evidence and commerce schemas (v1)

## Evidence / citation (`evidence.v1`)

Public citations are presentation-safe projections, not raw retrieved records:

```json
{
  "doc_id": "string",
  "title": "string",
  "url": "https://example.com/source",
  "snippet": "bounded source excerpt",
  "confidence": 0.91
}
```

`url` must be HTTP(S); credentials, provider diagnostics, raw documents, vector
payloads, and opaque tool output are excluded. Retrieval metadata exposes only
the stable status values `evidence`, `no_evidence`, `degraded`, and `error`.
See [P1 reliability](P1_RELIABILITY_CONTRACT.md) for failure semantics.

## Commerce product (`commerce.product.v1`)

Every catalog/provider adapter maps into this shape before persistence or widget
delivery. Providers may retain raw source data privately, but consumers must not
depend on it.

```json
{
  "id": "canonical variant or product identifier",
  "product_id": "source product identifier",
  "variant_id": "source variant identifier",
  "product_group_id": "stable grouping identifier",
  "name": "customer-facing title",
  "sku": "optional SKU",
  "price_minor": 149900,
  "currency": "INR",
  "currency_source": "product|commerce.default_currency",
  "in_stock": true,
  "source_active": true,
  "image_url": "https://…",
  "product_url": "https://…",
  "catalog_source": {"provider": "shopify", "source_key": "…"}
}
```

Amounts are integer minor units. A UI formats them using the item currency;
adapters must never mix major/minor units. `source_active=false` or
`in_stock=false` means the item is not eligible for a new recommendation/cart
mutation. Versioned schema additions are additive; a breaking field change
requires `commerce.product.v2` plus an explicit migration.

## Cart action (`commerce.cart_action.v1`)

Action tools receive canonical GraphQL IDs and explicit positive integer
quantities. A malformed quantity is an action failure, never an implicit `1`.
Only a successful tool response can produce a checkout URL, and it must be an
absolute HTTPS URL on the configured Shopify shop host.
