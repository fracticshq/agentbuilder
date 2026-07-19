"""Pure normalization helpers for commerce response metadata."""

import json
import re
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from .commerce_config import is_commerce_agent_config


def _normalize_commerce_product_currency(product: dict, agent_config: dict | None) -> dict:
    """Apply configured commerce currency policy before products leave the API."""
    if not isinstance(product, dict) or not is_commerce_agent_config(agent_config or {}):
        return product

    commerce = (agent_config or {}).get("commerce") or {}
    default_currency = str(commerce.get("default_currency") or "").strip().upper() or None
    policy = str(commerce.get("currency_policy") or "catalog_first_config_fallback").strip().lower()
    catalog_currency = (
        str(product.get("currency")).strip().upper()
        if product.get("currency") not in (None, "") and str(product.get("currency")).strip()
        else None
    )
    catalog_source = str(product.get("currency_source") or "").strip().lower()

    normalized = dict(product)
    if catalog_currency and catalog_source == "shopify_store":
        normalized["currency"] = catalog_currency
        normalized["currency_source"] = "shopify_store"
        return normalized
    if policy == "default_only":
        normalized["currency"] = default_currency
        normalized["currency_source"] = "commerce.default_currency" if default_currency else "missing"
        return normalized

    if catalog_currency:
        normalized["currency"] = catalog_currency
        normalized["currency_source"] = normalized.get("currency_source") or "product"
        return normalized

    if policy != "catalog_only" and default_currency:
        normalized["currency"] = default_currency
        normalized["currency_source"] = "commerce.default_currency"
        return normalized

    normalized["currency"] = None
    normalized["currency_source"] = "missing"
    return normalized


def _normalize_commerce_products_currency(products: list[dict], agent_config: dict | None) -> list[dict]:
    return [_canonicalize_commerce_product(_normalize_commerce_product_currency(product, agent_config)) for product in products]


def _canonicalize_commerce_product(product: dict) -> dict:
    """Normalize provider aliases into the widget's explicit minor-unit contract."""
    if not isinstance(product, dict):
        return product
    normalized = dict(product)
    if normalized.get("price_minor") is None and normalized.get("price") not in (None, ""):
        try:
            normalized["price_minor"] = int(round(float(normalized["price"])))
        except (TypeError, ValueError):
            normalized["price_minor"] = None
    normalized["price_unit"] = "minor"
    normalized["image_url"] = normalized.get("image_url") or normalized.get("image")
    normalized["product_url"] = normalized.get("product_url") or normalized.get("url")
    if normalized.get("currency_source") == "product":
        normalized["currency_source"] = "catalog"
    variants = normalized.get("variants")
    if isinstance(variants, list):
        normalized["variants"] = [_canonicalize_commerce_product(variant) for variant in variants if isinstance(variant, dict)]
    return normalized


def _safe_commerce_cart(
    agent_metadata: dict,
    tool_results: dict,
    previous: Optional[dict] = None,
    allowed_shop_url: Optional[str] = None,
) -> Optional[dict]:
    """Build one safe cart shape for sync, streaming, and persisted history."""
    state = dict(previous or {})
    for key in ("cart_id", "checkout_url", "cart_lines"):
        if agent_metadata.get(key) not in (None, ""):
            state[key] = agent_metadata[key]
    for tool_result in tool_results.values() if isinstance(tool_results, dict) else []:
        metadata = getattr(tool_result, "metadata", {}) or {}
        action = metadata.get("commerce_action") if isinstance(metadata.get("commerce_action"), dict) else {}
        cart = action.get("cart") if isinstance(action.get("cart"), dict) else metadata.get("cart")
        if not isinstance(cart, dict):
            continue
        for target, keys in {
            "cart_id": ("cart_id", "cartId", "id"),
            "checkout_url": ("checkout_url", "checkoutUrl"),
            "cart_lines": ("cart_lines", "lines", "line_items"),
        }.items():
            for key in keys:
                if cart.get(key) not in (None, ""):
                    state[target] = cart[key]
                    break
    if state.get("checkout_url"):
        try:
            parsed = urlsplit(str(state["checkout_url"]))
            allowed_host = urlsplit(str(allowed_shop_url)).hostname if allowed_shop_url else None
            if parsed.scheme != "https" or not parsed.hostname or (allowed_host and parsed.hostname != allowed_host):
                state["checkout_url"] = None
            else:
                state["checkout_url"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        except Exception:
            state["checkout_url"] = None
    if not isinstance(state.get("cart_lines"), list):
        state["cart_lines"] = []
    return state if any(state.get(key) for key in ("cart_id", "checkout_url", "cart_lines")) else None


def _base_product_url(url: Any) -> Optional[str]:
    if url in (None, ""):
        return None
    try:
        parts = urlsplit(str(url))
        if not parts.scheme or not parts.netloc:
            return re.sub(r"\?.*$", "", str(url)).rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except Exception:
        return re.sub(r"\?.*$", "", str(url)).rstrip("/")


def _commerce_product_group_key(product: dict) -> Optional[str]:
    for key in ("product_group_id", "product_id", "handle"):
        value = product.get(key)
        if value not in (None, ""):
            return f"{key}:{str(value).strip().lower()}"
    base_url = _base_product_url(product.get("product_url") or product.get("url") or product.get("variant_url"))
    if base_url:
        return f"url:{base_url.lower()}"
    return None


def _commerce_variant_identity(product: dict) -> Optional[str]:
    for key in ("variant_id", "variant_sku", "sku", "variant_url", "id"):
        value = product.get(key)
        if value not in (None, ""):
            return re.sub(r"\s+", " ", str(value).strip().lower())
    return None


def _variant_rank(product: dict, default: int = 9999) -> int:
    try:
        return int(product.get("_variant_rank"))
    except (TypeError, ValueError):
        return default


def _common_product_name(products: list[dict]) -> str:
    parent_names = [str(product.get("parent_name")) for product in products if product.get("parent_name")]
    if parent_names:
        return parent_names[0]
    names = [str(product.get("name") or product.get("title") or "") for product in products if product.get("name") or product.get("title")]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    prefix = names[0]
    for name in names[1:]:
        while prefix and not name.lower().startswith(prefix.lower()):
            prefix = prefix[:-1]
    return re.sub(r"[\s\-–—/]+$", "", prefix).strip() or names[0]


def _variant_label(product: dict, parent_name: str) -> str:
    explicit = product.get("variant_title")
    if explicit not in (None, "", "Default Title"):
        return str(explicit)
    name = str(product.get("name") or product.get("title") or "")
    if parent_name and name.lower().startswith(parent_name.lower()):
        suffix = re.sub(r"^[\s\-–—/]+", "", name[len(parent_name):]).strip()
        if suffix:
            return suffix
    return str(product.get("variant_sku") or product.get("sku") or product.get("variant_id") or "Variant")


def _commerce_variant_from_product(product: dict, selected: dict, parent_name: str) -> dict:
    variant_options = product.get("variant_options")
    if not isinstance(variant_options, dict) or not variant_options:
        variant_options = {"Variant": _variant_label(product, parent_name)}
    return {
        "id": product.get("variant_id") or product.get("id") or product.get("sku"),
        "variant_id": product.get("variant_id") or product.get("id") or product.get("sku"),
        "sku": product.get("variant_sku") or product.get("sku"),
        "variant_sku": product.get("variant_sku") or product.get("sku"),
        "name": product.get("name"),
        "title": product.get("variant_title") or _variant_label(product, parent_name),
        "variant_title": product.get("variant_title") or _variant_label(product, parent_name),
        "variant_options": variant_options,
        "price": product.get("price"),
        "currency": product.get("currency"),
        "currency_source": product.get("currency_source"),
        "image_url": product.get("image_url") or product.get("image"),
        "image": product.get("image") or product.get("image_url"),
        "product_url": product.get("product_url") or product.get("url"),
        "variant_url": product.get("variant_url") or product.get("product_url") or product.get("url"),
        "in_stock": product.get("in_stock", True),
        "is_default": _commerce_variant_identity(product) == _commerce_variant_identity(selected),
    }


def _group_commerce_products_for_cards(products: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    passthrough: list[dict] = []
    for index, product in enumerate(products):
        if not isinstance(product, dict):
            continue
        variants = product.get("variants")
        if isinstance(variants, list) and len(variants) > 1:
            passthrough.append(product)
            continue
        group_key = _commerce_product_group_key(product)
        if not group_key:
            passthrough.append(product)
            continue
        product_copy = dict(product)
        product_copy["_variant_rank"] = index
        if group_key not in groups:
            groups[group_key] = []
            order.append(group_key)
        groups[group_key].append(product_copy)

    grouped_products: list[dict] = []
    for group_key in order:
        group_products = groups[group_key]
        if len(group_products) == 1:
            product = dict(group_products[0])
            product.pop("_variant_rank", None)
            grouped_products.append(product)
            continue

        group_products = _deduplicate_entities(
            group_products,
            "variant_id",
            "variant_sku",
            "sku",
            "variant_url",
            "id",
        )
        selected = min(
            group_products,
            key=lambda product: (
                _variant_rank(product),
                0 if product.get("in_stock", True) else 1,
                float(product.get("price") or 10**18),
            ),
        )
        group_products = sorted(
            group_products,
            key=lambda product: (
                0 if _commerce_variant_identity(product) == _commerce_variant_identity(selected) else 1,
                _variant_rank(product),
                0 if product.get("in_stock", True) else 1,
                float(product.get("price") or 10**18),
                _commerce_variant_identity(product) or "",
            ),
        )
        parent_name = _common_product_name(group_products)
        variants = [_commerce_variant_from_product(product, selected, parent_name) for product in group_products]
        prices = [float(variant["price"]) for variant in variants if variant.get("price") not in (None, "")]
        card = dict(selected)
        card["product_group_id"] = selected.get("product_group_id") or group_key
        card["name"] = parent_name or selected.get("name") or selected.get("title") or "Product"
        card["title"] = card["name"]
        card["has_variants"] = True
        card["variant_count"] = max(int(selected.get("variant_count") or 0), len(variants))
        card["variants"] = variants
        card["default_variant_id"] = selected.get("variant_id") or selected.get("id") or selected.get("sku")
        if prices:
            card["price_min"] = min(prices)
            card["price_max"] = max(prices)
        card.pop("_variant_rank", None)
        grouped_products.append(card)

    return [*grouped_products, *passthrough]


def _prepare_commerce_products_for_response(products: list[dict], agent_config: dict | None) -> list[dict]:
    normalized = _normalize_commerce_products_currency(products, agent_config)
    return _group_commerce_products_for_cards(normalized)


def _entity_identity(entity: dict, *keys: str) -> Optional[str]:
    """Build a stable identity string from the first populated key."""
    for key in keys:
        value = entity.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return f"{key}:{normalized}"
    return None


def _deduplicate_entities(entities: list[dict], *identity_keys: str) -> list[dict]:
    """Deduplicate metadata entities while tolerating inconsistent provider schemas."""
    unique_entities: list[dict] = []
    seen_keys: set[str] = set()

    for entity in entities:
        identity = _entity_identity(entity, *identity_keys)
        if identity is None:
            identity = f"json:{json.dumps(entity, sort_keys=True, default=str)}"

        if identity in seen_keys:
            continue

        seen_keys.add(identity)
        unique_entities.append(entity)

    return unique_entities
