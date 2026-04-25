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

async def fetch_shopify_products(
    store_url: str,
    access_token: Optional[str],
    job_id: str,
) -> None:
    """Background task: paginate Shopify /products.json and store results in job."""
    if not await _job_store.get(job_id):
        return

    base = store_url.strip().rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"

    headers: Dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
        "Accept": "application/json",
    }
    if access_token:
        headers["X-Shopify-Access-Token"] = access_token.strip()

    all_items: List[dict] = []
    try:
        # Use a client without default redirect following to manage it manually and safely
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            page_info: Optional[str] = None
            page = 1
            while True:
                # Use Admin API if token is provided; otherwise public products.json
                # Admin API bypasses storefront password protection
                has_token = bool(access_token and access_token.strip())
                if has_token:
                    url = f"{base}/admin/api/2024-01/products.json?limit=250"
                else:
                    url = f"{base}/products.json?limit=250"

                if page_info:
                    url += f"&page_info={page_info}"

                logger.info("shopify_fetch_page", page=page, url=url, has_token=has_token)
                
                resp = await client.get(url, headers=headers)
                
                # Manual redirect handling
                if resp.is_redirect:
                    location = str(resp.headers.get("Location", ""))
                    logger.info("shopify_fetch_redirect", location=location)
                    
                    if "/password" in location:
                        raise ValueError(
                            "The Shopify store is password-protected. Please go to 'Settings' in your Shopify Admin, "
                            "create a Custom App, and enter the 'Admin API Access Token' (shpat_...) to allow access."
                        )
                    
                    # Follow other redirects (domain changes, etc) once
                    # update url for the next check/fetch
                    url = str(resp.url.join(location))
                    resp = await client.get(url, headers=headers)

                if resp.status_code == 401:
                    raise ValueError(
                        "Store requires an access token (HTTP 401). "
                        "Enable 'Store is private / password-protected?' and enter your Shopify Admin API token."
                    )
                if resp.status_code == 403:
                    raise ValueError(
                        "Access denied (HTTP 403). Ensure your token has the 'read_products' permission."
                    )
                if resp.status_code == 404:
                    raise ValueError(f"Store not found at {base}. Check the URL.")
                resp.raise_for_status()

                data = resp.json()
                products = data.get("products", [])
                if not products:
                    break

                batch = _normalize_shopify(data, base_url=base)
                all_items.extend(batch)
                await _job_store.update(job_id, {"processed": len(all_items), "total": len(all_items)})

                # Cursor-based pagination via Link header
                link = resp.headers.get("Link", "")
                m = re.search(r'<[^>]*page_info=([^&>]+)[^>]*>;\s*rel="next"', link)
                if m:
                    page_info = m.group(1)
                    page += 1
                else:
                    break

        await _job_store.update(job_id, {"items": all_items, "status": "completed", "total": len(all_items)})
        logger.info("shopify_fetch_complete", items=len(all_items))

    except Exception as exc:
        await _job_store.update(job_id, {"status": "error", "error": str(exc)})
        logger.error("shopify_fetch_failed", error=str(exc))


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
