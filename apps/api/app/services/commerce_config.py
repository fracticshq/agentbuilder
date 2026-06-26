"""Commerce configuration normalization helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


COMMERCE_DEFAULTS: dict[str, Any] = {
    "default_currency": None,
    "currency_policy": "catalog_first_config_fallback",
    "display_policy": {
        "source_display_policy": "cards_only",
        "show_sources": False,
        "show_product_cards": True,
        "cards_only": True,
    },
    "retrieval": {
        "enabled": True,
        "fusion": "rrf",
        "rrf_k": 60,
        "max_cards": 5,
        "max_product_cards": 5,
        "self_crag_enabled": True,
        "max_retries": 2,
        "include_out_of_stock": False,
    },
    "taxonomy": {
        "source": "catalog",
        "category_field": "category",
        "product_type_field": "product_type",
        "tags_field": "tags",
    },
}

COMMERCE_TEMPLATES = {"ecommerce", "ecommerce_sales", "shopify"}


def is_commerce_agent_config(config: dict[str, Any] | None) -> bool:
    config = config or {}
    domain = config.get("domain") or {}
    template = str(
        config.get("agent_template")
        or config.get("template")
        or domain.get("template")
        or domain.get("type")
        or ""
    ).lower()
    return (
        config.get("data_source") == "shopify"
        or bool(config.get("shopify"))
        or bool(config.get("commerce"))
        or template in COMMERCE_TEMPLATES
    )


def normalize_commerce_config(
    commerce: dict[str, Any] | None,
    *,
    public_widget_projection: bool = False,
) -> dict[str, Any]:
    """Merge commerce config with provider-neutral defaults."""
    normalized = _deep_merge(COMMERCE_DEFAULTS, commerce if isinstance(commerce, dict) else {})
    display_policy = normalized["display_policy"]
    cards_only = display_policy.get("source_display_policy") == "cards_only" or bool(display_policy.get("cards_only", False))
    display_policy["source_display_policy"] = display_policy.get("source_display_policy") or ("cards_only" if cards_only else "hide_sources")
    display_policy["cards_only"] = cards_only
    display_policy["show_sources"] = False if cards_only else bool(display_policy.get("show_sources", False))
    display_policy["show_product_cards"] = bool(display_policy.get("show_product_cards", True))

    if public_widget_projection:
        display_policy["source_display_policy"] = "cards_only"
        display_policy["cards_only"] = True
        display_policy["show_sources"] = False
        display_policy["show_product_cards"] = True

    return normalized


def normalize_commerce_configuration(
    config: dict[str, Any] | None,
    *,
    public_widget_projection: bool = False,
) -> dict[str, Any]:
    """Return a copy of an agent config with commerce defaults for commerce agents."""
    normalized = deepcopy(config or {})
    if not is_commerce_agent_config(normalized):
        return normalized

    normalized["commerce"] = normalize_commerce_config(
        normalized.get("commerce"),
        public_widget_projection=public_widget_projection,
    )
    return normalized


def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif value is not None:
            merged[key] = deepcopy(value)
    return merged
