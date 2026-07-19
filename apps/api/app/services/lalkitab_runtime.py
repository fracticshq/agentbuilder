from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any
import structlog

from tools.types import ToolResult

from .artifact_registry import LAL_KITAB_TEMPLATE, normalize_agent_template
from .context_connector_packs import built_in_geocode_endpoints
from . import lalkitab_geocoding as _geocoding
from . import lalkitab_birth_input as _birth_input
from .lalkitab_birth_input import (
    CITY_GEO_LOOKUP,
    _MONTHS_PATTERN,
    _NAME_PATTERNS,
    _NAME_TOKEN,
    _clean_birth_place,
    _extract_name,
    _extract_place_only_reply,
    _infer_unlabeled_place,
    _looks_like_question_or_intent,
    _normalize_date,
    _normalize_time,
    _normalize_timezone,
    _resolve_place,
    _strip_question_clauses,
    extract_lalkitab_birth_input,
    format_lalkitab_missing_input_clarification,
    message_contains_birth_details,
)
from .tool_registry import ContextConnectorTool
from .kundali_chart import extract_kundali_chart_summary


logger = structlog.get_logger(__name__)


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

# Public activity events must not disclose the user's full birth profile or a
# provider's diagnostic response.  The detailed data remains in the runtime
# context only, where it is needed to make a subsequent chart request.
LAL_KITAB_CHART_UNAVAILABLE_MESSAGE = (
    "I can’t safely give a Lal Kitab prediction or remedy until I can verify the "
    "calculated chart. Please try again shortly; if needed, confirm your birth "
    "date, time, and birthplace so I can recalculate it."
)

GEOCODE_SEARCH_ENDPOINT = _geocoding.GEOCODE_SEARCH_ENDPOINT
GEOCODE_RESOLVE_ENDPOINT = _geocoding.GEOCODE_RESOLVE_ENDPOINT


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
    # A chart is usable only after a successful, non-empty structured result
    # has been checked.  This blocks synthesis from failed, absent, or malformed
    # connector data.
    chart_validated: bool = False
    requires_safe_abstention: bool = False
    abstention_reason: str | None = None


def is_lalkitab_agent(config: dict[str, Any] | None) -> bool:
    config = config if isinstance(config, dict) else {}
    domain = config.get("domain") if isinstance(config.get("domain"), dict) else {}
    return (
        normalize_agent_template(domain.get("template")) == LAL_KITAB_TEMPLATE
        or normalize_agent_template(config.get("agent_template")) == LAL_KITAB_TEMPLATE
        or normalize_agent_template(config.get("template")) == LAL_KITAB_TEMPLATE
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


_MONTHS_PATTERN = (
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|"
    r"aug|august|sep|sept|september|oct|october|nov|november|dec|december)"
)


def _strip_question_clauses(text: str) -> str:
    """Drop question/intent sentences so they can never pollute place inference.

    "…, New Delhi. How is my health going to be in 2026" → "…, New Delhi." """
    sentences = re.split(r"(?<=[.?!])\s+|\n+", text or "")
    kept = [s for s in sentences if s.strip() and not _looks_like_question_or_intent(s)]
    return " ".join(kept)


_NAME_TOKEN = r"([A-Za-z][A-Za-z\s.']{1,60}?)"

_NAME_PATTERNS = (
    # "my name is Sandeep Amar" / "name: Priya Sharma" / "name - Anant"
    rf"\bmy\s+name\s+is\s+{_NAME_TOKEN}(?=[,.;\n]|$)",
    rf"\bname\s*[:=\-–]\s*{_NAME_TOKEN}(?=[,.;\n]|\s+dob\b|\s+tob\b|\s+pob\b|$)",
    rf"\bname\s+{_NAME_TOKEN}(?=[,.;\n]|$)",
    # "Sandeep Amar is my name"
    rf"\b{_NAME_TOKEN}\s+is\s+my\s+name\b",
    # Leading "Sandeep Amar, DOB …" / "anant mendiratta. 16july 1987 …"
    rf"^\s*{_NAME_TOKEN}\s*[,.]\s*(?:dob\b|date\s+of\s+birth|born\b|birth\b|\d)",
)


def _extract_name(text: str) -> str | None:
    """Extract the person's name so it can never be mistaken for a place."""
    for pattern in _NAME_PATTERNS:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            name = re.sub(r"\s+", " ", match.group(1)).strip(" .,-")
            if (
                name
                and not _looks_like_question_or_intent(name)
                and not re.search(r"\d", name)
                # A candidate carrying birth/place vocabulary is a mis-split
                # detail fragment ("Born in Springfield"), not a person.
                and not re.search(r"\b(?:born|birth|place|city|dob|tob|pob)\b", name, re.IGNORECASE)
            ):
                return name
    return None


def _infer_unlabeled_place(text: str) -> str | None:
    """Infer an unlabeled birthplace from free-form input.

    Handles natural phrasing such as "16 July 1987, 15:26, Delhi India" where
    the user never writes "place:" or "born in". This is generic scrubbing of
    date/time/label fragments — no city lists or keyword hardcoding.
    """
    # 1) Prefer the free-text fragment that follows the birth time.
    #    Anchors: "1526", "1526 hrs", "15:26", "11 AM" — all real user shapes.
    after_time = re.search(
        r"(?:\b\d{3,4}\s*(?:hrs|hours?|ist|india(?:n)?\s+timezone)?\b|"
        r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|"
        r"\b\d{1,2}\s*(?:am|pm)\b)"
        r"\s*(?:[,.)-]|\btime\b)?\s*([A-Za-z][A-Za-z\s,.-]{1,120})",
        text,
        re.IGNORECASE,
    )
    if after_time:
        place = _clean_birth_place(after_time.group(1))
        if place and not _looks_like_question_or_intent(place):
            return place
    # 2) Otherwise scrub date/time/label fragments and keep the trailing
    #    location-like free-text fragment (names tend to come first).
    scrubbed = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ", text)
    scrubbed = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", scrubbed)
    scrubbed = re.sub(
        rf"\b\d{{1,2}}\s*{_MONTHS_PATTERN}\s+\d{{4}}\b|\b{_MONTHS_PATTERN}\s+\d{{1,2}}\s+\d{{4}}\b",
        " ",
        scrubbed,
        flags=re.IGNORECASE,
    )
    scrubbed = re.sub(
        r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|\b\d{3,4}\s*(?:hrs|hours?|ist)?\b|\b\d{1,2}\s*(?:am|pm)\b",
        " ",
        scrubbed,
        flags=re.IGNORECASE,
    )
    scrubbed = re.sub(
        r"\b(?:name|dob|tob|pob|date|time|birth|of|place|question|query|ist|india timezone)\b\s*[:=-]?",
        " ",
        scrubbed,
        flags=re.IGNORECASE,
    )
    parts = []
    for part in re.split(r"[.;\n]+", scrubbed):
        cleaned = _clean_birth_place(part)
        if cleaned and not _looks_like_question_or_intent(cleaned) and not re.search(r"\d", cleaned):
            parts.append(cleaned)
    return parts[-1] if parts else None


def message_contains_birth_details(message: str) -> bool:
    """True when the message itself reads like birth details (date plus a time
    or place), even without any astrology keyword — e.g. a bare
    "16 July 1987, 15:26, Delhi India" reply."""
    extracted, _ = extract_lalkitab_birth_input(message, resolve_known_places=False)
    return bool(extracted.get("date") and (extracted.get("time") or extracted.get("birth_place")))


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
        r"\b\d{1,2}\s*(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{4}\b",
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{1,2}\s+\d{4}\b",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_date = re.sub(
                r"^(\d{1,2})(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
                r"\1 \2",
                match.group(0),
                flags=re.IGNORECASE,
            )
            parsed = _normalize_date(raw_date)
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
        r"\b(\d{3,4})\s*(?:ist|india(?:n)?\s+timezone)\b",
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

    # The person's name is a first-class field so it can never be mistaken
    # for the birth place ("Sandeep Amar, DOB 25/01/1975, …").
    extracted_name = _extract_name(text)
    if extracted_name:
        normalized["name"] = extracted_name

    # All place matching runs on text with the name clause removed.
    place_text = text
    if extracted_name:
        place_text = re.sub(
            rf"\b(?:my\s+name\s+is\s+)?{re.escape(extracted_name)}(?:\s+is\s+my\s+name)?\b",
            " ",
            place_text,
            flags=re.IGNORECASE,
        )
    place_match = re.search(
        r"\b(?:birth\s*place|birthplace|place\s*of\s*birth|pob|p\.?o\.?b\.?|born\s+in|place|city)\s*[:=\-–]?\s*([A-Za-z][A-Za-z\s,.-]{1,120})",
        place_text,
        re.IGNORECASE,
    )
    if not place_match:
        place_match = re.search(
            r"\b([A-Za-z][A-Za-z\s,.-]{1,80})\s+(?:born|birthplace)\b",
            place_text,
            re.IGNORECASE,
        )
    if place_match:
        birth_place = _clean_birth_place(place_match.group(1))
        parts = [part.strip() for part in re.split(r"[.;\n]+", birth_place) if part.strip()]
        normalized["birth_place"] = parts[-1] if parts else birth_place
    elif normalized.get("date"):
        # No labelled place, but the message carries birth details — infer the
        # unlabeled place ("16 July 1987, 15:26, Delhi India"). Question
        # sentences and the person's name are removed first so neither can
        # ever be inferred as the place.
        inferred_place = _infer_unlabeled_place(_strip_question_clauses(place_text))
        if inferred_place:
            normalized["birth_place"] = inferred_place
    if normalized.get("birth_place") and extracted_name and (
        normalized["birth_place"].strip().lower() == extracted_name.strip().lower()
    ):
        # Never geocode the user's own name.
        normalized.pop("birth_place")
    if normalized.get("birth_place"):
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
    # Coordinates and timezone are derived automatically from the birthplace,
    # so the user is only ever asked for the place itself — never lat/long.
    friendly_missing = {
        "date": "birth date",
        "time": "birth time",
        "latitude": "birth place (city and country)",
        "longitude": "birth place (city and country)",
        "timezone": "birth place (city and country)",
    }
    deduped_missing: list[str] = []
    for field in missing:
        label = friendly_missing.get(field, field.replace("_", " "))
        if label not in deduped_missing:
            deduped_missing.append(label)

    # Only validated facts are presented as understood: dates/times are
    # deterministically normalized, and a place counts only once geocoding
    # confirmed it. An unvalidated guess must never be echoed as fact
    # ("I understood birth place Sandeep Amar").
    understood = []
    if normalized.get("name"):
        understood.append(f"name {normalized['name']}")
    if normalized.get("date"):
        understood.append(f"birth date {normalized['date']}")
    if normalized.get("time"):
        understood.append(f"birth time {normalized['time']}")
    if normalized.get("birth_place_resolved"):
        understood.append(f"birth place {normalized['birth_place_resolved']}")

    prefix = f"I have your {', '.join(understood)}. " if understood else ""
    if "birth place (city and country)" in deduped_missing and normalized.get("birth_place"):
        return (
            f"{prefix}I could not find \"{normalized['birth_place']}\" on the map yet. "
            "Could you confirm the city and country (or the nearest major city, if it is a small town)?"
        )
    if deduped_missing == ["birth place (city and country)"]:
        return f"{prefix}Which city (and country) were you born in?"
    return f"{prefix}Please share the missing detail(s): {', '.join(deduped_missing)}."


# Compatibility re-exports. The deterministic behavior is owned by the leaf
# module; existing imports from this runtime remain valid.
CITY_GEO_LOOKUP = _birth_input.CITY_GEO_LOOKUP
_MONTHS_PATTERN = _birth_input._MONTHS_PATTERN
_NAME_TOKEN = _birth_input._NAME_TOKEN
_NAME_PATTERNS = _birth_input._NAME_PATTERNS
_normalize_date = _birth_input._normalize_date
_normalize_time = _birth_input._normalize_time
_normalize_timezone = _birth_input._normalize_timezone
_clean_birth_place = _birth_input._clean_birth_place
_resolve_place = _birth_input._resolve_place
_extract_place_only_reply = _birth_input._extract_place_only_reply
_looks_like_question_or_intent = _birth_input._looks_like_question_or_intent
_strip_question_clauses = _birth_input._strip_question_clauses
_extract_name = _birth_input._extract_name
_infer_unlabeled_place = _birth_input._infer_unlabeled_place
message_contains_birth_details = _birth_input.message_contains_birth_details
extract_lalkitab_birth_input = _birth_input.extract_lalkitab_birth_input
format_lalkitab_missing_input_clarification = _birth_input.format_lalkitab_missing_input_clarification


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
        (("health", "wellness", "illness", "disease", "medical", "swasthya"), ("lalkitab_predictions",)),
        (("lucky", "favorable", "colour", "color", "number"), ("lalkitab_lucky",)),
        (("varshphal", "annual", "yearly"), ("lalkitab_varshphal",)),
    ]
    for terms, endpoints in rules:
        if any(term in text for term in terms):
            selected.extend(endpoints)
    # A question about a specific year ("… in 2026") is an annual-chart question.
    if re.search(r"\b20\d{2}\b", text):
        selected.append("lalkitab_varshphal")
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


# Compatibility re-exports. The resolver owns deterministic geocoding behavior;
# public imports from this runtime remain valid.
COUNTRY_ALIASES = _geocoding.COUNTRY_ALIASES
ORDINAL_WORDS = _geocoding.ORDINAL_WORDS
default_geocoding_config = _geocoding.default_geocoding_config
get_geocoding_config = _geocoding.get_geocoding_config
_country_hint_from_text = _geocoding._country_hint_from_text
candidate_label = _geocoding.candidate_label
_normalize_candidate = _geocoding._normalize_candidate
_filter_candidates_by_hint = _geocoding._filter_candidates_by_hint
match_place_choice = _geocoding.match_place_choice
format_place_disambiguation = _geocoding.format_place_disambiguation
_iana_to_offset = _geocoding._iana_to_offset


def _geocode_endpoint(connector: dict[str, Any], endpoint_id: str) -> dict[str, Any] | None:
    """Find a geocoding endpoint on the connector, falling back to the built-in pack."""
    for endpoint in connector.get("endpoints") or []:
        if isinstance(endpoint, dict) and str(endpoint.get("id")) == endpoint_id and endpoint.get("enabled", True):
            return endpoint
    for endpoint in built_in_geocode_endpoints():
        if str(endpoint.get("id")) == endpoint_id:
            return endpoint
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
    try:
        return await tool.run(query=message, payload=payload)
    except Exception as exc:  # pragma: no cover - provider failures are environment-specific
        logger.warning("lalkitab_geocode_call_failed", endpoint_id=endpoint_id, error=str(exc))
        return ToolResult(
            success=False,
            data=None,
            error="connector call failed",
            metadata={"endpoint_id": endpoint_id},
        )


async def resolve_birthplace_via_geocoding(
    *,
    connector: dict[str, Any],
    geocoding_cfg: dict[str, Any],
    birth_place: str,
    datetime_iso: str | None,
    message: str,
) -> dict[str, Any]:
    return await _geocoding.resolve_birthplace_via_geocoding(
        connector=connector,
        geocoding_cfg=geocoding_cfg,
        birth_place=birth_place,
        datetime_iso=datetime_iso,
        message=message,
        call_endpoint=_call_geocode_endpoint,
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
    return await _geocoding.finalize_geocode_choice(
        connector=connector,
        resolve_id=resolve_id,
        candidate=candidate,
        datetime_iso=datetime_iso,
        message=message,
        events=events,
        call_endpoint=_call_geocode_endpoint,
    )


def is_valid_lalkitab_context_payload(payload: Any) -> bool:
    """Return whether a connector supplied usable structured Lal Kitab data.

    The provider payload is intentionally treated as schema-flexible, but a
    successful HTTP/tool invocation alone is not evidence: it must contain a
    non-empty JSON object or list and must not carry an explicit failure shape.
    This gives the runtime a stable boundary for malformed responses without
    guessing at a provider-specific chart schema.
    """
    if isinstance(payload, list):
        return bool(payload)
    if not isinstance(payload, dict) or not payload:
        return False

    for key in ("error", "errors", "exception"):
        if payload.get(key) not in (None, "", [], {}):
            return False
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "failed", "failure", "invalid", "unavailable"}:
        return False
    status_code = payload.get("status_code") or payload.get("statusCode")
    if isinstance(status_code, int) and status_code >= 400:
        return False
    return True


async def build_lalkitab_runtime_context(
    config: dict[str, Any] | None,
    message: str,
    *,
    pending_state: dict[str, Any] | None = None,
    birth_profile: dict[str, Any] | None = None,
) -> LalKitabPlanResult:
    if not is_lalkitab_agent(config):
        return LalKitabPlanResult(handled=False)
    pending_state = pending_state or {}
    previous_api_context = (
        pending_state.get("api_context")
        if isinstance(pending_state.get("api_context"), dict)
        else {}
    )
    has_previous_chart = is_valid_lalkitab_context_payload(previous_api_context.get("chart_context"))
    # A message that *is* birth details ("16 July 1987, 15:26, Delhi India")
    # counts as astrology intent even without any keyword — whether detected
    # deterministically or by the LLM understanding layer.
    requires_api = (
        message_requires_lalkitab_api(message)
        or message_contains_birth_details(message)
        or bool(
            isinstance(birth_profile, dict)
            and any(birth_profile.get(key) for key in ("birth_date", "birth_time", "birth_place", "question"))
        )
    )
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
        # A Lal Kitab request without a chart connector cannot safely fall
        # through to the general synthesizer; there is no calculated evidence
        # to ground a prediction or remedy.
        return LalKitabPlanResult(
            handled=True,
            requires_safe_abstention=True,
            abstention_reason="chart_connector_unavailable",
        )

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
    # The LLM birth profile is the most reliable interpretation of this turn —
    # it wins over the regex extraction above.
    question_text: str | None = None
    if isinstance(birth_profile, dict):
        profile_date = _normalize_date(str(birth_profile.get("birth_date"))) if birth_profile.get("birth_date") else None
        profile_time = _normalize_time(str(birth_profile.get("birth_time"))) if birth_profile.get("birth_time") else None
        if profile_date:
            normalized_birth_input["date"] = profile_date
            normalized_birth_input["birth_date"] = profile_date
        if profile_time:
            normalized_birth_input["time"] = profile_time
            normalized_birth_input["birth_time"] = profile_time
        profile_place = birth_profile.get("birth_place")
        profile_name = birth_profile.get("name")
        if profile_name:
            normalized_birth_input["name"] = str(profile_name)
        if profile_place and (
            not profile_name or str(profile_place).strip().lower() != str(profile_name).strip().lower()
        ):
            # A new place invalidates any previously resolved coordinates.
            if str(profile_place).strip().lower() != str(normalized_birth_input.get("birth_place") or "").strip().lower():
                for stale in ("latitude", "longitude", "timezone", "birth_place_resolved"):
                    normalized_birth_input.pop(stale, None)
            normalized_birth_input["birth_place"] = str(profile_place)
        if birth_profile.get("question"):
            question_text = str(birth_profile["question"])
        has_new_birth_input = has_new_birth_input or any(
            birth_profile.get(key) for key in ("birth_date", "birth_time", "birth_place")
        )
    if (
        not normalized_birth_input.get("birth_place")
        and normalized_birth_input.get("date")
        and normalized_birth_input.get("time")
    ):
        followup_place = _extract_place_only_reply(message)
        if followup_place:
            normalized_birth_input["birth_place"] = followup_place

    # Endpoint selection follows the user's actual question when the
    # understanding layer separated it from the details.
    selected_endpoint_ids = (
        select_lalkitab_endpoint_ids(question_text or message)
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

    # Resolve common or previously cached city names before hitting external
    # geocoding. This keeps normal users from ever needing to know lat/lon for
    # places such as Delhi, while still allowing connector-backed geocoding for
    # new or ambiguous places below.
    if (
        not _has_coords()
        and normalized_birth_input.get("birth_place")
        and input_resolution.get("resolve_known_places", True) is not False
    ):
        resolved_place = _resolve_place(str(normalized_birth_input["birth_place"]))
        if resolved_place:
            normalized_birth_input["latitude"] = resolved_place["latitude"]
            normalized_birth_input["longitude"] = resolved_place["longitude"]
            normalized_birth_input["timezone"] = resolved_place["timezone"]
            normalized_birth_input["birth_place_resolved"] = resolved_place["label"]
            result.events.append(
                {
                    "type": "geocode_result",
                    "content": "Birthplace resolved.",
                    "metadata": {
                        "success": True,
                        "source": "known_place_cache",
                    },
                }
            )

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

    # Never reuse a truthy-but-malformed cached chart.  Secondary results depend
    # on the chart, so they are not safe to reuse either in that situation.
    if not is_valid_lalkitab_context_payload(api_context.get("chart_context")):
        api_context["chart_context"] = None
        api_context["secondary_endpoint_results"] = {}
        api_context["source_provenance"] = []

    endpoints_to_call: list[str] = []
    existing_secondaries = api_context.get("secondary_endpoint_results") or {}
    for endpoint_id in selected_endpoint_ids:
        if endpoint_id == LAL_KITAB_CHART_ENDPOINT and is_valid_lalkitab_context_payload(api_context.get("chart_context")):
            continue
        if endpoint_id != LAL_KITAB_CHART_ENDPOINT and endpoint_id in existing_secondaries:
            if is_valid_lalkitab_context_payload(existing_secondaries[endpoint_id]):
                continue
            # A cached secondary result without usable structured data is not
            # evidence for a prediction/remedy; retry it rather than synthesize.
            api_context["secondary_endpoint_results"].pop(endpoint_id, None)
        endpoints_to_call.append(endpoint_id)

    for endpoint_id in endpoints_to_call:
        endpoint = endpoints_by_id.get(endpoint_id)
        if not endpoint:
            result.events.append(
                {
                    "type": "connector_error",
                    "content": "The required Lal Kitab calculation is unavailable right now.",
                    "metadata": {"success": False, "endpoint_id": endpoint_id},
                }
            )
            result.requires_safe_abstention = True
            result.abstention_reason = "required_endpoint_unavailable"
            break
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
                },
            }
        )
        try:
            tool_result = await tool.run(query=message, payload=normalized_birth_input)
        except Exception as exc:  # pragma: no cover - provider failures are environment-specific
            logger.warning("lalkitab_connector_call_failed", endpoint_id=endpoint_id, error=str(exc))
            tool_result = ToolResult(
                success=False,
                data=None,
                error="connector call failed",
                metadata={"endpoint_id": endpoint_id, "endpoint_name": endpoint_name},
            )
        result.tool_results[tool.name] = tool_result
        metadata = tool_result.metadata or {}
        payload_valid = tool_result.success and is_valid_lalkitab_context_payload(tool_result.data)
        event_type = "connector_result" if payload_valid else "connector_error"
        result.events.append(
            {
                "type": event_type,
                "content": (
                    f"{endpoint_name} returned calculated context."
                    if payload_valid
                    else f"{endpoint_name} could not provide verified context."
                ),
                "metadata": {
                    "success": payload_valid,
                    "connector_id": metadata.get("connector_id") or connector.get("id"),
                    "connector_name": metadata.get("connector_name") or connector_name,
                    "endpoint_id": metadata.get("endpoint_id") or endpoint_id,
                    "endpoint_name": metadata.get("endpoint_name") or endpoint_name,
                    "latency_ms": metadata.get("latency_ms"),
                },
            }
        )
        if not payload_valid:
            result.requires_safe_abstention = True
            result.abstention_reason = (
                "chart_context_unavailable"
                if endpoint_id == LAL_KITAB_CHART_ENDPOINT
                else "required_context_unavailable"
            )
            break
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

    result.chart_validated = is_valid_lalkitab_context_payload(api_context.get("chart_context"))
    if not result.chart_validated:
        result.requires_safe_abstention = True
        result.abstention_reason = result.abstention_reason or "chart_context_unavailable"
        api_context["chart_context"] = None
        api_context["secondary_endpoint_results"] = {}
        api_context["source_provenance"] = []
        result.pending_state = {"normalized_birth_input": normalized_birth_input}

    result.api_context = api_context
    result.used_cached_context = bool(
        previous_api_context and not endpoints_to_call and result.chart_validated
    )
    if endpoints_to_call:
        result.events.append(
            {
                "type": "api_context",
                "content": (
                    "Calculated Lal Kitab API context is ready."
                    if result.chart_validated and not result.requires_safe_abstention
                    else "Verified Lal Kitab context is unavailable for this request."
                ),
                "metadata": {
                    "selected_endpoint_ids": selected_endpoint_ids,
                    "chart_available": result.chart_validated,
                    "secondary_endpoint_ids": sorted((api_context.get("secondary_endpoint_results") or {}).keys()),
                },
            }
        )
    return result
