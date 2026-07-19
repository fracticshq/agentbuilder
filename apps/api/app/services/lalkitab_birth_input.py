"""Deterministic Lal Kitab birth-detail parsing and normalization.

This leaf module intentionally has no connector, geocoding, or chart-execution
dependencies. The runtime re-exports these names for compatibility.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any


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
    cleaned = re.sub(r"\b(?:born|birthplace)\b", " ", cleaned, flags=re.IGNORECASE)
    # Drop time/preposition fragments that ride along with an unlabeled place
    # ("1526 hrs time. delhi" → "delhi", "at in mumbai" → "mumbai").
    cleaned = re.sub(r"\b(?:hrs?|hours?|ist|india\s+timezone)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" .,-")
    cleaned = re.sub(
        r"^(?:(?:time|at|in|on|around|near)\b[\s.,-]*)+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned)
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


def _extract_place_only_reply(text: str) -> str | None:
    cleaned = _clean_birth_place(text or "")
    if not cleaned:
        return None
    if re.search(r"\d", cleaned) or _looks_like_question_or_intent(cleaned):
        return None
    words = [word for word in re.split(r"[\s,]+", cleaned) if word]
    if not 1 <= len(words) <= 6:
        return None
    return cleaned


def _looks_like_question_or_intent(text: str) -> bool:
    lowered = (text or "").lower()
    if "?" in lowered:
        return True
    return bool(
        re.search(
            r"\b(what|why|how|when|where|which|who|will|should|can|could|would|"
            r"career|marriage|finance|relationship|health|remed\w*|predict\w*|"
            r"kundli|kundali|horoscope|chart|please|question|query)\b",
            lowered,
        )
    )


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
