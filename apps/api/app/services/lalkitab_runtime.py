from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any

from tools.types import ToolResult

from .context_connector_packs import built_in_geocode_endpoints, default_geocoding_config
from .tool_registry import ContextConnectorTool


LAL_KITAB_TEMPLATE = "astrology_lalkitab"
LAL_KITAB_CHART_ENDPOINT = "lalkitab_chart"
LAL_KITAB_SECONDARY_ENDPOINTS = (
    "lalkitab_debts",
    "lalkitab_houses",
    "lalkitab_lucky",
    "lalkitab_predictions",
    "lalkitab_remedies",
    "lalkitab_totke",
    "lalkitab_varshphal",
)

CITY_GEO_LOOKUP = {
    "delhi": {"latitude": 28.6139, "longitude": 77.2090, "timezone": "+05:30", "label": "Delhi, India"},
    "new delhi": {"latitude": 28.6139, "longitude": 77.2090, "timezone": "+05:30", "label": "New Delhi, India"},
    "mumbai": {"latitude": 19.0760, "longitude": 72.8777, "timezone": "+05:30", "label": "Mumbai, India"},
    "bombay": {"latitude": 19.0760, "longitude": 72.8777, "timezone": "+05:30", "label": "Mumbai, India"},
    "bangalore": {"latitude": 12.9716, "longitude": 77.5946, "timezone": "+05:30", "label": "Bengaluru, India"},
    "bengaluru": {"latitude": 12.9716, "longitude": 77.5946, "timezone": "+05:30", "label": "Bengaluru, India"},
    "chennai": {"latitude": 13.0827, "longitude": 80.2707, "timezone": "+05:30", "label": "Chennai, India"},
    "kolkata": {"latitude": 22.5726, "longitude": 88.3639, "timezone": "+05:30", "label": "Kolkata, India"},
    "calcutta": {"latitude": 22.5726, "longitude": 88.3639, "timezone": "+05:30", "label": "Kolkata, India"},
    "hyderabad": {"latitude": 17.3850, "longitude": 78.4867, "timezone": "+05:30", "label": "Hyderabad, India"},
    "pune": {"latitude": 18.5204, "longitude": 73.8567, "timezone": "+05:30", "label": "Pune, India"},
    "jaipur": {"latitude": 26.9124, "longitude": 75.7873, "timezone": "+05:30", "label": "Jaipur, India"},
    "ahmedabad": {"latitude": 23.0225, "longitude": 72.5714, "timezone": "+05:30", "label": "Ahmedabad, India"},
    "lucknow": {"latitude": 26.8467, "longitude": 80.9462, "timezone": "+05:30", "label": "Lucknow, India"},
}


GEOCODE_SEARCH_ENDPOINT = "geocode_search"
GEOCODE_RESOLVE_ENDPOINT = "geocode_resolve"


@dataclass
class LalKitabPlanResult:
    handled: bool = False
    missing_input: list[str] = field(default_factory=list)
    clarification: str = ""
    normalized_birth_input: dict[str, Any] = field(default_factory=dict)
    selected_endpoint_ids: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    api_context: dict[str, Any] = field(default_factory=dict)
    tool_results: dict[str, ToolResult] = field(default_factory=dict)
    # Birthplace disambiguation: when the geocoder returns multiple plausible
    # places, we pause and ask the user to choose one.
    awaiting_place_choice: bool = False
    place_candidates: list[dict[str, Any]] = field(default_factory=list)
    # Accumulated state to carry across turns (merged birth input + pending place).
    pending_state: dict[str, Any] = field(default_factory=dict)
    # True when this turn can answer from previously calculated chart/API
    # context without calling Vedika again.
    used_cached_context: bool = False


def is_lalkitab_agent(config: dict[str, Any] | None) -> bool:
    config = config or {}
    domain = config.get("domain") if isinstance(config.get("domain"), dict) else {}
    return (
        domain.get("template") == LAL_KITAB_TEMPLATE
        or config.get("agent_template") == LAL_KITAB_TEMPLATE
        or config.get("template") == LAL_KITAB_TEMPLATE
    )


def message_requires_lalkitab_api(message: str) -> bool:
    text = (message or "").lower()
    intent_terms = (
        "chart",
        "birth",
        "born",
        "dob",
        "date of birth",
        "kundli",
        "horoscope",
        "prediction",
        "future",
        "remedy",
        "remedies",
        "totke",
        "varshphal",
        "lucky",
        "house",
        "houses",
        "debt",
        "debts",
        "planet",
        "placement",
        "relocation",
        "foreign",
        "marriage",
        "career",
        "full reading",
        "complete reading",
    )
    return any(term in text for term in intent_terms)


def message_is_lalkitab_followup(message: str) -> bool:
    """Detect contextual follow-ups that should reuse prior chart context.

    This deliberately excludes greetings so "hi" on a fresh or existing chat
    stays conversational and does not trigger astrology/RAG work.
    """
    text = re.sub(r"\s+", " ", (message or "").strip().lower())
    if not text:
        return False
    if text in {"hi", "hello", "hey", "namaste", "namaskar", "thanks", "thank you"}:
        return False
    if len(text.split()) <= 2 and re.fullmatch(r"(hi|hello|hey|thanks|ok|okay|yes|no)[.!?]*", text):
        return False
    followup_terms = (
        "what about",
        "tell me more",
        "explain",
        "continue",
        "go on",
        "more detail",
        "why",
        "how so",
        "what does that mean",
        "is that",
        "does that",
        "can you elaborate",
        "elaborate",
        "same chart",
        "from this chart",
        "based on this",
        "based on that",
        "that mean",
        "this mean",
    )
    return any(term in text for term in followup_terms)


def _normalize_date(value: str) -> str | None:
    value = value.strip().replace(",", " ")
    formats = (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%m-%y",
        "%d/%m/%y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _normalize_time(value: str) -> str | None:
    raw = value.strip().lower().replace(".", "")
    if re.fullmatch(r"\d{3,4}", raw):
        raw = raw.zfill(4)
        return f"{raw[:2]}:{raw[2:]}:00"
    if re.fullmatch(r"\d{3,4}\s*(?:hrs|hours?)", raw):
        digits = re.match(r"(\d{3,4})", raw).group(1)  # type: ignore[union-attr]
        raw = digits.zfill(4)
        return f"{raw[:2]}:{raw[2:]}:00"
    formats = ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I %p")
    normalized = raw.upper()
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    return None


def _normalize_timezone(value: str) -> str:
    timezone = value.strip()
    lowered = timezone.lower()
    aliases = {
        "ist": "+05:30",
        "asia/kolkata": "+05:30",
        "asia/calcutta": "+05:30",
        "utc": "+00:00",
        "z": "+00:00",
    }
    if lowered in aliases:
        return aliases[lowered]
    offset_match = re.fullmatch(r"UTC?([+-]\d{1,2})(?::?(\d{2}))?", timezone, re.IGNORECASE)
    if offset_match:
        hours = int(offset_match.group(1))
        minutes = offset_match.group(2) or "00"
        return f"{hours:+03d}:{minutes}"
    plain_offset = re.fullmatch(r"([+-]\d{1,2})(?::?(\d{2}))?", timezone)
    if plain_offset:
        hours = int(plain_offset.group(1))
        minutes = plain_offset.group(2) or "00"
        return f"{hours:+03d}:{minutes}"
    return timezone


def _clean_birth_place(value: str) -> str:
    # Stop the place capture at the next field label or the start of the question
    # (e.g. "Delhi, India. TOB: 1526" → "Delhi, India"). Also cut on an arrow.
    cleaned = re.split(
        r"(?:->|→|\|)|"
        r"\b(?:question|query|ask|will|should|can|dob|tob|pob|"
        r"date\s+of\s+birth|time\s+of\s+birth|birth\s+time|place\s+of\s+birth)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = cleaned.strip(" .,-")
    return cleaned


def _resolve_place(place: str) -> dict[str, Any] | None:
    text = re.sub(r"[^a-zA-Z,\s]", " ", place or "").lower()
    parts = [part.strip() for part in text.split(",") if part.strip()]
    candidates = [text.strip(), *parts]
    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate in CITY_GEO_LOOKUP:
            return CITY_GEO_LOOKUP[candidate]
    for key, value in CITY_GEO_LOOKUP.items():
        if re.search(rf"\b{re.escape(key)}\b", text):
            return value
    return None


def extract_lalkitab_birth_input(
    message: str,
    *,
    resolve_known_places: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    text = message or ""
    normalized: dict[str, Any] = {"language": "en"}

    date_patterns = [
        r"\b\d{4}-\d{1,2}-\d{1,2}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{1,2}\s+(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{4}\b",
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{1,2}\s+\d{4}\b",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _normalize_date(match.group(0))
            if parsed:
                normalized["date"] = parsed
                normalized["birth_date"] = parsed
                break

    time_patterns = [
        r"\b(?:time\s*of\s*birth|birth\s*time|tob)\s*[:=]?\s*(\d{3,4})\b",
        r"\b(?:time\s*of\s*birth|birth\s*time|tob)\s*[:=]?\s*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)\b",
        r"\b(?:born|birth)\s+(?:at|around)\s+(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?|\d{3,4})\b",
        r"\b(?:at)\s+(\d{3,4})\s*(?:hrs|hours?|IST|\(|india)?\b",
        r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b",
        r"\b\d{1,2}\s*(?:am|pm)\b",
        r"\b\d{3,4}\s*(?:hrs|hours?)\b",
    ]
    for pattern in time_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            parsed = _normalize_time(match.group(1) if match.lastindex else match.group(0))
            if parsed:
                normalized["time"] = parsed
                normalized["birth_time"] = parsed
                break

    lat_match = re.search(r"\b(?:lat|latitude)\s*[:=]?\s*(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    lon_match = re.search(r"\b(?:lon|lng|longitude)\s*[:=]?\s*(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if lat_match:
        normalized["latitude"] = float(lat_match.group(1))
    if lon_match:
        normalized["longitude"] = float(lon_match.group(1))

    timezone_match = re.search(
        r"\b(?:timezone|tz)\s*[:=]?\s*([A-Za-z]+/[A-Za-z_]+|UTC[+-]\d{1,2}(?::?\d{2})?|IST)\b",
        text,
        re.IGNORECASE,
    )
    if timezone_match:
        timezone = timezone_match.group(1)
        normalized["timezone"] = _normalize_timezone(timezone)
    elif re.search(r"\bIST\b", text, re.IGNORECASE) or re.search(r"\bindia(?:n)?\s+timezone\b", text, re.IGNORECASE):
        normalized["timezone"] = "+05:30"

    place_match = re.search(
        r"\b(?:birth\s*place|birthplace|place\s*of\s*birth|pob|p\.?o\.?b\.?|born\s+in|place|city)\s*[:=]?\s*([A-Za-z][A-Za-z\s,.-]{1,120})",
        text,
        re.IGNORECASE,
    )
    if place_match:
        normalized["birth_place"] = _clean_birth_place(place_match.group(1))
        resolved_place = _resolve_place(normalized["birth_place"]) if resolve_known_places else None
        if resolved_place:
            normalized.setdefault("latitude", resolved_place["latitude"])
            normalized.setdefault("longitude", resolved_place["longitude"])
            normalized.setdefault("timezone", resolved_place["timezone"])
            normalized["birth_place_resolved"] = resolved_place["label"]

    if normalized.get("date") and normalized.get("time"):
        normalized["datetime"] = f"{normalized['date']}T{normalized['time']}"

    missing = []
    for field in ("date", "time", "latitude", "longitude", "timezone"):
        if normalized.get(field) in (None, ""):
            missing.append(field)
    return normalized, missing


def format_lalkitab_missing_input_clarification(normalized: dict[str, Any], missing: list[str]) -> str:
    friendly_missing = {
        "date": "birth date",
        "time": "birth time",
        "latitude": "birth place coordinates",
        "longitude": "birth place coordinates",
        "timezone": "birth timezone",
    }
    deduped_missing: list[str] = []
    for field in missing:
        label = friendly_missing.get(field, field.replace("_", " "))
        if label not in deduped_missing:
            deduped_missing.append(label)

    understood = []
    if normalized.get("date"):
        understood.append(f"birth date {normalized['date']}")
    if normalized.get("time"):
        understood.append(f"birth time {normalized['time']}")
    if normalized.get("birth_place_resolved"):
        understood.append(f"birth place {normalized['birth_place_resolved']}")
    elif normalized.get("birth_place"):
        understood.append(f"birth place {normalized['birth_place']}")
    if normalized.get("timezone"):
        understood.append(f"timezone {normalized['timezone']}")

    prefix = f"I understood {', '.join(understood)}. " if understood else ""
    if "birth place coordinates" in deduped_missing and normalized.get("birth_place"):
        return (
            f"{prefix}I could not resolve that birthplace to coordinates yet. "
            "Please confirm the nearest major city, or provide latitude, longitude, and timezone."
        )
    return f"{prefix}Please share the missing detail(s): {', '.join(deduped_missing)}."


def select_lalkitab_endpoint_ids(message: str) -> list[str]:
    text = (message or "").lower()
    if any(term in text for term in ("full reading", "complete reading", "full profile", "complete profile", "overall", "all endpoints")):
        return [LAL_KITAB_CHART_ENDPOINT, *LAL_KITAB_SECONDARY_ENDPOINTS]

    selected = [LAL_KITAB_CHART_ENDPOINT]
    rules = [
        (("remedy", "remedies"), ("lalkitab_remedies", "lalkitab_totke")),
        (("totke", "totka"), ("lalkitab_totke",)),
        (("debt", "debts", "karmic", "rin"), ("lalkitab_debts",)),
        (("house", "houses", "planet", "placement"), ("lalkitab_houses",)),
        (("prediction", "future", "timing", "career", "marriage", "relationship", "relocation", "foreign"), ("lalkitab_predictions", "lalkitab_varshphal")),
        (("lucky", "favorable", "colour", "color", "number"), ("lalkitab_lucky",)),
        (("varshphal", "annual", "yearly"), ("lalkitab_varshphal",)),
    ]
    for terms, endpoints in rules:
        if any(term in text for term in terms):
            selected.extend(endpoints)
    if selected == [LAL_KITAB_CHART_ENDPOINT]:
        selected.extend(("lalkitab_predictions", "lalkitab_remedies"))

    deduped: list[str] = []
    for endpoint_id in selected:
        if endpoint_id not in deduped:
            deduped.append(endpoint_id)
    return deduped


def find_lalkitab_connector(config: dict[str, Any] | None) -> dict[str, Any] | None:
    for connector in (config or {}).get("context_connectors") or []:
        if not isinstance(connector, dict) or not connector.get("enabled") or connector.get("revoked"):
            continue
        endpoints = connector.get("endpoints") if isinstance(connector.get("endpoints"), list) else []
        endpoint_ids = {str(endpoint.get("id")) for endpoint in endpoints if isinstance(endpoint, dict)}
        connector_name = f"{connector.get('id', '')} {connector.get('name', '')}".lower()
        if LAL_KITAB_CHART_ENDPOINT in endpoint_ids or "lalkitab" in connector_name or "lal kitab" in connector_name:
            return connector
    return None


def normalize_lalkitab_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(endpoint)
    endpoint_id = str(normalized.get("id") or "")
    if not endpoint_id.startswith("lalkitab_"):
        return normalized
    slug = endpoint_id.replace("lalkitab_", "")
    corrected_url = f"https://api.vedika.io/v2/astrology/lalkitab/{slug}"
    url_template = str(normalized.get("url_template") or normalized.get("url") or "")
    if not url_template or "/v1/lal-kitab/" in url_template:
        normalized["url_template"] = corrected_url
        normalized["url"] = corrected_url
    normalized.setdefault("payload_mode", "flat_body")
    normalized.setdefault("field_mapping", {"birth_date": "date", "birth_time": "time"})
    normalized["runtime_required_fields"] = ["datetime", "latitude", "longitude", "timezone"]
    body_schema = normalized.get("body_schema") if isinstance(normalized.get("body_schema"), dict) else {}
    body_properties = body_schema.get("properties") if isinstance(body_schema.get("properties"), dict) else {}
    if not body_properties or "datetime" not in body_properties:
        normalized["body_schema"] = {
            "type": "object",
            "properties": {
                "datetime": {"type": "string"},
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "timezone": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["datetime", "latitude", "longitude", "timezone"],
        }
    normalized.setdefault("timeout_seconds", 45)
    normalized.setdefault("retry_count", 1)
    normalized.setdefault("max_response_chars", 50000)
    normalized.setdefault("execution_order", 1 if endpoint_id == LAL_KITAB_CHART_ENDPOINT else 2)
    if endpoint_id != LAL_KITAB_CHART_ENDPOINT:
        normalized.setdefault("requires_prior_endpoint", LAL_KITAB_CHART_ENDPOINT)
    return normalized


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


def get_geocoding_config(connector: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a connector's geocoding overrides onto the built-in defaults."""
    config = default_geocoding_config()
    input_resolution = (connector or {}).get("input_resolution")
    overrides = input_resolution.get("geocoding") if isinstance(input_resolution, dict) else None
    if isinstance(overrides, dict):
        config.update({k: v for k, v in overrides.items() if v is not None})
    return config


def _geocode_endpoint(connector: dict[str, Any], endpoint_id: str) -> dict[str, Any] | None:
    """Find a geocoding endpoint on the connector, falling back to the built-in pack."""
    for endpoint in connector.get("endpoints") or []:
        if isinstance(endpoint, dict) and str(endpoint.get("id")) == endpoint_id and endpoint.get("enabled", True):
            return endpoint
    for endpoint in built_in_geocode_endpoints():
        if str(endpoint.get("id")) == endpoint_id:
            return endpoint
    return None


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
        narrowed = [c for c in candidates if str(c.get("countryCode")).upper() == country_code]
        if narrowed:
            return narrowed
    # Region/state token match (e.g. "Hyderabad Telangana").
    region_matches = [
        c for c in candidates
        if c.get("adminRegion") and re.search(rf"\b{re.escape(str(c.get('adminRegion')).lower())}\b", lowered)
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
        idx = int(number.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    # 3) Ordinal words ("the second one").
    for word, index in ORDINAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered) and index < len(candidates):
            return candidates[index]
    return None


async def _call_geocode_endpoint(
    connector: dict[str, Any],
    endpoint_id: str,
    payload: dict[str, Any],
    message: str,
) -> ToolResult | None:
    endpoint = _geocode_endpoint(connector, endpoint_id)
    if not endpoint:
        return None
    tool = ContextConnectorTool(connector, endpoint)
    return await tool.run(query=message, payload=payload)


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
        "content": f"Resolving birthplace \"{birth_place}\"…",
        "metadata": {"birth_place": birth_place, "endpoint_id": search_id},
    })
    search_result = await _call_geocode_endpoint(
        connector, search_id, {"q": birth_place, "limit": max_candidates}, message
    )
    if not search_result or not search_result.success:
        events.append({
            "type": "geocode_result",
            "content": f"Could not look up \"{birth_place}\".",
            "metadata": {"success": False, "error": getattr(search_result, "error", None)},
        })
        return {"status": "failed", "events": events}

    raw_results = []
    data = search_result.data if isinstance(search_result.data, dict) else {}
    if isinstance(data.get("results"), list):
        raw_results = [c for c in data["results"] if isinstance(c, dict) and c.get("placeId")]
    candidates = [_normalize_candidate(c) for c in raw_results]
    if not candidates:
        events.append({
            "type": "geocode_result",
            "content": f"No place matched \"{birth_place}\".",
            "metadata": {"success": True, "count": 0},
        })
        return {"status": "failed", "events": events}

    # 1) Narrow by any country/region token the user already gave.
    narrowed = _filter_candidates_by_hint(candidates, message)
    # 2) Apply the configured default-country bias if still ambiguous.
    default_country = str(geocoding_cfg.get("default_country") or "").upper()
    if len(narrowed) > 1 and default_country:
        biased = [c for c in narrowed if str(c.get("countryCode")).upper() == default_country]
        if len(biased) == 1:
            narrowed = biased

    if len(narrowed) > 1:
        strategy = str(geocoding_cfg.get("ambiguous_strategy") or "ask").lower()
        if strategy == "highest_population" or geocoding_cfg.get("confirm_when_ambiguous") is False:
            narrowed = [max(narrowed, key=lambda c: c.get("population") or 0)]
        else:
            top = narrowed[:max_candidates]
            events.append({
                "type": "geocode_result",
                "content": f"\"{birth_place}\" matches {len(top)} places — asking which one.",
                "metadata": {"success": True, "ambiguous": True, "count": len(top)},
            })
            return {"status": "ambiguous", "candidates": top, "events": events}

    chosen = narrowed[0]
    return await _finalize_geocode_choice(
        connector=connector,
        resolve_id=resolve_id,
        candidate=chosen,
        datetime_iso=datetime_iso,
        message=message,
        events=events,
    )


async def _finalize_geocode_choice(
    *,
    connector: dict[str, Any],
    resolve_id: str,
    candidate: dict[str, Any],
    datetime_iso: str | None,
    message: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a chosen place into coordinates + (historical) timezone offset."""
    latitude = candidate.get("latitude")
    longitude = candidate.get("longitude")
    timezone_offset: str | None = None
    resolve_payload = {"placeId": candidate.get("placeId")}
    if datetime_iso:
        resolve_payload["birthDate"] = datetime_iso
    resolve_result = await _call_geocode_endpoint(connector, resolve_id, resolve_payload, message)
    if resolve_result and resolve_result.success and isinstance(resolve_result.data, dict):
        place = resolve_result.data.get("place") if isinstance(resolve_result.data.get("place"), dict) else {}
        tz_at_birth = resolve_result.data.get("timezoneAtBirth") if isinstance(resolve_result.data.get("timezoneAtBirth"), dict) else {}
        latitude = place.get("latitude", latitude)
        longitude = place.get("longitude", longitude)
        timezone_offset = tz_at_birth.get("utcOffsetString") or timezone_offset

    if timezone_offset is None and candidate.get("timezone"):
        # Fall back to the IANA zone's offset only if the resolve endpoint gave none.
        timezone_offset = _iana_to_offset(str(candidate.get("timezone")))

    if latitude is None or longitude is None or not timezone_offset:
        events.append({
            "type": "geocode_result",
            "content": f"Resolved {candidate.get('label')} but could not derive a timezone.",
            "metadata": {"success": False, "candidate": candidate},
        })
        return {"status": "failed", "events": events}

    events.append({
        "type": "geocode_result",
        "content": f"Birthplace resolved to {candidate.get('label')}.",
        "metadata": {
            "success": True,
            "label": candidate.get("label"),
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone_offset,
        },
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


async def build_lalkitab_runtime_context(
    config: dict[str, Any] | None,
    message: str,
    *,
    pending_state: dict[str, Any] | None = None,
) -> LalKitabPlanResult:
    if not is_lalkitab_agent(config):
        return LalKitabPlanResult(handled=False)
    pending_state = pending_state or {}
    previous_api_context = (
        pending_state.get("api_context")
        if isinstance(pending_state.get("api_context"), dict)
        else {}
    )
    has_previous_chart = bool(previous_api_context.get("chart_context"))
    requires_api = message_requires_lalkitab_api(message)
    # A bare follow-up ("Illinois", "10:30 AM") won't trip the intent keywords,
    # so continue any in-flight birth-input / disambiguation collection. Once a
    # chart exists, remembered birth input alone is not enough to rerun Vedika.
    resuming_input_collection = bool(
        pending_state.get("awaiting_place_choice")
        or (pending_state.get("normalized_birth_input") and not has_previous_chart)
    )
    contextual_followup = has_previous_chart and message_is_lalkitab_followup(message)
    if not requires_api and not resuming_input_collection and not contextual_followup:
        return LalKitabPlanResult(handled=False)

    connector = find_lalkitab_connector(config)
    if not connector:
        return LalKitabPlanResult(handled=False)

    input_resolution = connector.get("input_resolution") if isinstance(connector.get("input_resolution"), dict) else {}
    extracted, _ = extract_lalkitab_birth_input(
        message,
        resolve_known_places=input_resolution.get("resolve_known_places", True) is not False,
    )
    has_new_birth_input = any(
        key in extracted
        for key in (
            "date",
            "birth_date",
            "time",
            "birth_time",
            "birth_place",
            "latitude",
            "longitude",
            "timezone",
        )
    )
    # Merge previously collected birth input (so a follow-up that only adds the
    # missing time does not discard the earlier date/place) with this turn.
    normalized_birth_input: dict[str, Any] = {"language": "en"}
    if isinstance(previous_api_context.get("normalized_birth_input"), dict):
        normalized_birth_input.update(previous_api_context.get("normalized_birth_input") or {})
    normalized_birth_input.update(pending_state.get("normalized_birth_input") or {})
    normalized_birth_input.update({k: v for k, v in extracted.items() if v not in (None, "")})

    selected_endpoint_ids = (
        select_lalkitab_endpoint_ids(message)
        if requires_api or has_new_birth_input or not has_previous_chart
        else []
    )
    result = LalKitabPlanResult(
        handled=True,
        normalized_birth_input=normalized_birth_input,
        selected_endpoint_ids=selected_endpoint_ids,
    )

    geocoding_cfg = get_geocoding_config(connector)
    geocoding_enabled = geocoding_cfg.get("enabled") is not False

    def _has_coords() -> bool:
        return all(normalized_birth_input.get(field) not in (None, "") for field in ("latitude", "longitude", "timezone"))

    def _refresh_datetime() -> None:
        if normalized_birth_input.get("date") and normalized_birth_input.get("time"):
            normalized_birth_input["datetime"] = f"{normalized_birth_input['date']}T{normalized_birth_input['time']}"

    _refresh_datetime()

    # A follow-up answer to a pending birthplace disambiguation.
    pending_candidates = pending_state.get("place_candidates") or []
    if pending_state.get("awaiting_place_choice") and pending_candidates and not _has_coords():
        choice = match_place_choice(message, pending_candidates)
        if choice is not None:
            finalize = await _finalize_geocode_choice(
                connector=connector,
                resolve_id=geocoding_cfg.get("resolve_endpoint_id") or GEOCODE_RESOLVE_ENDPOINT,
                candidate=choice,
                datetime_iso=normalized_birth_input.get("datetime"),
                message=message,
                events=[],
            )
            result.events.extend(finalize.get("events") or [])
            if finalize.get("status") == "resolved":
                normalized_birth_input["latitude"] = finalize["latitude"]
                normalized_birth_input["longitude"] = finalize["longitude"]
                normalized_birth_input["timezone"] = finalize["timezone"]
                normalized_birth_input["birth_place_resolved"] = finalize.get("label")
        else:
            # Still could not tell which place — re-ask with the same candidates.
            result.awaiting_place_choice = True
            result.place_candidates = pending_candidates
            result.clarification = format_place_disambiguation(
                pending_state.get("normalized_birth_input", {}).get("birth_place") or "that place",
                pending_candidates,
            )
            result.pending_state = {
                "normalized_birth_input": normalized_birth_input,
                "place_candidates": pending_candidates,
                "awaiting_place_choice": True,
            }
            return result

    # Resolve birthplace via the geocoding connector when coordinates are still
    # missing but we have a birthplace string and the birth datetime.
    if (
        not _has_coords()
        and geocoding_enabled
        and normalized_birth_input.get("birth_place")
        and normalized_birth_input.get("datetime")
    ):
        geo = await resolve_birthplace_via_geocoding(
            connector=connector,
            geocoding_cfg=geocoding_cfg,
            birth_place=str(normalized_birth_input["birth_place"]),
            datetime_iso=normalized_birth_input.get("datetime"),
            message=message,
        )
        result.events.extend(geo.get("events") or [])
        if geo.get("status") == "resolved":
            normalized_birth_input["latitude"] = geo["latitude"]
            normalized_birth_input["longitude"] = geo["longitude"]
            normalized_birth_input["timezone"] = geo["timezone"]
            normalized_birth_input["birth_place_resolved"] = geo.get("label")
        elif geo.get("status") == "ambiguous":
            candidates = geo.get("candidates") or []
            result.awaiting_place_choice = True
            result.place_candidates = candidates
            result.clarification = format_place_disambiguation(
                str(normalized_birth_input["birth_place"]), candidates
            )
            result.pending_state = {
                "normalized_birth_input": normalized_birth_input,
                "place_candidates": candidates,
                "awaiting_place_choice": True,
            }
            return result

    missing = [
        field for field in ("date", "time", "latitude", "longitude", "timezone")
        if normalized_birth_input.get(field) in (None, "")
    ]
    result.missing_input = missing
    if missing:
        result.clarification = format_lalkitab_missing_input_clarification(normalized_birth_input, missing)
        # Carry collected birth input forward so the next turn can complete it.
        result.pending_state = {"normalized_birth_input": normalized_birth_input}
        return result

    endpoints_by_id = {
        endpoint.get("id"): normalize_lalkitab_endpoint(endpoint)
        for endpoint in (connector.get("endpoints") or [])
        if isinstance(endpoint, dict) and endpoint.get("enabled", True) and not endpoint.get("revoked")
    }
    api_context = deepcopy(previous_api_context) if previous_api_context else {}
    api_context.setdefault("chart_context", None)
    api_context.setdefault("secondary_endpoint_results", {})
    api_context.setdefault("source_provenance", [])
    api_context["normalized_birth_input"] = normalized_birth_input
    api_context["input_resolution"] = {
        "resolve_known_places": input_resolution.get("resolve_known_places", True) is not False,
        "confirm_understood_details": input_resolution.get("confirm_understood_details", True) is not False,
        "missing_input_strategy": input_resolution.get("missing_input_strategy") or "ask_follow_up",
    }

    if has_new_birth_input and previous_api_context:
        # A new birth profile invalidates any cached calculated evidence.
        api_context["chart_context"] = None
        api_context["secondary_endpoint_results"] = {}
        api_context["source_provenance"] = []

    endpoints_to_call: list[str] = []
    existing_secondaries = api_context.get("secondary_endpoint_results") or {}
    for endpoint_id in selected_endpoint_ids:
        if endpoint_id == LAL_KITAB_CHART_ENDPOINT and api_context.get("chart_context"):
            continue
        if endpoint_id != LAL_KITAB_CHART_ENDPOINT and endpoint_id in existing_secondaries:
            continue
        endpoints_to_call.append(endpoint_id)

    for endpoint_id in endpoints_to_call:
        endpoint = endpoints_by_id.get(endpoint_id)
        if not endpoint:
            continue
        tool = ContextConnectorTool(connector, endpoint)
        endpoint_name = endpoint.get("name") or endpoint_id
        connector_name = connector.get("name") or connector.get("id") or "Lal Kitab Connector"
        result.events.append(
            {
                "type": "connector_start",
                "content": f"Calling {connector_name} · {endpoint_name}.",
                "metadata": {
                    "connector_id": connector.get("id"),
                    "connector_name": connector_name,
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint_name,
                    "normalized_birth_input": normalized_birth_input,
                },
            }
        )
        tool_result = await tool.run(query=message, payload=normalized_birth_input)
        result.tool_results[tool.name] = tool_result
        metadata = tool_result.metadata or {}
        event_type = "connector_result" if tool_result.success else "connector_error"
        result.events.append(
            {
                "type": event_type,
                "content": (
                    f"{endpoint_name} returned calculated context."
                    if tool_result.success
                    else f"{endpoint_name} failed: {tool_result.error or 'unknown connector error'}"
                ),
                "metadata": {
                    "success": tool_result.success,
                    "connector_id": metadata.get("connector_id") or connector.get("id"),
                    "connector_name": metadata.get("connector_name") or connector_name,
                    "endpoint_id": metadata.get("endpoint_id") or endpoint_id,
                    "endpoint_name": metadata.get("endpoint_name") or endpoint_name,
                    "request_shape": metadata.get("request_shape"),
                    "response_summary": metadata.get("response_summary"),
                    "latency_ms": metadata.get("latency_ms"),
                    "error": tool_result.error,
                },
            }
        )
        if not tool_result.success:
            continue
        if endpoint_id == LAL_KITAB_CHART_ENDPOINT:
            api_context["chart_context"] = tool_result.data
        else:
            api_context["secondary_endpoint_results"][endpoint_id] = tool_result.data
        api_context["source_provenance"].append(
            {
                "endpoint_id": endpoint_id,
                "endpoint_name": endpoint_name,
                "source": metadata.get("url"),
            }
        )

    result.api_context = api_context
    result.used_cached_context = bool(previous_api_context and not endpoints_to_call)
    if endpoints_to_call:
        result.events.append(
            {
                "type": "api_context",
                "content": "Calculated Lal Kitab API context is ready.",
                "metadata": {
                    "normalized_birth_input": normalized_birth_input,
                    "selected_endpoint_ids": selected_endpoint_ids,
                    "chart_available": bool(api_context.get("chart_context")),
                    "secondary_endpoint_ids": sorted((api_context.get("secondary_endpoint_results") or {}).keys()),
                    "source_provenance": api_context.get("source_provenance") or [],
                },
            }
        )
    return result
