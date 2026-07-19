"""Catalog Service — multi-source product import with sync support.

Authenticated Shopify sync uses the versioned Admin GraphQL API. Public JSON
feeds remain a separate, explicitly configured import source.
"""
from __future__ import annotations

import asyncio
import csv
import io
import ipaddress
import os
import re
import socket
import uuid
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import structlog

from app.config import Settings
from app.connections import connection_manager
from app.services.knowledge_service import KnowledgeService
from .job_store import JobStore

logger = structlog.get_logger()

_job_store = JobStore()
_SHOPIFY_API_VERSION_PATTERN = re.compile(r"^20\d{2}-(?:01|04|07|10)$")
_SHOPIFY_GRAPHQL_PRODUCTS_PAGE_SIZE = 10
_SHOPIFY_GRAPHQL_VARIANTS_PAGE_SIZE = 100
_SHOPIFY_GRAPHQL_MAX_RETRIES = 3

_SHOPIFY_SHOP_CURRENCY_QUERY = """
query ShopCurrency {
  shop { currencyCode }
}
"""

_SHOPIFY_PRODUCTS_QUERY = """
query CatalogProducts($after: String, $first: Int!) {
  products(first: $first, after: $after, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      legacyResourceId
      title
      handle
      productType
      vendor
      tags
      options { name position }
      featuredImage { url }
      variants(first: 25) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          legacyResourceId
          sku
          title
          price { amount currencyCode }
          inventoryQuantity
          inventoryPolicy
          image { url }
          selectedOptions { name value }
        }
      }
    }
  }
}
"""

_SHOPIFY_PRODUCT_VARIANTS_QUERY = """
query CatalogProductVariants($productId: ID!, $after: String, $first: Int!) {
  product(id: $productId) {
    variants(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        legacyResourceId
        sku
        title
        price { amount currencyCode }
        inventoryQuantity
        inventoryPolicy
        image { url }
        selectedOptions { name value }
      }
    }
  }
}
"""


def shopify_admin_api_version() -> str:
    """Return an explicitly configured, current Shopify API release label."""
    configured = str(os.environ.get("SHOPIFY_ADMIN_API_VERSION", "2026-04")).strip()
    if not _SHOPIFY_API_VERSION_PATTERN.fullmatch(configured):
        raise ValueError("SHOPIFY_ADMIN_API_VERSION must use the YYYY-MM Shopify release format.")
    return configured


async def create_job(job_id: str, job_type: str, brand_id: str, total: int = 0) -> None:
    """Persist an owned catalog job before its asynchronous worker is queued."""
    await _job_store.set(job_id, {
        "job_id": job_id,
        "type": job_type,
        "brand_id": brand_id,
        "status": "processing",
        "processed": 0,
        "total": total,
        "items": [],
        "results": [],
        "counts": {
            "products_seen": 0,
            "products_upserted": 0,
            "products_marked_inactive": 0,
            "error_count": 0,
        },
        "error": None,
        "created_at": datetime.utcnow().isoformat(),
    })


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _job_store.get(job_id)


# ── Format detection ──────────────────────────────────────────────────────────

def _detect_format(data: Any) -> str:
    """Auto-detect JSON feed format. Returns one of: shopify, woocommerce, schema_org, generic, unknown."""
    # Shopify: { "products": [ { ..., "variants": [...] } ] }
    if isinstance(data, dict) and "products" in data:
        prods = data["products"]
        if prods and isinstance(prods[0], dict) and "variants" in prods[0]:
            return "shopify"

    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        # WooCommerce REST API
        if "stock_status" in first or "regular_price" in first:
            return "woocommerce"
        # schema.org
        if first.get("@type") in ("Product", "ProductGroup"):
            return "schema_org"
        # Generic array
        return "generic"

    if isinstance(data, dict) and data.get("@type") in ("Product", "ProductGroup"):
        return "schema_org"

    return "unknown"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_cents(value: Any) -> int:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def _price_amount(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("amount") or value.get("value") or value.get("price") or 0
    return value


def _normalize_currency(value: Any) -> Optional[str]:
    if value is None:
        return None
    currency = str(value).strip()
    return currency.upper() if currency else None


def normalize_shopify_store_url(value: Any) -> str:
    """Return a normalized Shopify store root URL or raise an actionable error."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Shopify store URL is required, for example celavilifestyle.com.")

    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ValueError
        if parsed.username or parsed.password:
            raise ValueError
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError
        host = hostname.rstrip(".").lower()
        _validate_shopify_hostname(host)
        port = f":{parsed.port}" if parsed.port else ""
    except (ValueError, TypeError):
        raise ValueError(
            "Enter a Shopify store root URL such as https://celavilifestyle.com or https://store.myshopify.com."
        ) from None

    return urlunsplit((parsed.scheme, f"{host}{port}", "", "", ""))


def _validate_shopify_hostname(hostname: str) -> None:
    """Reject obvious local, private, and cloud-metadata destinations."""
    host = hostname.rstrip(".").lower()
    blocked_names = {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "host.docker.internal",
        "kubernetes.default.svc",
    }
    if host in blocked_names or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
        raise ValueError
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError


def _is_myshopify_hostname(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    store_name = host.removesuffix(".myshopify.com")
    return (
        host.endswith(".myshopify.com")
        and bool(store_name)
        and bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", store_name))
    )


def normalize_authenticated_shopify_store_url(value: Any) -> str:
    """Require the canonical HTTPS Shopify host before sending an Admin token."""
    base_url = normalize_shopify_store_url(value)
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or parsed.port is not None or not _is_myshopify_hostname(hostname):
        raise ValueError(
            "Authenticated Shopify sync requires the canonical HTTPS store hostname, for example https://store.myshopify.com."
        )
    return f"https://{hostname}"


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is safe to use as an external HTTP destination."""
    return address.is_global


def _validate_public_hostname(hostname: str) -> None:
    """Reject local, reserved, and metadata hostnames before a DNS lookup."""
    host = hostname.rstrip(".").lower()
    blocked_names = {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "host.docker.internal",
        "kubernetes.default.svc",
    }
    if host in blocked_names or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
        raise ValueError("URL must target a public host.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not _is_public_ip(address):
        raise ValueError("URL must target a public host.")


async def _resolve_public_hostname(hostname: str) -> None:
    """Resolve a hostname and reject DNS answers that point into private networks."""
    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved.") from exc

    addresses = {record[4][0] for record in records if record[4]}
    if not addresses:
        raise ValueError("URL hostname could not be resolved.")

    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError("URL hostname resolved to an invalid address.") from exc
        if not _is_public_ip(address):
            raise ValueError("URL hostname must resolve only to public addresses.")


async def validate_json_feed_url(value: Any) -> str:
    """Validate a JSON feed URL, including its currently-resolved IP addresses."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError
        # Accessing .port intentionally validates malformed ports such as :abc.
        _ = parsed.port
    except (TypeError, ValueError):
        raise ValueError("JSON feed URL must be a public http or https URL.") from None

    host = hostname.rstrip(".").lower()
    _validate_public_hostname(host)
    if _is_myshopify_hostname(host) and parsed.path.rstrip("/") == "/products.json":
        raise ValueError("Shopify catalog sync must use the authenticated Admin GraphQL integration, not products.json.")
    await _resolve_public_hostname(host)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def normalize_currency_code(value: Any, *, allow_empty: bool = True) -> Optional[str]:
    """Normalize an explicit ISO-style three-letter currency code."""
    currency = _normalize_currency(value)
    if not currency and allow_empty:
        return None
    if not currency or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a three-letter code such as INR, USD, or EUR.")
    return currency


def _extract_catalog_currency(*sources: Optional[Dict[str, Any]]) -> Optional[str]:
    for source in sources:
        if not isinstance(source, dict):
            continue

        for key in ("currency", "currencyCode", "currency_code", "price_currency", "priceCurrency"):
            currency = _normalize_currency(source.get(key))
            if currency:
                return currency

        for price_key in ("price", "priceV2", "compare_at_price", "compareAtPrice"):
            price = source.get(price_key)
            if isinstance(price, dict):
                currency = _extract_catalog_currency(price)
                if currency:
                    return currency

        presentment_prices = source.get("presentment_prices")
        if isinstance(presentment_prices, list):
            for presentment in presentment_prices:
                if not isinstance(presentment, dict):
                    continue
                currency = _extract_catalog_currency(presentment.get("price"), presentment)
                if currency:
                    return currency

    return None


def _currency_with_source(
    *catalog_sources: Optional[Dict[str, Any]],
    shopify_currency: Optional[str] = None,
    fallback_currency: Optional[str] = None,
) -> tuple[Optional[str], str]:
    authoritative_currency = _normalize_currency(shopify_currency)
    if authoritative_currency:
        return authoritative_currency, "shopify_store"

    catalog_currency = _extract_catalog_currency(*catalog_sources)
    if catalog_currency:
        return catalog_currency, "catalog"

    configured_currency = _normalize_currency(fallback_currency)
    if configured_currency:
        return configured_currency, "configured_default"

    return None, "missing"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _shopify_product_group_id(product: Dict[str, Any], handle: str, product_url: Optional[str]) -> str:
    product_id = (
        product.get("id")
        or product.get("legacy_resource_id")
        or product.get("admin_graphql_api_id")
        or product.get("graphql_id")
        or handle
        or product_url
        or uuid.uuid4()
    )
    return f"shopify:{product_id}"


def _shopify_source_key(product: Dict[str, Any], variant: Optional[Dict[str, Any]] = None) -> str:
    product_id = product.get("id") or product.get("admin_graphql_api_id") or product.get("graphql_id") or product.get("handle")
    product_key = str(product_id or "unknown-product")
    variant_id = (variant or {}).get("id") or (variant or {}).get("admin_graphql_api_id") or (variant or {}).get("graphql_id")
    return f"shopify:{product_key}:{variant_id or 'product'}"


def _shopify_option_names(product: Dict[str, Any]) -> List[str]:
    raw_options = product.get("options") or []
    option_names: List[str] = []
    if isinstance(raw_options, list):
        for index, option in enumerate(raw_options, start=1):
            if isinstance(option, dict):
                option_names.append(str(option.get("name") or f"Option {index}"))
            elif option not in (None, ""):
                option_names.append(str(option))
    while len(option_names) < 3:
        option_names.append(f"Option {len(option_names) + 1}")
    return option_names[:3]


def _shopify_variant_options(variant: Dict[str, Any], option_names: List[str]) -> Dict[str, str]:
    options: Dict[str, str] = {}
    for index, option_name in enumerate(option_names, start=1):
        value = variant.get(f"option{index}")
        if value not in (None, "", "Default Title"):
            options[str(option_name)] = str(value)
    return options


def _shopify_variant_url(product_url: Optional[str], variant_id: Any) -> Optional[str]:
    if not product_url or variant_id in (None, ""):
        return product_url
    separator = "&" if "?" in product_url else "?"
    return f"{product_url}{separator}variant={variant_id}"


def _shopify_image_src(image: Any) -> Optional[str]:
    if isinstance(image, dict):
        src = image.get("src") or image.get("url")
        return str(src) if src not in (None, "") else None
    if image not in (None, ""):
        return str(image)
    return None


def _shopify_variant_image(variant: Dict[str, Any], images: List[Any], primary_image: Optional[str]) -> Optional[str]:
    featured_image = variant.get("featured_image") or variant.get("image")
    featured_src = _shopify_image_src(featured_image)
    if featured_src:
        return featured_src

    variant_id = variant.get("id")
    image_id = variant.get("image_id")
    for image in images:
        if not isinstance(image, dict):
            continue
        if image_id not in (None, "") and image.get("id") == image_id:
            return _shopify_image_src(image) or primary_image
        variant_ids = image.get("variant_ids")
        if variant_id not in (None, "") and isinstance(variant_ids, list) and variant_id in variant_ids:
            return _shopify_image_src(image) or primary_image

    return primary_image


def _shopify_legacy_resource_id(value: Any) -> Optional[str]:
    """Return Shopify's stable numeric REST-compatible identity from a GraphQL value."""
    if value not in (None, ""):
        raw = str(value).strip()
        if raw.isdigit():
            return raw
        # ``legacyResourceId`` is expected, but parse a GID fallback rather
        # than persisting a new identity format and duplicating existing rows.
        match = re.search(r"/(\d+)$", raw)
        if match:
            return match.group(1)
    return None


def _shopify_graphql_variant_to_legacy(variant: dict[str, Any]) -> dict[str, Any]:
    variant_id = _shopify_legacy_resource_id(variant.get("legacyResourceId")) or _shopify_legacy_resource_id(variant.get("id")) or ""
    if not variant_id:
        raise ShopifyGraphQLRequestError("shopify_graphql_variant_identity_missing")
    price = variant.get("price") if isinstance(variant.get("price"), dict) else {}
    image = variant.get("image") if isinstance(variant.get("image"), dict) else {}
    selected_options = variant.get("selectedOptions") if isinstance(variant.get("selectedOptions"), list) else []
    legacy: dict[str, Any] = {
        "id": variant_id,
        "admin_graphql_api_id": str(variant.get("id") or ""),
        "sku": variant.get("sku"),
        "title": variant.get("title"),
        "price": price.get("amount"),
        "currency": price.get("currencyCode"),
        "inventory_quantity": variant.get("inventoryQuantity"),
        "inventory_policy": str(variant.get("inventoryPolicy") or "").lower(),
        **({"image": {"src": image.get("url")}} if image.get("url") else {}),
    }
    for index, option in enumerate(selected_options[:3], start=1):
        if isinstance(option, dict) and option.get("value") not in (None, ""):
            legacy[f"option{index}"] = option["value"]
    return legacy


def _shopify_graphql_product_to_legacy(product: dict[str, Any]) -> dict[str, Any]:
    """Adapt a GraphQL product node to the one canonical catalog normalizer.

    Keeping this adapter deliberately small avoids split product/variant/money
    contracts. Numeric ``legacyResourceId`` values preserve existing source
    keys, deletion-webhook matching, and idempotent knowledge upserts.
    """
    product_id = _shopify_legacy_resource_id(product.get("legacyResourceId")) or _shopify_legacy_resource_id(product.get("id")) or ""
    if not product_id:
        raise ShopifyGraphQLRequestError("shopify_graphql_product_identity_missing")
    featured_image = product.get("featuredImage") if isinstance(product.get("featuredImage"), dict) else {}
    options = product.get("options") if isinstance(product.get("options"), list) else []
    variants = product.get("variants") if isinstance(product.get("variants"), dict) else {}
    return {
        "id": product_id,
        "admin_graphql_api_id": str(product.get("id") or ""),
        "title": product.get("title") or "",
        "handle": product.get("handle") or "",
        "product_type": product.get("productType") or "General",
        "vendor": product.get("vendor") or "",
        "tags": product.get("tags") if isinstance(product.get("tags"), list) else [],
        "options": [
            {"name": option.get("name") or f"Option {index}"}
            for index, option in enumerate(options, start=1)
            if isinstance(option, dict)
        ],
        "images": ([{"src": featured_image["url"]}] if featured_image.get("url") else []),
        "variants": [
            _shopify_graphql_variant_to_legacy(variant)
            for variant in (variants.get("nodes") or [])
            if isinstance(variant, dict)
        ],
    }


async def _resolve_configured_default_currency(brand_id: Optional[str]) -> Optional[str]:
    if not brand_id:
        return None

    try:
        system_db = connection_manager.get_system_db()
        brand = await system_db.brands.find_one({
            "$or": [
                {"id": brand_id},
                {"slug": brand_id},
            ]
        })
        if not brand:
            return None

        sync_config = brand.get("catalog_sync") or {}
        explicit_currency = (
            sync_config.get("fallback_currency")
            or sync_config.get("default_currency")
            or brand.get("default_currency")
            or brand.get("currency")
        )
        return normalize_currency_code(explicit_currency)
    except Exception as exc:
        logger.warning("catalog_default_currency_resolution_failed", brand_id=brand_id, error=str(exc))
        return None


async def _update_brand_sync_state(brand_id: Optional[str], updates: Dict[str, Any]) -> None:
    if not brand_id or not updates:
        return
    try:
        system_db = connection_manager.get_system_db()
        set_fields = {f"catalog_sync.{key}": value for key, value in updates.items()}
        await system_db.brands.update_one(
            {"$or": [{"id": brand_id}, {"slug": brand_id}]},
            {"$set": set_fields},
        )
    except Exception as exc:
        logger.warning("catalog_sync_state_persist_failed", brand_id=brand_id, error=str(exc))


# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalize_shopify(
    data: dict,
    base_url: str = "",
    fallback_currency: Optional[str] = None,
    shopify_currency: Optional[str] = None,
) -> List[dict]:
    items: List[dict] = []
    for product in data.get("products", []):
        title = product.get("title", "")
        product_type = product.get("product_type") or "General"
        vendor = product.get("vendor", "")
        handle = product.get("handle", "")
        product_url = f"{base_url}/products/{handle}" if handle and base_url else None
        product_group_id = _shopify_product_group_id(product, handle, product_url)
        option_names = _shopify_option_names(product)
        images = product.get("images", [])
        primary_image = _shopify_image_src(images[0]) if images else None
        raw_tags = product.get("tags", "")
        features = [t.strip() for t in (raw_tags.split(",") if isinstance(raw_tags, str) else raw_tags) if t.strip()]
        variants = product.get("variants", [])
        variant_count = len(variants)
        variant_prices = [_to_cents(_price_amount(v.get("price", 0))) for v in variants if isinstance(v, dict)]
        price_min = min(variant_prices) if variant_prices else None
        price_max = max(variant_prices) if variant_prices else None
        default_variant_id = str(variants[0].get("id")) if variants and variants[0].get("id") not in (None, "") else None

        for v in variants:
            currency, currency_source = _currency_with_source(
                v,
                product,
                shopify_currency=shopify_currency,
                fallback_currency=fallback_currency,
            )
            variant_title = v.get("title", "")
            name = f"{title} – {variant_title}" if variant_title and variant_title != "Default Title" else title
            v_img = _shopify_variant_image(v, images, primary_image)
            inv_qty = v.get("inventory_quantity")
            in_stock = (inv_qty is None or inv_qty > 0) or v.get("inventory_policy") == "continue"
            variant_id = str(v.get("id")) if v.get("id") not in (None, "") else None
            variant_sku = str(v.get("sku") or variant_id or uuid.uuid4())
            items.append({
                "sku": variant_sku,
                "name": name,
                "parent_name": title,
                "price": _to_cents(_price_amount(v.get("price", 0))),
                "price_unit": "minor",
                "currency": currency,
                "currency_source": currency_source,
                "source_type": "shopify",
                "source_product_id": str(product.get("id") or product.get("admin_graphql_api_id") or product.get("handle") or ""),
                "source_variant_id": str(v.get("id") or v.get("admin_graphql_api_id") or ""),
                "source_key": _shopify_source_key(product, v),
                "category": product_type,
                "image_url": v_img,
                "product_url": product_url,
                "in_stock": bool(in_stock),
                "features": features,
                "vendor": vendor,
                "handle": handle,
                "product_group_id": product_group_id,
                "has_variants": variant_count > 1,
                "variant_count": variant_count,
                "price_min": price_min,
                "price_max": price_max,
                "default_variant_id": default_variant_id,
                "variant_id": variant_id,
                "variant_sku": variant_sku,
                "variant_title": variant_title if variant_title and variant_title != "Default Title" else None,
                "variant_options": _shopify_variant_options(v, option_names),
                "variant_url": _shopify_variant_url(product_url, variant_id),
            })

        if not variants:
            currency, currency_source = _currency_with_source(
                product,
                shopify_currency=shopify_currency,
                fallback_currency=fallback_currency,
            )
            items.append({
                "sku": str(product.get("id") or uuid.uuid4()),
                "name": title,
                "price": _to_cents(_price_amount(product.get("price", 0))),
                "price_unit": "minor",
                "currency": currency,
                "currency_source": currency_source,
                "source_type": "shopify",
                "source_product_id": str(product.get("id") or product.get("admin_graphql_api_id") or product.get("handle") or ""),
                "source_variant_id": None,
                "source_key": _shopify_source_key(product),
                "category": product_type,
                "image_url": primary_image,
                "product_url": product_url,
                "in_stock": True,
                "features": features,
                "vendor": vendor,
                "handle": handle,
                "product_group_id": product_group_id,
                "has_variants": False,
                "variant_count": 0,
                "price_min": None,
                "price_max": None,
                "default_variant_id": None,
                "variant_options": {},
            })
    return items


def _normalize_woocommerce(products: list, fallback_currency: Optional[str] = None) -> List[dict]:
    items = []
    for p in products:
        cats = p.get("categories", [])
        category = cats[0]["name"] if cats else "General"
        images = p.get("images", [])
        image_url = images[0]["src"] if images else None
        tags = p.get("tags", [])
        features = [t["name"] for t in tags if t.get("name")]
        in_stock = p.get("stock_status", "instock") == "instock"
        currency, currency_source = _currency_with_source(p, fallback_currency=fallback_currency)
        items.append({
            "sku": p.get("sku") or str(p.get("id") or uuid.uuid4()),
            "name": p.get("name", ""),
            "price": _to_cents(p.get("price") or p.get("regular_price", 0)),
            "currency": currency,
            "currency_source": currency_source,
            "category": category,
            "image_url": image_url,
            "product_url": p.get("permalink"),
            "in_stock": in_stock,
            "features": features,
        })
    return items


def _normalize_schema_org(raw: Any, fallback_currency: Optional[str] = None) -> List[dict]:
    nodes = raw if isinstance(raw, list) else [raw]
    items = []
    for node in nodes:
        t = node.get("@type", "")
        if t == "ProductGroup":
            for v in node.get("hasVariant", []):
                offer = v.get("offers", {})
                if isinstance(offer, list):
                    offer = offer[0] if offer else {}
                image = v.get("image")
                if isinstance(image, list):
                    image = image[0] if image else None
                currency, currency_source = _currency_with_source(offer, v, node, fallback_currency=fallback_currency)
                items.append({
                    "sku": v.get("sku") or str(uuid.uuid4()),
                    "name": v.get("name") or node.get("name", ""),
                    "price": _to_cents(offer.get("price", 0)),
                    "currency": currency,
                    "currency_source": currency_source,
                    "category": node.get("category", "General"),
                    "image_url": image,
                    "product_url": offer.get("url"),
                    "in_stock": "InStock" in offer.get("availability", "InStock"),
                    "features": [],
                    "color": v.get("color"),
                    "size": v.get("size"),
                })
        elif t == "Product":
            offer = node.get("offers", {})
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            currency, currency_source = _currency_with_source(offer, node, fallback_currency=fallback_currency)
            items.append({
                "sku": node.get("sku") or str(uuid.uuid4()),
                "name": node.get("name", ""),
                "price": _to_cents(offer.get("price", 0)),
                "currency": currency,
                "currency_source": currency_source,
                "category": node.get("category", "General"),
                "image_url": image,
                "product_url": offer.get("url"),
                "in_stock": "InStock" in offer.get("availability", "InStock"),
                "features": [],
            })
    return items


# ── Async fetch functions ─────────────────────────────────────────────────────

class ShopifyGraphQLRequestError(ValueError):
    """A safe, retryable-or-terminal failure returned by Shopify Admin GraphQL."""


def _shopify_graphql_url(base_url: str) -> str:
    base = normalize_authenticated_shopify_store_url(base_url)
    return f"{base.rstrip('/')}/admin/api/{shopify_admin_api_version()}/graphql.json"


def _shopify_graphql_error_codes(errors: Any) -> set[str]:
    codes: set[str] = set()
    for error in errors if isinstance(errors, list) else []:
        if not isinstance(error, dict):
            continue
        extensions = error.get("extensions") if isinstance(error.get("extensions"), dict) else {}
        code = extensions.get("code")
        if code:
            codes.add(str(code).upper())
    return codes


def _shopify_retry_delay(response: Any, attempt: int) -> float:
    headers = getattr(response, "headers", {}) or {}
    try:
        retry_after = float(headers.get("Retry-After", ""))
        if retry_after > 0:
            return min(retry_after, 30.0)
    except (TypeError, ValueError):
        pass
    return min(float(2 ** attempt), 10.0)


async def _post_shopify_graphql(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST one bounded GraphQL operation and fail closed on partial data.

    Shopify reports GraphQL failures in a 200 response, so an HTTP success is
    not sufficient. Throttle responses use a bounded retry with no token or
    provider diagnostic in logs/job state.
    """
    if not headers.get("X-Shopify-Access-Token"):
        raise ShopifyGraphQLRequestError("shopify_admin_token_missing")
    request_headers = {
        **headers,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = _shopify_graphql_url(base_url)
    payload = {"query": query, "variables": variables or {}}
    for attempt in range(_SHOPIFY_GRAPHQL_MAX_RETRIES):
        try:
            response = await client.post(url, headers=request_headers, json=payload)
        except httpx.HTTPError as exc:
            if attempt + 1 >= _SHOPIFY_GRAPHQL_MAX_RETRIES:
                raise ShopifyGraphQLRequestError("shopify_graphql_transport_failed") from exc
            await asyncio.sleep(_shopify_retry_delay(None, attempt))
            continue

        if bool(getattr(response, "is_redirect", False)) or response.status_code in {301, 302, 303, 307, 308}:
            raise ShopifyGraphQLRequestError("shopify_graphql_redirect_rejected")
        if response.status_code == 401:
            raise ShopifyGraphQLRequestError("shopify_admin_token_rejected")
        if response.status_code == 403:
            raise ShopifyGraphQLRequestError("shopify_admin_scope_denied")
        if response.status_code == 404:
            raise ShopifyGraphQLRequestError("shopify_store_not_found")
        if response.status_code == 429:
            if attempt + 1 >= _SHOPIFY_GRAPHQL_MAX_RETRIES:
                raise ShopifyGraphQLRequestError("shopify_graphql_throttled")
            await asyncio.sleep(_shopify_retry_delay(response, attempt))
            continue
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ShopifyGraphQLRequestError("shopify_graphql_response_invalid") from exc
        if not isinstance(body, dict):
            raise ShopifyGraphQLRequestError("shopify_graphql_response_invalid")
        errors = body.get("errors")
        if errors:
            error_codes = _shopify_graphql_error_codes(errors)
            if "THROTTLED" in error_codes and attempt + 1 < _SHOPIFY_GRAPHQL_MAX_RETRIES:
                await asyncio.sleep(_shopify_retry_delay(response, attempt))
                continue
            raise ShopifyGraphQLRequestError("shopify_graphql_throttled" if "THROTTLED" in error_codes else "shopify_graphql_query_failed")
        data = body.get("data")
        if not isinstance(data, dict):
            raise ShopifyGraphQLRequestError("shopify_graphql_response_invalid")
        return data
    raise ShopifyGraphQLRequestError("shopify_graphql_throttled")


async def _fetch_shopify_default_currency(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
) -> Optional[str]:
    """Fetch the store currency using Shopify Admin GraphQL only.

    The store currency is authoritative for the existing commerce contract, so
    a failed/malformed currency operation fails the snapshot rather than
    silently changing every product to a fallback currency.
    """
    data = await _post_shopify_graphql(
        client,
        base_url,
        headers,
        _SHOPIFY_SHOP_CURRENCY_QUERY,
    )
    shop = data.get("shop") if isinstance(data.get("shop"), dict) else None
    currency = _normalize_currency(shop.get("currencyCode")) if shop else None
    if not currency:
        raise ShopifyGraphQLRequestError("shopify_graphql_currency_missing")
    return currency


async def _fetch_shopify_remaining_variants(
    client: httpx.AsyncClient,
    base_url: str,
    headers: Dict[str, str],
    product: dict[str, Any],
) -> None:
    """Append every GraphQL product-variant page before publication."""
    product_id = str(product.get("id") or "")
    variants = product.get("variants") if isinstance(product.get("variants"), dict) else {}
    page_info = variants.get("pageInfo") if isinstance(variants.get("pageInfo"), dict) else {}
    after = page_info.get("endCursor")
    seen_cursors: set[str] = set()
    while page_info.get("hasNextPage"):
        if not product_id or not isinstance(after, str) or not after or after in seen_cursors:
            raise ShopifyGraphQLRequestError("shopify_graphql_variant_cursor_invalid")
        seen_cursors.add(after)
        data = await _post_shopify_graphql(
            client,
            base_url,
            headers,
            _SHOPIFY_PRODUCT_VARIANTS_QUERY,
            {"productId": product_id, "after": after, "first": _SHOPIFY_GRAPHQL_VARIANTS_PAGE_SIZE},
        )
        result_product = data.get("product") if isinstance(data.get("product"), dict) else None
        result_variants = result_product.get("variants") if result_product and isinstance(result_product.get("variants"), dict) else None
        if not result_variants:
            raise ShopifyGraphQLRequestError("shopify_graphql_variant_page_invalid")
        nodes = result_variants.get("nodes")
        if not isinstance(nodes, list):
            raise ShopifyGraphQLRequestError("shopify_graphql_variant_page_invalid")
        variants.setdefault("nodes", []).extend(node for node in nodes if isinstance(node, dict))
        page_info = result_variants.get("pageInfo") if isinstance(result_variants.get("pageInfo"), dict) else {}
        after = page_info.get("endCursor")
    product["variants"] = variants

async def fetch_shopify_products(
    store_url: str,
    access_token: Optional[str],
    job_id: str,
    brand_id: Optional[str] = None,
    fallback_currency: Optional[str] = None,
) -> None:
    """Read a complete Shopify Admin GraphQL snapshot before publishing it."""
    if not await _job_store.get(job_id):
        return

    all_items: List[dict] = []
    started_at = datetime.utcnow().isoformat()
    try:
        if not access_token or not access_token.strip():
            raise ValueError("Shopify catalog sync requires an Admin API access token.")
        base = normalize_shopify_store_url(store_url)
        base = normalize_authenticated_shopify_store_url(base)
        explicit_fallback = normalize_currency_code(fallback_currency) if fallback_currency else await _resolve_configured_default_currency(brand_id)
        await _job_store.update(job_id, {
            "brand_id": brand_id,
            "source_url": base,
            "started_at": started_at,
            "status": "processing",
            "counts": {
                "products_seen": 0,
                "products_upserted": 0,
                "products_marked_inactive": 0,
                "error_count": 0,
            },
        })
        await _update_brand_sync_state(brand_id, {
            "last_sync_job_id": job_id,
            "last_sync_status": "processing",
            "last_sync_started_at": started_at,
            "last_sync_error": None,
        })

        headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
            "Accept": "application/json",
        }
        if access_token and access_token.strip():
            headers["X-Shopify-Access-Token"] = access_token.strip()

        # Use a client without default redirect following to manage it manually and safely
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            shopify_currency = await _fetch_shopify_default_currency(client, base, headers)
            resolved_currency = shopify_currency or explicit_fallback
            currency_source = "shopify_store" if shopify_currency else ("configured_default" if explicit_fallback else "missing")
            logger.info(
                "shopify_currency_resolved",
                currency=resolved_currency,
                source=currency_source,
            )
            await _job_store.update(job_id, {
                "currency": resolved_currency,
                "currency_source": currency_source,
                "warning": None,
            })
            product_cursor: Optional[str] = None
            seen_product_cursors: set[str] = set()
            page = 1
            while True:
                if product_cursor:
                    if product_cursor in seen_product_cursors:
                        raise ShopifyGraphQLRequestError("shopify_graphql_product_cursor_invalid")
                    seen_product_cursors.add(product_cursor)
                logger.info("shopify_graphql_fetch_page", page=page, has_cursor=bool(product_cursor))
                data = await _post_shopify_graphql(
                    client,
                    base,
                    headers,
                    _SHOPIFY_PRODUCTS_QUERY,
                    {"after": product_cursor, "first": _SHOPIFY_GRAPHQL_PRODUCTS_PAGE_SIZE},
                )
                connection = data.get("products") if isinstance(data.get("products"), dict) else None
                if not connection:
                    raise ShopifyGraphQLRequestError("shopify_graphql_product_page_invalid")
                products = connection.get("nodes")
                if not isinstance(products, list):
                    raise ShopifyGraphQLRequestError("shopify_graphql_product_page_invalid")
                if not products:
                    page_info = connection.get("pageInfo") if isinstance(connection.get("pageInfo"), dict) else {}
                    if product_cursor or page_info.get("hasNextPage"):
                        raise ShopifyGraphQLRequestError("shopify_graphql_product_page_invalid")
                    break

                for product in products:
                    if not isinstance(product, dict):
                        raise ShopifyGraphQLRequestError("shopify_graphql_product_page_invalid")
                    await _fetch_shopify_remaining_variants(client, base, headers, product)

                batch = _normalize_shopify(
                    {"products": [_shopify_graphql_product_to_legacy(product) for product in products]},
                    base_url=base,
                    fallback_currency=explicit_fallback,
                    shopify_currency=shopify_currency,
                )
                all_items.extend(batch)
                await _job_store.update(job_id, {
                    "processed": len(all_items),
                    "total": len(all_items),
                    "page": page,
                })

                page_info = connection.get("pageInfo") if isinstance(connection.get("pageInfo"), dict) else {}
                if page_info.get("hasNextPage"):
                    next_cursor = page_info.get("endCursor")
                    if not isinstance(next_cursor, str) or not next_cursor:
                        raise ShopifyGraphQLRequestError("shopify_graphql_product_cursor_invalid")
                    product_cursor = next_cursor
                    page += 1
                else:
                    break

        sync_counts = {
            "products_seen": len(all_items),
            "products_upserted": 0,
            "products_marked_inactive": 0,
            "error_count": 0,
        }
        if brand_id:
            sync_counts = await _upsert_shopify_catalog_into_knowledge(brand_id, all_items, job_id, base)
        completed_at = datetime.utcnow().isoformat()
        await _job_store.update(job_id, {
            "items": all_items,
            "status": "completed",
            "total": len(all_items),
            "completed_at": completed_at,
            "counts": sync_counts,
        })
        await _update_brand_sync_state(brand_id, {
            "last_sync_status": "completed",
            "last_sync_completed_at": completed_at,
            "last_synced_at": completed_at,
            "last_sync_error": None,
            "last_sync_counts": sync_counts,
        })
        logger.info("shopify_fetch_complete", items=len(all_items))

    except Exception as exc:
        error_message = str(exc)
        finished_at = datetime.utcnow().isoformat()
        await _job_store.update(job_id, {
            "status": "error",
            "error": error_message,
            "completed_at": finished_at,
            "counts": {
                "products_seen": len(all_items),
                "products_upserted": 0,
                "products_marked_inactive": 0,
                "error_count": 1,
            },
        })
        await _update_brand_sync_state(brand_id, {
            "last_sync_status": "error",
            "last_sync_completed_at": finished_at,
            "last_sync_error": error_message,
            "last_sync_counts": {
                "products_seen": len(all_items),
                "products_upserted": 0,
                "products_marked_inactive": 0,
                "error_count": 1,
            },
        })
        logger.error("shopify_fetch_failed", error=str(exc))


async def _upsert_shopify_catalog_into_knowledge(
    brand_id: str,
    items: List[dict],
    source_job_id: str,
    source_url: str,
) -> Dict[str, int]:
    """Persist fetched Shopify products into the brand knowledge base.

    Shopify MCP is useful for actions, but catalog discovery needs NOVA's own
    hybrid retrieval so broad and nuanced product queries work reliably.
    """
    service = KnowledgeService(Settings())
    kb_job_id = await service.start_bulk_upload("product", items, brand_id)
    product_items = [
        SimpleNamespace(
            sku=str(item.get("sku") or item.get("id") or uuid.uuid4()),
            name=item.get("name") or item.get("title") or "Untitled product",
            price=int(item.get("price") or 0),
            price_unit=item.get("price_unit") or "minor",
            currency=item.get("currency"),
            currency_source=item.get("currency_source") or ("catalog" if item.get("currency") else "missing"),
            source_type=item.get("source_type") or "shopify",
            source_product_id=item.get("source_product_id"),
            source_variant_id=item.get("source_variant_id"),
            source_key=item.get("source_key"),
            category=item.get("category") or item.get("product_type") or "General",
            image_url=item.get("image_url") or item.get("image"),
            product_url=item.get("product_url") or item.get("url"),
            in_stock=item.get("in_stock", True),
            features=item.get("features") or [],
            product_group_id=item.get("product_group_id"),
            handle=item.get("handle"),
            parent_name=item.get("parent_name"),
            has_variants=item.get("has_variants", False),
            variant_count=item.get("variant_count", 0),
            price_min=item.get("price_min"),
            price_max=item.get("price_max"),
            default_variant_id=item.get("default_variant_id"),
            variant_id=item.get("variant_id"),
            variant_sku=item.get("variant_sku"),
            variant_title=item.get("variant_title"),
            variant_options=item.get("variant_options") or {},
            variant_url=item.get("variant_url"),
        )
        for item in items
    ]
    counts = await service.sync_shopify_catalog(
        kb_job_id,
        product_items,
        brand_id,
        source_url=source_url,
        source_job_id=source_job_id,
    )
    await _job_store.update(source_job_id, {"knowledge_job_id": kb_job_id, "knowledge_status": "completed"})
    return counts


async def fetch_json_feed(url: str, fallback_currency: Optional[str] = None) -> dict:
    """Fetch a JSON URL, auto-detect format, return normalised items + detected format."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
        "Accept": "application/json",
    }
    request_url = await validate_json_feed_url(url)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for redirect_count in range(4):
            resp = await client.get(request_url, headers=headers)
            is_redirect = bool(getattr(resp, "is_redirect", False)) or resp.status_code in {301, 302, 303, 307, 308}
            if not is_redirect:
                break

            if redirect_count == 3:
                raise ValueError("Too many redirects when fetching JSON feed.")
            location = resp.headers.get("Location")
            if not location:
                raise ValueError("JSON feed returned a redirect without a Location header.")
            request_url = await validate_json_feed_url(urljoin(request_url, location))
        else:  # pragma: no cover - the loop always breaks or raises
            raise ValueError("Too many redirects when fetching JSON feed.")

        if not resp.is_success:
            raise ValueError(f"HTTP {resp.status_code} when fetching JSON feed")
        data = resp.json()

    fmt = _detect_format(data)
    if fmt == "shopify":
        items = _normalize_shopify(data, fallback_currency=fallback_currency)
    elif fmt == "woocommerce":
        items = _normalize_woocommerce(data, fallback_currency=fallback_currency)
    elif fmt == "schema_org":
        items = _normalize_schema_org(data, fallback_currency=fallback_currency)
    elif fmt == "generic":
        items = data  # pass-through; Map Fields step handles it
    else:
        raise ValueError(
            "Could not detect feed format. "
            "Try 'Upload File' or 'Paste JSON' and use the field mapper instead."
        )
    return {"items": items, "detected_format": fmt, "raw_count": len(items)}


def parse_csv(content: str) -> List[dict]:
    """Parse CSV text into a list of dicts. Column headers become field keys."""
    reader = csv.DictReader(io.StringIO(content))
    rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError("CSV file is empty or contains no data rows.")
    return rows


async def run_firecrawl_scrape(
    urls: List[str],
    job_id: str,
    api_key: str,
    brand_id: str,
    *,
    fallback_currency: Optional[str] = None,
) -> None:
    """Background task: Firecrawl-extract product data from each URL."""
    job = await _job_store.get(job_id)
    if not job or job.get("brand_id") != brand_id:
        logger.warning("firecrawl_job_scope_mismatch", job_id=job_id, brand_id=brand_id)
        return

    try:
        from firecrawl import V1FirecrawlApp, V1JsonConfig  # type: ignore
    except ImportError:
        await _job_store.update(job_id, {"status": "error", "error": "firecrawl-py is not installed. Run: pip install firecrawl-py"})
        return

    extraction_schema = {
        "type": "object",
        "properties": {
            "product_type": {"type": "string", "enum": ["ProductGroup", "Product"]},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "sku": {"type": "string"},
            "price": {"type": "number"},
            "currency": {"type": "string"},
            "category": {"type": "string"},
            "image_url": {"type": "string"},
            "in_stock": {"type": "boolean"},
            "brand": {"type": "string"},
            "variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                        "color": {"type": "string"},
                        "size": {"type": "string"},
                        "image_url": {"type": "string"},
                        "in_stock": {"type": "boolean"},
                    },
                },
            },
        },
    }

    app = V1FirecrawlApp(api_key=api_key)
    all_items: List[dict] = []
    per_url: List[dict] = []

    for i, url in enumerate(urls):
        await _job_store.update(job_id, {"processed": i})
        try:
            extract_cfg = V1JsonConfig(
                schema_field=extraction_schema,
                prompt=(
                    "Extract the product name, SKU, price (as a number), "
                    "currency code (e.g. INR, USD, EUR), category, image URL, "
                    "and whether it is in stock. "
                    "If this is a product with multiple variants (sizes/colors), "
                    "set product_type to ProductGroup and list each variant. "
                    "Otherwise set product_type to Product."
                ),
            )
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                partial(
                    app.scrape_url,
                    url,
                    formats=["markdown", "extract"],
                    wait_for=3000,
                    extract=extract_cfg,
                ),
            )
            # result is a V1ScrapeResponse Pydantic model
            raw_extract = result.extract
            if raw_extract is None:
                extracted = {}
            elif isinstance(raw_extract, dict):
                extracted = raw_extract
            else:
                extracted = raw_extract.dict() if hasattr(raw_extract, "dict") else {}

            # Normalise common LLM field-name variations → our schema keys
            field_aliases = {
                "productName": "name", "title": "name", "product_name": "name",
                "productPrice": "price", "cost": "price",
                "currencyCode": "currency", "priceCurrency": "currency",
                "imageUrl": "image_url", "image": "image_url",
                "inStock": "in_stock", "available": "in_stock",
                "productType": "product_type", "type": "product_type",
            }
            for alias, canonical in field_aliases.items():
                if alias in extracted and canonical not in extracted:
                    extracted[canonical] = extracted.pop(alias)

            # Detect 404 / empty pages before checking extraction results
            markdown_lower = (result.markdown or "").lower()
            not_found_patterns = ["page not found", "404", "does not exist", "no page found"]
            if any(p in markdown_lower for p in not_found_patterns) and len(result.markdown or "") < 2000:
                per_url.append({"url": url, "status": "error", "error": "Page not found (404) — check the URL", "item_count": 0})
                continue

            if not extracted or not extracted.get("name"):
                per_url.append({"url": url, "status": "no_product", "item_count": 0})
                continue

            items: List[dict] = []
            if extracted.get("product_type") == "ProductGroup" and extracted.get("variants"):
                for v in extracted["variants"]:
                    currency, currency_source = _currency_with_source(
                        v,
                        extracted,
                        fallback_currency=fallback_currency,
                    )
                    items.append({
                        "sku": v.get("sku") or str(uuid.uuid4()),
                        "name": v.get("name") or extracted.get("name", ""),
                        "price": _to_cents(v.get("price") or extracted.get("price", 0)),
                        "currency": currency,
                        "currency_source": currency_source,
                        "category": extracted.get("category", "General"),
                        "image_url": v.get("image_url") or extracted.get("image_url"),
                        "product_url": url,
                        "in_stock": v.get("in_stock", True),
                        "features": [],
                        "color": v.get("color"),
                        "size": v.get("size"),
                    })
            else:
                currency, currency_source = _currency_with_source(
                    extracted,
                    fallback_currency=fallback_currency,
                )
                items.append({
                    "sku": extracted.get("sku") or str(uuid.uuid4()),
                    "name": extracted.get("name", ""),
                    "price": _to_cents(extracted.get("price", 0)),
                    "currency": currency,
                    "currency_source": currency_source,
                    "category": extracted.get("category", "General"),
                    "image_url": extracted.get("image_url"),
                    "product_url": url,
                    "in_stock": extracted.get("in_stock", True),
                    "features": [],
                })

            all_items.extend(items)
            per_url.append({
                "url": url,
                "status": "success",
                "product_type": extracted.get("product_type", "Product"),
                "item_count": len(items),
                "name": extracted.get("name", ""),
            })

        except Exception as exc:
            logger.error("firecrawl_url_error", url=url, error=str(exc))
            per_url.append({"url": url, "status": "error", "error": str(exc), "item_count": 0})

    await _job_store.update(job_id, {
        "items": all_items,
        "results": per_url,
        "status": "completed",
        "processed": len(urls),
        "total": len(urls),
    })
    logger.info("firecrawl_scrape_complete", urls=len(urls), items=len(all_items))
