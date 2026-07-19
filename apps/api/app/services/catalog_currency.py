"""Pure catalog price and currency normalization helpers.

This module deliberately has no service, database, or network dependencies so
catalog and knowledge paths can share its deterministic rules safely.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional


def to_cents(value: Any) -> int:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def price_amount(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("amount") or value.get("value") or value.get("price") or 0
    return value


def normalize_currency(value: Any) -> Optional[str]:
    if value is None:
        return None
    currency = str(value).strip()
    return currency.upper() if currency else None


def normalize_currency_code(value: Any, *, allow_empty: bool = True) -> Optional[str]:
    """Normalize an explicit ISO-style three-letter currency code."""
    currency = normalize_currency(value)
    if not currency and allow_empty:
        return None
    if not currency or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a three-letter code such as INR, USD, or EUR.")
    return currency


def extract_catalog_currency(*sources: Optional[Dict[str, Any]]) -> Optional[str]:
    for source in sources:
        if not isinstance(source, dict):
            continue

        for key in ("currency", "currencyCode", "currency_code", "price_currency", "priceCurrency"):
            currency = normalize_currency(source.get(key))
            if currency:
                return currency

        for price_key in ("price", "priceV2", "compare_at_price", "compareAtPrice"):
            price = source.get(price_key)
            if isinstance(price, dict):
                currency = extract_catalog_currency(price)
                if currency:
                    return currency

        presentment_prices = source.get("presentment_prices")
        if isinstance(presentment_prices, list):
            for presentment in presentment_prices:
                if not isinstance(presentment, dict):
                    continue
                currency = extract_catalog_currency(presentment.get("price"), presentment)
                if currency:
                    return currency

    return None


def currency_with_source(
    *catalog_sources: Optional[Dict[str, Any]],
    shopify_currency: Optional[str] = None,
    fallback_currency: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Resolve catalog currency with Shopify store currency taking priority."""
    authoritative_currency = normalize_currency(shopify_currency)
    if authoritative_currency:
        return authoritative_currency, "shopify_store"

    catalog_currency = extract_catalog_currency(*catalog_sources)
    if catalog_currency:
        return catalog_currency, "catalog"

    configured_currency = normalize_currency(fallback_currency)
    if configured_currency:
        return configured_currency, "configured_default"

    return None, "missing"
