"""
Catalog Service — multi-source product import with sync support.
Supports: Shopify /products.json, JSON feed (auto-detect), CSV, Firecrawl scrape.
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
import uuid
from datetime import datetime
from functools import partial
from typing import Any, Dict, List, Optional

import httpx
import structlog

from .job_store import JobStore

logger = structlog.get_logger()

_job_store = JobStore()


async def create_job(job_id: str, job_type: str, total: int = 0) -> None:
    await _job_store.set(job_id, {
        "job_id": job_id,
        "type": job_type,
        "status": "processing",
        "processed": 0,
        "total": total,
        "items": [],
        "results": [],
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
        return int(float(str(value).replace(",", "")) * 100)
    except (ValueError, TypeError):
        return 0


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalize_shopify(data: dict, base_url: str = "") -> List[dict]:
    items: List[dict] = []
    for product in data.get("products", []):
        title = product.get("title", "")
        product_type = product.get("product_type") or "General"
        vendor = product.get("vendor", "")
        handle = product.get("handle", "")
        product_url = f"{base_url}/products/{handle}" if handle and base_url else None
        images = product.get("images", [])
        primary_image = images[0].get("src") if images else None
        raw_tags = product.get("tags", "")
        features = [t.strip() for t in (raw_tags.split(",") if isinstance(raw_tags, str) else raw_tags) if t.strip()]
        variants = product.get("variants", [])

        for v in variants:
            variant_title = v.get("title", "")
            name = f"{title} – {variant_title}" if variant_title and variant_title != "Default Title" else title
            vid = v.get("image_id")
            v_img = next((img["src"] for img in images if img.get("id") == vid), primary_image)
            inv_qty = v.get("inventory_quantity")
            in_stock = (inv_qty is None or inv_qty > 0) or v.get("inventory_policy") == "continue"
            items.append({
                "sku": str(v.get("sku") or v.get("id") or uuid.uuid4()),
                "name": name,
                "price": _to_cents(v.get("price", 0)),
                "currency": "USD",
                "category": product_type,
                "image_url": v_img,
                "product_url": product_url,
                "in_stock": bool(in_stock),
                "features": features,
                "vendor": vendor,
            })

        if not variants:
            items.append({
                "sku": str(product.get("id") or uuid.uuid4()),
                "name": title,
                "price": 0,
                "currency": "USD",
                "category": product_type,
                "image_url": primary_image,
                "product_url": product_url,
                "in_stock": True,
                "features": features,
                "vendor": vendor,
            })
    return items


def _normalize_woocommerce(products: list) -> List[dict]:
    items = []
    for p in products:
        cats = p.get("categories", [])
        category = cats[0]["name"] if cats else "General"
        images = p.get("images", [])
        image_url = images[0]["src"] if images else None
        tags = p.get("tags", [])
        features = [t["name"] for t in tags if t.get("name")]
        in_stock = p.get("stock_status", "instock") == "instock"
        items.append({
            "sku": p.get("sku") or str(p.get("id") or uuid.uuid4()),
            "name": p.get("name", ""),
            "price": _to_cents(p.get("price") or p.get("regular_price", 0)),
            "currency": "USD",
            "category": category,
            "image_url": image_url,
            "product_url": p.get("permalink"),
            "in_stock": in_stock,
            "features": features,
        })
    return items


def _normalize_schema_org(raw: Any) -> List[dict]:
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
                items.append({
                    "sku": v.get("sku") or str(uuid.uuid4()),
                    "name": v.get("name") or node.get("name", ""),
                    "price": _to_cents(offer.get("price", 0)),
                    "currency": offer.get("priceCurrency", "USD"),
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
            items.append({
                "sku": node.get("sku") or str(uuid.uuid4()),
                "name": node.get("name", ""),
                "price": _to_cents(offer.get("price", 0)),
                "currency": offer.get("priceCurrency", "USD"),
                "category": node.get("category", "General"),
                "image_url": image,
                "product_url": offer.get("url"),
                "in_stock": "InStock" in offer.get("availability", "InStock"),
                "features": [],
            })
    return items


# ── Async fetch functions ─────────────────────────────────────────────────────


# ── Token cache: {store_domain: (token, expires_at_unix)} ────────────────────
# Avoids re-fetching a token on every paginated page-request.
# Shopify client-credentials tokens are valid for 24 hours (expires_in seconds).
_shopify_token_cache: Dict[str, tuple] = {}


def _get_cached_token(store_domain: str) -> Optional[str]:
    """Return a cached token if it is still valid (>60 s remaining)."""
    import time
    entry = _shopify_token_cache.get(store_domain)
    if entry:
        token, expires_at = entry
        if time.time() < expires_at - 60:  # 60-second safety buffer
            return token
    return None


def _set_cached_token(store_domain: str, token: str, expires_in: int) -> None:
    import time
    _shopify_token_cache[store_domain] = (token, time.time() + expires_in)


async def fetch_shopify_products(
    store_url: str,
    job_id: str,
    brand_id: Optional[str] = None,
    knowledge_service: Optional[Any] = None,
    settings: Optional[Any] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> None:
    """Background task: paginate Shopify /products.json and store results in job.

    Auth flow (Shopify client credentials grant — RFC 6749 §4.4):
      POST {base}/admin/oauth/access_token
        grant_type=client_credentials&client_id=...&client_secret=...
      → { access_token, scope, expires_in }
    The returned token is cached per store-domain for its lifetime (24 h)
    to avoid hammering the token endpoint on every paginated request.

    API version is read from settings.SHOPIFY_API_VERSION (default: 2026-04).
    All HTTP calls use HTTP/2 for improved multiplexing.
    429 responses are handled with exponential back-off via Retry-After header.
    """
    if not await _job_store.get(job_id):
        return

    base = store_url.strip().rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"

    # Derive a stable cache key from the hostname only (strip protocol/path)
    import time
    from urllib.parse import urlparse
    store_domain = urlparse(base).hostname or base

    headers: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
        "Accept": "application/json",
    }

    # ── Step 1: Acquire / refresh access token via client-credentials grant ──
    token: Optional[str] = None
    if client_id and client_secret:
        # Check cache first
        token = _get_cached_token(store_domain)

        if not token:
            token_url = f"{base}/admin/oauth/access_token"
            token_data = {
                "grant_type": "client_credentials",
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
            }
            try:
                async with httpx.AsyncClient(timeout=10.0, http2=True) as token_client:
                    logger.info("requesting_shopify_oauth_token", url=token_url)
                    token_resp = await token_client.post(
                        token_url,
                        data=token_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if token_resp.status_code == 200:
                        resp_json = token_resp.json()
                        token = resp_json.get("access_token")
                        expires_in = int(resp_json.get("expires_in", 86400))  # default 24 h
                        if token:
                            _set_cached_token(store_domain, token, expires_in)
                            logger.info(
                                "shopify_oauth_token_acquired",
                                expires_in=expires_in,
                                scope=resp_json.get("scope"),
                            )
                    else:
                        logger.error(
                            "shopify_oauth_token_failed",
                            status=token_resp.status_code,
                            body=token_resp.text[:500],
                        )
                        # Token fetch failed — we cannot safely continue for a
                        # private store; fail the job immediately with a clear message.
                        if client_id or client_secret:
                            await _job_store.update(
                                job_id,
                                {
                                    "status": "error",
                                    "error": (
                                        f"Shopify token request failed ({token_resp.status_code}). "
                                        "Verify your Client ID and Client Secret in the Shopify "
                                        "Partner / Dev Dashboard under Settings → API credentials."
                                    ),
                                },
                            )
                            return
            except Exception as e:
                logger.error("shopify_oauth_error", error=str(e))
                await _job_store.update(job_id, {"status": "error", "error": f"OAuth error: {e}"})
                return

    # ── Step 2: Attach token to request headers ───────────────────────────────
    if token:
        headers["X-Shopify-Access-Token"] = token
        logger.info("shopify_using_access_token", store=store_domain)

    # ── Step 3: Determine API version from settings ───────────────────────────
    api_version = "2026-04"
    if settings and getattr(settings, "SHOPIFY_API_VERSION", None):
        api_version = settings.SHOPIFY_API_VERSION
    logger.info("shopify_api_version", version=api_version)

    # ── Step 4: Paginate /products.json with HTTP/2 and 429 back-off ─────────
    all_items: List[dict] = []
    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=False, http2=True
        ) as client:
            page_info: Optional[str] = None
            page = 1

            while True:
                # Admin API if authenticated; public storefront otherwise
                has_auth = bool(token)
                if has_auth:
                    url = f"{base}/admin/api/{api_version}/products.json?limit=250"
                else:
                    url = f"{base}/products.json?limit=250"

                if page_info:
                    url += f"&page_info={page_info}"

                logger.info("shopify_fetch_page", page=page, url=url, has_auth=has_auth)

                # ── 429 retry loop ────────────────────────────────────────────
                for attempt in range(1, 4):
                    resp = await client.get(url, headers=headers)

                    # Log rate-limit header for observability
                    call_limit = resp.headers.get("X-Shopify-Shop-Api-Call-Limit", "?/?")
                    logger.debug("shopify_rate_limit", limit=call_limit, page=page)

                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", str(attempt * 2)))
                        logger.warning(
                            "shopify_rate_limited",
                            retry_after=retry_after,
                            attempt=attempt,
                        )
                        await asyncio.sleep(retry_after)
                        continue  # retry same page

                    break  # success or non-429 error — exit retry loop

                # ── Manual redirect handling ──────────────────────────────────
                if resp.is_redirect:
                    location = str(resp.headers.get("Location", ""))
                    logger.info("shopify_fetch_redirect", location=location)

                    if "/password" in location:
                        raise ValueError(
                            "The Shopify store is password-protected. Please go to "
                            "'Settings' in your Shopify Admin, create a Custom App, "
                            "and enter your Client ID and Client Secret to allow access."
                        )

                    url = str(resp.url.join(location))
                    resp = await client.get(url, headers=headers)

                # ── HTTP error handling ───────────────────────────────────────
                if resp.status_code == 401:
                    raise ValueError(
                        "Shopify authentication failed (401 Unauthorized). "
                        "Verify your Client ID and Client Secret are correct and "
                        "that the app is installed on this store."
                    )
                if resp.status_code == 403:
                    raise ValueError(
                        "Access denied (403 Forbidden). Ensure your app has the "
                        "'read_products' access scope configured in the Dev Dashboard."
                    )
                if resp.status_code == 404:
                    raise ValueError(f"Store not found at {base}. Check the URL.")
                if resp.status_code == 402:
                    raise ValueError(
                        "This store's plan does not support API access (402). "
                        "The store owner may need to upgrade their Shopify plan."
                    )
                resp.raise_for_status()

                data = resp.json()
                products = data.get("products", [])
                if not products:
                    break

                batch = _normalize_shopify(data, base_url=base)
                all_items.extend(batch)
                await _job_store.update(
                    job_id, {"processed": len(all_items), "total": len(all_items)}
                )

                # ── Cursor-based pagination via Link header ───────────────────
                # Per Shopify docs: only `limit` may be combined with page_info.
                link = resp.headers.get("Link", "")
                m = re.search(r'<[^>]*page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
                if m:
                    page_info = m.group(1)
                    page += 1
                else:
                    break  # no more pages

        await _job_store.update(
            job_id,
            {"items": all_items, "status": "processing_embeddings", "total": len(all_items)},
        )

        # ── Step 5: Ingest into knowledge base ───────────────────────────────
        if knowledge_service and brand_id and all_items:
            from types import SimpleNamespace

            logger.info("shopify_starting_ingestion", items=len(all_items), brand_id=brand_id)
            items_to_ingest = [SimpleNamespace(**item) for item in all_items]
            try:
                await knowledge_service.process_bulk_upload(
                    job_id=job_id,
                    content_type="product",
                    items=items_to_ingest,
                    brand_id=brand_id,
                )
                logger.info("shopify_ingestion_complete", job_id=job_id)
            except Exception as ing_exc:
                logger.error("shopify_ingestion_failed", error=str(ing_exc))
                await _job_store.update(
                    job_id,
                    {"status": "completed", "warning": f"Ingestion failed: {ing_exc}"},
                )
                return

        await _job_store.update(job_id, {"status": "completed"})
        logger.info("shopify_fetch_complete", items=len(all_items))

    except Exception as exc:
        logger.error("shopify_fetch_failed", error=str(exc), store_url=store_url)

        # ── Firecrawl fallback (only when explicitly enabled AND no auth creds) ──
        # We intentionally do NOT fall back to Firecrawl when client_id/secret
        # were provided — a failed auth should surface the error, not mask it.
        if (
            not client_id
            and not client_secret
            and settings
            and settings.USE_FIRECRAWL
            and settings.FIRECRAWL_API_KEY
        ):
            logger.info("triggering_firecrawl_fallback", store_url=store_url)
            await _job_store.update(job_id, {"status": "processing", "fallback": "firecrawl"})
            await run_firecrawl_scrape([base], job_id, settings.FIRECRAWL_API_KEY)
            return

        await _job_store.update(job_id, {"status": "error", "error": str(exc)})




async def fetch_json_feed(url: str) -> dict:
    """Fetch a JSON URL, auto-detect format, return normalised items + detected format."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if not resp.is_success:
            raise ValueError(f"HTTP {resp.status_code} when fetching {url}")
        data = resp.json()

    fmt = _detect_format(data)
    if fmt == "shopify":
        items = _normalize_shopify(data)
    elif fmt == "woocommerce":
        items = _normalize_woocommerce(data)
    elif fmt == "schema_org":
        items = _normalize_schema_org(data)
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


async def run_firecrawl_scrape(urls: List[str], job_id: str, api_key: str) -> None:
    """Background task: Firecrawl-extract product data from each URL."""
    if not await _job_store.get(job_id):
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
                    items.append({
                        "sku": v.get("sku") or str(uuid.uuid4()),
                        "name": v.get("name") or extracted.get("name", ""),
                        "price": _to_cents(v.get("price") or extracted.get("price", 0)),
                        "currency": extracted.get("currency", "USD"),
                        "category": extracted.get("category", "General"),
                        "image_url": v.get("image_url") or extracted.get("image_url"),
                        "product_url": url,
                        "in_stock": v.get("in_stock", True),
                        "features": [],
                        "color": v.get("color"),
                        "size": v.get("size"),
                    })
            else:
                items.append({
                    "sku": extracted.get("sku") or str(uuid.uuid4()),
                    "name": extracted.get("name", ""),
                    "price": _to_cents(extracted.get("price", 0)),
                    "currency": extracted.get("currency", "USD"),
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
