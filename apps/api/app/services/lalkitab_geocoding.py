"""Stateful birthplace resolution for the Lal Kitab runtime.

This module deliberately has no connector or HTTP dependency.  The runtime
injects the connector-backed endpoint caller for every resolution, keeping
tenant-scoped connector policy at the runtime boundary and making the resolver
safe to reuse without cross-turn state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re
from typing import Any

from tools.types import ToolResult

from .context_connector_packs import default_geocoding_config


GEOCODE_SEARCH_ENDPOINT = "geocode_search"
GEOCODE_RESOLVE_ENDPOINT = "geocode_resolve"

COUNTRY_ALIASES = {
    "india": "IN",
    "bharat": "IN",
    "pakistan": "PK",
    "usa": "US",
    "us": "US",
    "united states": "US",
    "america": "US",
    "uk": "GB",
    "england": "GB",
    "britain": "GB",
    "united kingdom": "GB",
    "canada": "CA",
    "australia": "AU",
    "nepal": "NP",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "uae": "AE",
}

# Deliberately excludes bare number words ("one", "two") — they collide with
# natural phrasing like "the Illinois one".
ORDINAL_WORDS = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
}

GeocodeEndpointCaller = Callable[
    [dict[str, Any], str, dict[str, Any], str],
    Awaitable[ToolResult | None],
]


def get_geocoding_config(connector: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a connector's geocoding overrides onto the built-in defaults."""
    config = default_geocoding_config()
    input_resolution = (connector or {}).get("input_resolution")
    overrides = input_resolution.get("geocoding") if isinstance(input_resolution, dict) else None
    if isinstance(overrides, dict):
        config.update({key: value for key, value in overrides.items() if value is not None})
    return config


def _country_hint_from_text(text: str) -> str | None:
    lowered = (text or "").lower()
    for alias, code in COUNTRY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return code
    iso = re.search(r"\b([A-Z]{2})\b", text or "")
    if iso and iso.group(1) in {code for code in COUNTRY_ALIASES.values()}:
        return iso.group(1)
    return None


def candidate_label(candidate: dict[str, Any]) -> str:
    parts = [candidate.get("name")]
    if candidate.get("adminRegion"):
        parts.append(candidate.get("adminRegion"))
    if candidate.get("country"):
        parts.append(candidate.get("country"))
    return ", ".join(part for part in parts if part)


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "placeId": candidate.get("placeId"),
        "name": candidate.get("name"),
        "adminRegion": candidate.get("adminRegion"),
        "country": candidate.get("country"),
        "countryCode": candidate.get("countryCode"),
        "latitude": candidate.get("latitude"),
        "longitude": candidate.get("longitude"),
        "timezone": candidate.get("timezone"),
        "population": candidate.get("population"),
        "label": candidate_label(candidate),
    }


def _filter_candidates_by_hint(candidates: list[dict[str, Any]], hint_text: str) -> list[dict[str, Any]]:
    """Keep candidates matching a country/region token mentioned by the user."""
    country_code = _country_hint_from_text(hint_text)
    lowered = (hint_text or "").lower()
    if country_code:
        narrowed = [candidate for candidate in candidates if str(candidate.get("countryCode")).upper() == country_code]
        if narrowed:
            return narrowed
    # Region/state token match (e.g. "Hyderabad Telangana").
    region_matches = [
        candidate
        for candidate in candidates
        if candidate.get("adminRegion")
        and re.search(rf"\b{re.escape(str(candidate.get('adminRegion')).lower())}\b", lowered)
    ]
    if region_matches:
        return region_matches
    return candidates


def match_place_choice(message: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Interpret a follow-up reply as a selection among pending place candidates."""
    if not candidates:
        return None
    lowered = (message or "").lower().strip()
    # 1) Country / region / name token match — the strongest signal.
    narrowed = _filter_candidates_by_hint(candidates, message)
    if len(narrowed) == 1:
        return narrowed[0]
    for candidate in candidates:
        for key in ("country", "adminRegion", "placeId"):
            value = str(candidate.get(key) or "").lower()
            if value and value in lowered:
                return candidate
    # 2) Explicit numeric selection ("2").
    number = re.search(r"\b(\d{1,2})\b", lowered)
    if number:
        index = int(number.group(1)) - 1
        if 0 <= index < len(candidates):
            return candidates[index]
    # 3) Ordinal words ("the second one").
    for word, index in ORDINAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered) and index < len(candidates):
            return candidates[index]
    return None


def format_place_disambiguation(birth_place: str, candidates: list[dict[str, Any]]) -> str:
    options = "\n".join(
        f"{index + 1}. {candidate.get('label')}" for index, candidate in enumerate(candidates)
    )
    return (
        f"There are a few places named \"{birth_place}\". Which one is the birthplace?\n{options}\n"
        "Reply with the number or the country/state."
    )


async def resolve_birthplace_via_geocoding(
    *,
    connector: dict[str, Any],
    geocoding_cfg: dict[str, Any],
    birth_place: str,
    datetime_iso: str | None,
    message: str,
    call_endpoint: GeocodeEndpointCaller,
) -> dict[str, Any]:
    """Resolve a birthplace string to coordinates + timezone.

    Returns a dict with `status` in {"resolved", "ambiguous", "failed"} and
    accompanying data (coordinates/timezone, or candidate list, plus events).
    """
    events: list[dict[str, Any]] = []
    search_id = geocoding_cfg.get("search_endpoint_id") or GEOCODE_SEARCH_ENDPOINT
    resolve_id = geocoding_cfg.get("resolve_endpoint_id") or GEOCODE_RESOLVE_ENDPOINT
    max_candidates = int(geocoding_cfg.get("max_candidates") or 5)

    events.append({
        "type": "geocode_start",
        "content": "Resolving birthplace…",
        "metadata": {"endpoint_id": search_id},
    })
    search_result = await call_endpoint(
        connector, search_id, {"q": birth_place, "limit": max_candidates}, message
    )
    if not search_result or not search_result.success:
        events.append({
            "type": "geocode_result",
            "content": "I couldn’t verify that birthplace right now.",
            "metadata": {"success": False},
        })
        return {"status": "failed", "events": events}

    raw_results = []
    data = search_result.data if isinstance(search_result.data, dict) else {}
    if isinstance(data.get("results"), list):
        raw_results = [candidate for candidate in data["results"] if isinstance(candidate, dict) and candidate.get("placeId")]
    candidates = [_normalize_candidate(candidate) for candidate in raw_results]
    if not candidates:
        events.append({
            "type": "geocode_result",
            "content": "I couldn’t find a matching birthplace.",
            "metadata": {"success": True, "count": 0},
        })
        return {"status": "failed", "events": events}

    # 1) Narrow by any country/region token the user already gave.
    narrowed = _filter_candidates_by_hint(candidates, message)
    # 2) Apply the configured default-country bias if still ambiguous.
    default_country = str(geocoding_cfg.get("default_country") or "").upper()
    if len(narrowed) > 1 and default_country:
        biased = [candidate for candidate in narrowed if str(candidate.get("countryCode")).upper() == default_country]
        if len(biased) == 1:
            narrowed = biased

    if len(narrowed) > 1:
        strategy = str(geocoding_cfg.get("ambiguous_strategy") or "ask").lower()
        if strategy == "highest_population" or geocoding_cfg.get("confirm_when_ambiguous") is False:
            narrowed = [max(narrowed, key=lambda candidate: candidate.get("population") or 0)]
        else:
            top = narrowed[:max_candidates]
            events.append({
                "type": "geocode_result",
                "content": f"I found {len(top)} possible birthplaces and need your choice.",
                "metadata": {"success": True, "ambiguous": True, "count": len(top)},
            })
            return {"status": "ambiguous", "candidates": top, "events": events}

    return await finalize_geocode_choice(
        connector=connector,
        resolve_id=resolve_id,
        candidate=narrowed[0],
        datetime_iso=datetime_iso,
        message=message,
        events=events,
        call_endpoint=call_endpoint,
    )


async def finalize_geocode_choice(
    *,
    connector: dict[str, Any],
    resolve_id: str,
    candidate: dict[str, Any],
    datetime_iso: str | None,
    message: str,
    events: list[dict[str, Any]],
    call_endpoint: GeocodeEndpointCaller,
) -> dict[str, Any]:
    """Resolve a chosen place into coordinates + (historical) timezone offset."""
    latitude = candidate.get("latitude")
    longitude = candidate.get("longitude")
    timezone_offset: str | None = None
    resolve_payload = {"placeId": candidate.get("placeId")}
    if datetime_iso:
        resolve_payload["birthDate"] = datetime_iso
    resolve_result = await call_endpoint(connector, resolve_id, resolve_payload, message)
    if resolve_result and resolve_result.success and isinstance(resolve_result.data, dict):
        place = resolve_result.data.get("place") if isinstance(resolve_result.data.get("place"), dict) else {}
        tz_at_birth = (
            resolve_result.data.get("timezoneAtBirth")
            if isinstance(resolve_result.data.get("timezoneAtBirth"), dict)
            else {}
        )
        latitude = place.get("latitude", latitude)
        longitude = place.get("longitude", longitude)
        timezone_offset = tz_at_birth.get("utcOffsetString") or timezone_offset

    if timezone_offset is None and candidate.get("timezone"):
        # Fall back to the IANA zone's offset only if the resolve endpoint gave none.
        timezone_offset = _iana_to_offset(str(candidate.get("timezone")))

    if latitude is None or longitude is None or not timezone_offset:
        events.append({
            "type": "geocode_result",
            "content": "I couldn’t verify the timezone for that birthplace.",
            "metadata": {"success": False},
        })
        return {"status": "failed", "events": events}

    events.append({
        "type": "geocode_result",
        "content": "Birthplace resolved.",
        "metadata": {"success": True},
    })
    return {
        "status": "resolved",
        "latitude": float(latitude),
        "longitude": float(longitude),
        "timezone": timezone_offset,
        "label": candidate.get("label"),
        "events": events,
    }


def _iana_to_offset(iana_zone: str) -> str | None:
    """Best-effort IANA → fixed offset for the few zones we ship offline."""
    static = {
        "Asia/Kolkata": "+05:30",
        "Asia/Calcutta": "+05:30",
        "Asia/Karachi": "+05:00",
        "Asia/Kathmandu": "+05:45",
        "Asia/Dhaka": "+06:00",
        "Asia/Colombo": "+05:30",
        "UTC": "+00:00",
    }
    return static.get(iana_zone)
