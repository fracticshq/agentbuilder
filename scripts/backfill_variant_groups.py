#!/usr/bin/env python3
"""Backfill provider-neutral variant grouping fields for existing product rows.

Dry-run by default. Use --apply to write changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import urllib.request
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from motor.motor_asyncio import AsyncIOMotorClient


def base_product_url(url: Any) -> str | None:
    if url in (None, ""):
        return None
    try:
        parts = urlsplit(str(url))
        if not parts.scheme or not parts.netloc:
            return re.sub(r"\?.*$", "", str(url)).rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return re.sub(r"\?.*$", "", str(url)).rstrip("/")


def group_key(product_data: dict[str, Any]) -> str | None:
    for key in ("product_group_id", "product_id", "handle"):
        value = product_data.get(key)
        if value not in (None, ""):
            return f"{key}:{str(value).strip().lower()}"
    base_url = base_product_url(product_data.get("product_url") or product_data.get("url") or product_data.get("variant_url"))
    if base_url:
        return f"url:{base_url.lower()}"
    return None


def storefront_json_url(product_data: dict[str, Any]) -> str | None:
    base_url = base_product_url(product_data.get("product_url") or product_data.get("url") or product_data.get("variant_url"))
    if not base_url:
        return None
    parts = urlsplit(base_url)
    if not parts.scheme or not parts.netloc:
        return f"{base_url}.js"
    encoded_path = quote(parts.path, safe="/%")
    return f"{urlunsplit((parts.scheme, parts.netloc, encoded_path, '', ''))}.js"


def fetch_storefront_product(url: str) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except Exception as exc:
        print({"storefront_fetch_failed": url, "error": str(exc)})
        return None


def image_src(image: Any) -> str | None:
    if isinstance(image, dict):
        src = image.get("src") or image.get("url")
        return str(src) if src not in (None, "") else None
    if image not in (None, ""):
        return str(image)
    return None


def option_names(product: dict[str, Any]) -> list[str]:
    names: list[str] = []
    raw_options = product.get("options") or []
    if isinstance(raw_options, list):
        for index, option in enumerate(raw_options, start=1):
            if isinstance(option, dict):
                names.append(str(option.get("name") or f"Option {index}"))
            elif option not in (None, ""):
                names.append(str(option))
    while len(names) < 3:
        names.append(f"Option {len(names) + 1}")
    return names[:3]


def variant_options(variant: dict[str, Any], names: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for index, name in enumerate(names, start=1):
        value = variant.get(f"option{index}")
        if value not in (None, "", "Default Title"):
            options[str(name)] = str(value)
    return options


def variant_image(variant: dict[str, Any], product: dict[str, Any]) -> str | None:
    featured = image_src(variant.get("featured_image") or variant.get("image"))
    if featured:
        return featured

    images = product.get("images") or []
    primary = image_src(images[0]) if images else None
    variant_id = variant.get("id")
    image_id = variant.get("image_id")
    for image in images:
        if not isinstance(image, dict):
            continue
        if image_id not in (None, "") and image.get("id") == image_id:
            return image_src(image) or primary
        image_variant_ids = image.get("variant_ids")
        if variant_id not in (None, "") and isinstance(image_variant_ids, list) and variant_id in image_variant_ids:
            return image_src(image) or primary
    return primary


def build_variant_lookup(product: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for variant in product.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        for key in ("id", "sku"):
            value = variant.get(key)
            if value not in (None, ""):
                lookup[str(value).strip().lower()] = variant
    return lookup


def match_storefront_variant(product_data: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for key in ("variant_id", "variant_sku", "sku", "id"):
        value = product_data.get(key)
        if value not in (None, ""):
            match = lookup.get(str(value).strip().lower())
            if match:
                return match
    return None


def common_name(items: list[dict[str, Any]]) -> str:
    names = [str((item.get("product_data") or {}).get("name") or item.get("title") or "") for item in items]
    names = [name for name in names if name]
    if not names:
        return ""
    prefix = names[0]
    for name in names[1:]:
        while prefix and not name.lower().startswith(prefix.lower()):
            prefix = prefix[:-1]
    return re.sub(r"[\s\-–—/]+$", "", prefix).strip() or names[0]


def variant_title(name: str, parent_name: str, sku: str) -> str:
    if parent_name and name.lower().startswith(parent_name.lower()):
        suffix = re.sub(r"^[\s\-–—/]+", "", name[len(parent_name):]).strip()
        if suffix:
            return suffix
    return sku


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongodb-uri", default=os.getenv("MONGODB_URI"), required=not os.getenv("MONGODB_URI"))
    parser.add_argument("--brand-db", required=True, help="Brand database name")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--hydrate-shopify-json", action="store_true", help="Fetch product_url.js and backfill exact Shopify variant metadata/images.")
    parser.add_argument("--max-groups", type=int, default=0, help="Optional limit for testing hydration.")
    args = parser.parse_args()

    client = AsyncIOMotorClient(args.mongodb_uri)
    collection = client[args.brand_db].knowledge_base
    rows = await collection.find({"content_type": "product", "product_data": {"$exists": True}}).to_list(None)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = group_key(row.get("product_data") or {})
        if key:
            grouped.setdefault(key, []).append(row)

    candidate_groups = {
        key: value
        for key, value in grouped.items()
        if len(value) > 1 or args.hydrate_shopify_json
    }
    updates = 0
    hydrated_groups = 0
    for group_index, (key, items) in enumerate(candidate_groups.items(), start=1):
        if args.max_groups and group_index > args.max_groups:
            break

        storefront_product = None
        storefront_lookup: dict[str, dict[str, Any]] = {}
        storefront_option_names: list[str] = []
        if args.hydrate_shopify_json:
            first_product = (items[0].get("product_data") or {})
            url = storefront_json_url(first_product)
            if url:
                storefront_product = fetch_storefront_product(url)
                if storefront_product and storefront_product.get("variants"):
                    storefront_lookup = build_variant_lookup(storefront_product)
                    storefront_option_names = option_names(storefront_product)
                    hydrated_groups += 1

        parent_name = common_name(items)
        if storefront_product and storefront_product.get("title"):
            parent_name = str(storefront_product["title"])
        prices = [
            float((item.get("product_data") or {}).get("price"))
            for item in items
            if (item.get("product_data") or {}).get("price") not in (None, "")
        ]
        price_min = int(min(prices)) if prices else None
        price_max = int(max(prices)) if prices else None
        default_variant_id = str((items[0].get("product_data") or {}).get("variant_id") or (items[0].get("product_data") or {}).get("sku") or "")

        for item in items:
            product = item.get("product_data") or {}
            sku = str(product.get("sku") or product.get("id") or item.get("_id"))
            title = variant_title(str(product.get("name") or item.get("title") or ""), parent_name, sku)
            storefront_variant = match_storefront_variant(product, storefront_lookup)
            storefront_options = (
                variant_options(storefront_variant, storefront_option_names)
                if storefront_variant and storefront_option_names
                else {}
            )
            storefront_image = (
                variant_image(storefront_variant, storefront_product)
                if storefront_variant and storefront_product
                else None
            )
            storefront_variant_id = (
                str(storefront_variant.get("id"))
                if storefront_variant and storefront_variant.get("id") not in (None, "")
                else None
            )
            set_fields = {
                "product_data.product_group_id": product.get("product_group_id") or key,
                "product_data.parent_name": product.get("parent_name") or parent_name,
                "product_data.has_variants": True,
                "product_data.variant_count": len(items),
                "product_data.price_min": price_min,
                "product_data.price_max": price_max,
                "product_data.default_variant_id": default_variant_id,
                "product_data.variant_id": product.get("variant_id") or storefront_variant_id or sku,
                "product_data.variant_sku": product.get("variant_sku") or sku,
                "product_data.variant_title": product.get("variant_title") or (storefront_variant or {}).get("title") or title,
                "product_data.variant_options": product.get("variant_options") or storefront_options or {"Variant": title},
                "product_data.variant_url": product.get("variant_url") or (
                    f"{base_product_url(product.get('product_url') or product.get('url') or '')}?variant={storefront_variant_id}"
                    if storefront_variant_id and base_product_url(product.get("product_url") or product.get("url") or "")
                    else product.get("product_url") or product.get("url")
                ),
            }
            if storefront_image:
                set_fields["product_data.image_url"] = storefront_image
            updates += 1
            if args.apply:
                await collection.update_one({"_id": item["_id"]}, {"$set": set_fields})

    print({
        "brand_db": args.brand_db,
        "candidate_groups": len(candidate_groups),
        "hydrated_groups": hydrated_groups,
        "rows_to_update": updates,
        "applied": bool(args.apply),
    })
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
