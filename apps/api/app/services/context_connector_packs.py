from __future__ import annotations

from copy import deepcopy
from typing import Any


LAL_KITAB_ENDPOINTS = (
    ("lalkitab_chart", "Lal Kitab Chart", "Fetch calculated Lal Kitab chart context."),
    ("lalkitab_debts", "Lal Kitab Debts", "Fetch Lal Kitab debt and karmic obligation context."),
    ("lalkitab_houses", "Lal Kitab Houses", "Fetch Lal Kitab house interpretation context."),
    ("lalkitab_lucky", "Lal Kitab Lucky Factors", "Fetch lucky colors, numbers, timing, and favorable factors."),
    ("lalkitab_predictions", "Lal Kitab Predictions", "Fetch calculated Lal Kitab prediction context."),
    ("lalkitab_remedies", "Lal Kitab Remedies", "Fetch Lal Kitab remedy recommendations from Vedika."),
    ("lalkitab_totke", "Lal Kitab Totke", "Fetch Lal Kitab totke/remedial actions from Vedika."),
    ("lalkitab_varshphal", "Lal Kitab Varshphal", "Fetch Lal Kitab annual chart/varshphal context."),
)


def _vedika_endpoint(endpoint_id: str, name: str, description: str) -> dict[str, Any]:
    slug = endpoint_id.replace("lalkitab_", "")
    is_chart = endpoint_id == "lalkitab_chart"
    return {
        "id": endpoint_id,
        "name": name,
        "enabled": True,
        "method": "POST",
        "url_template": f"https://api.vedika.io/v2/astrology/lalkitab/{slug}",
        "url": f"https://api.vedika.io/v2/astrology/lalkitab/{slug}",
        "execution_order": 1 if is_chart else 2,
        "requires_prior_endpoint": None if is_chart else "lalkitab_chart",
        "payload_mode": "flat_body",
        "timeout_seconds": 45,
        "retry_count": 1,
        "max_response_chars": 50000,
        "field_mapping": {
            "birth_date": "date",
            "birth_time": "time",
        },
        "required_user_fields": ["birth_date", "birth_time", "birth_place"],
        "required_fields": ["birth_date", "birth_time", "birth_place"],
        "runtime_required_fields": ["datetime", "latitude", "longitude", "timezone"],
        "body_schema": {
            "type": "object",
            "properties": {
                "datetime": {"type": "string", "description": "Birth datetime in ISO format, for example 1990-05-15T10:30:00."},
                "latitude": {"type": "number", "description": "Birthplace latitude."},
                "longitude": {"type": "number", "description": "Birthplace longitude."},
                "timezone": {"type": "string", "description": "Timezone offset, for example +05:30."},
                "language": {"type": "string"},
            },
            "required": ["datetime", "latitude", "longitude", "timezone"],
        },
        "response_mapping": {},
        "tool_description": description,
        "description": description,
    }


def _vedika_geocode_search_endpoint() -> dict[str, Any]:
    """Geocode birthplace text into candidate places (ambiguity signal via result count)."""
    return {
        "id": "geocode_search",
        "name": "Vedika Geocode Search",
        "enabled": True,
        "method": "GET",
        "url_template": "https://api.vedika.io/v2/geocode/search",
        "url": "https://api.vedika.io/v2/geocode/search",
        "execution_order": 0,
        "payload_mode": "flat_body",
        "field_mapping": {},
        "runtime_required_fields": ["q"],
        "body_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Birthplace text to geocode, for example 'Hyderabad'."},
                "country": {"type": "string", "description": "Optional ISO country code bias, for example 'IN'."},
                "limit": {"type": "number", "description": "Maximum candidate results to return."},
            },
            "required": ["q"],
        },
        "tool_description": "Resolve a birthplace string into candidate places with coordinates and timezone.",
        "description": "Vedika geocoding search endpoint.",
    }


def _vedika_geocode_resolve_endpoint() -> dict[str, Any]:
    """Resolve a chosen placeId + birth datetime into precise coordinates and historical timezone."""
    return {
        "id": "geocode_resolve",
        "name": "Vedika Geocode Resolve",
        "enabled": True,
        "method": "GET",
        "url_template": "https://api.vedika.io/v2/geocode/resolve",
        "url": "https://api.vedika.io/v2/geocode/resolve",
        "execution_order": 0,
        "payload_mode": "flat_body",
        "field_mapping": {},
        "runtime_required_fields": ["placeId"],
        "body_schema": {
            "type": "object",
            "properties": {
                "placeId": {"type": "string", "description": "Place id returned by geocode_search."},
                "birthDate": {"type": "string", "description": "Birth datetime in ISO format for historical timezone resolution."},
            },
            "required": ["placeId"],
        },
        "tool_description": "Resolve a placeId and birth datetime into coordinates and the historical timezone at birth.",
        "description": "Vedika geocoding resolve endpoint.",
    }


BUILT_IN_CONNECTOR_PACKS: dict[str, dict[str, Any]] = {
    "vedika_lal_kitab": {
        "id": "vedika_lal_kitab",
        "name": "Vedika Lal Kitab",
        "type": "http_api",
        "enabled": True,
        "auth": {"type": "bearer"},
        "domain_allowlist": ["api.vedika.io"],
        "input_resolution": {
            "resolve_known_places": True,
            "confirm_understood_details": True,
            "missing_input_strategy": "ask_follow_up",
            "geocoding": {
                "enabled": True,
                "search_endpoint_id": "geocode_search",
                "resolve_endpoint_id": "geocode_resolve",
                "default_country": "IN",
                "confirm_when_ambiguous": True,
                # When multiple candidates remain after the default-country bias,
                # ask the user to choose. Set to "highest_population" to auto-pick instead.
                "ambiguous_strategy": "ask",
                "max_candidates": 5,
            },
        },
        "usage_policy": (
            "Use only for calculated Lal Kitab, Vedic Jyotish chart, remedy, prediction, "
            "lucky factor, totke, debts, houses, and varshphal context. Build the Lal Kitab "
            "chart first, then call relevant secondary endpoints. Ask for missing birth inputs "
            "before calling; if birthplace cannot be resolved, ask for the nearest major city "
            "or latitude, longitude, and timezone."
        ),
        "safety_policy": {
            "required_input_policy": "Ask for birth date, birth time, and birth place before chart-specific guidance. Resolve known birthplaces automatically; if birthplace cannot be resolved, ask for the nearest major city or latitude, longitude, and timezone.",
            "do_not_fabricate": "Never invent chart placements, debts, remedies, predictions, or varshphal output.",
            "source_limits": "Distinguish API-calculated facts from interpretive guidance and cite knowledge context separately.",
        },
        "endpoints": [
            _vedika_endpoint(endpoint_id, name, description)
            for endpoint_id, name, description in LAL_KITAB_ENDPOINTS
        ]
        + [
            _vedika_geocode_search_endpoint(),
            _vedika_geocode_resolve_endpoint(),
        ],
    }
}


def built_in_geocode_endpoints() -> list[dict[str, Any]]:
    """Built-in Vedika geocoding endpoints, for runtime-merging into a stored connector."""
    return [
        deepcopy(_vedika_geocode_search_endpoint()),
        deepcopy(_vedika_geocode_resolve_endpoint()),
    ]


def default_geocoding_config() -> dict[str, Any]:
    """Default geocoding input-resolution block used when a connector omits one."""
    return deepcopy(
        BUILT_IN_CONNECTOR_PACKS["vedika_lal_kitab"]["input_resolution"]["geocoding"]
    )


def list_connector_packs() -> list[dict[str, Any]]:
    return [deepcopy(pack) for pack in BUILT_IN_CONNECTOR_PACKS.values()]


def get_connector_pack(pack_id: str) -> dict[str, Any] | None:
    pack = BUILT_IN_CONNECTOR_PACKS.get(pack_id)
    return deepcopy(pack) if pack else None
