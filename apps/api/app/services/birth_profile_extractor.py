"""LLM-first birth-profile extraction for astrology agents.

This is the single understanding layer for birth details. It asks the LLM to
read the user's message like a human assistant — name, birth date, birth time,
birth place, and the actual question are separated into a strict schema — and
validates every field deterministically afterwards, so a malformed model reply
can never inject garbage downstream.

The regex extractors in `lalkitab_runtime` / `conversation_policy` remain only
as the offline fallback (LLM unavailable or invalid output), and every result
carries `source` so the fallback path is observable instead of silent.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from .lalkitab_runtime import (
    _extract_name,
    _normalize_date,
    _normalize_time,
    extract_lalkitab_birth_input,
)


logger = structlog.get_logger(__name__)


PROFILE_FIELDS = ("name", "birth_date", "birth_time", "birth_place", "question")


_EXTRACTION_PROMPT = """You extract birth details for a Vedic astrology assistant.
Read the user's message like a careful human assistant, not a parser.

Previously known details (may be empty):
{prior}

User message:
{message}

Return ONLY strict JSON:
{{
  "name": "person's name or null",
  "birth_date": "YYYY-MM-DD or null",
  "birth_time": "HH:MM:SS (24h) or null",
  "birth_place": "place text exactly as the user gave it, or null",
  "question": "the user's actual question, details stripped, or null",
  "ambiguities": ["only genuine ambiguities that block a field, phrased as short questions"]
}}

Rules:
- Unlabeled comma/period-separated details are the norm: "Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health in 2026" → name=Sandeep Amar, birth_date=1975-01-25, birth_time=11:00:00, birth_place=New Delhi, question=How is my health in 2026.
- A person's name is NEVER a birth place. A question is NEVER a birth place.
- Dates in DD/MM/YYYY order for Indian users when the day is unambiguous (25/01 → 25 January). If both parts are ≤ 12 (e.g. 03/04/1990) and no other signal disambiguates, leave birth_date null and add one ambiguity question.
- Corrections move values between fields: "Sandeep Amar is my name, birth place - Delhi" sets name=Sandeep Amar and birth_place=Delhi (the earlier wrong value is replaced).
- Only fill a field the message (or prior details) actually supports. Never guess.
- Keep prior values unless this message corrects or adds to them.
- Understand Hinglish and casual phrasing ("subah 6 baje" → 06:00:00).
"""


def _parse_json_block(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _clean_str(value: Any, *, max_len: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .,-")
    if not cleaned or cleaned.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return cleaned[:max_len]


def _validate_profile(raw: dict[str, Any], message: str) -> dict[str, Any]:
    """Deterministically validate/normalize the LLM output. Invalid fields are
    dropped, never guessed."""
    profile: dict[str, Any] = {}

    date_value = _clean_str(raw.get("birth_date"), max_len=40)
    if date_value:
        normalized_date = _normalize_date(date_value)
        if normalized_date:
            profile["birth_date"] = normalized_date

    time_value = _clean_str(raw.get("birth_time"), max_len=40)
    if time_value:
        normalized_time = _normalize_time(time_value)
        if normalized_time:
            profile["birth_time"] = normalized_time

    name = _clean_str(raw.get("name"), max_len=80)
    if name and not re.search(r"\d", name):
        profile["name"] = name

    place = _clean_str(raw.get("birth_place"))
    if place and "?" not in place:
        # The user's own name must never reach the geocoder.
        if not profile.get("name") or place.lower() != profile["name"].lower():
            profile["birth_place"] = place

    question = _clean_str(raw.get("question"), max_len=500)
    if question:
        profile["question"] = question

    ambiguities = raw.get("ambiguities")
    if isinstance(ambiguities, list):
        cleaned_ambiguities = [
            item.strip() for item in ambiguities if isinstance(item, str) and item.strip()
        ][:3]
        if cleaned_ambiguities:
            profile["ambiguities"] = cleaned_ambiguities

    return profile


def _regex_fallback_profile(message: str) -> dict[str, Any]:
    """Deterministic fallback when the LLM is unavailable or returned garbage."""
    normalized, _ = extract_lalkitab_birth_input(message, resolve_known_places=False)
    profile: dict[str, Any] = {"source": "regex_fallback"}
    if normalized.get("date"):
        profile["birth_date"] = normalized["date"]
    if normalized.get("time"):
        profile["birth_time"] = normalized["time"]
    if normalized.get("birth_place"):
        profile["birth_place"] = normalized["birth_place"]
    name = normalized.get("name") or _extract_name(message)
    if name:
        profile["name"] = name
    return profile


async def extract_birth_profile(
    message: str,
    *,
    prior_profile: dict[str, Any] | None = None,
    llm_provider: Any | None = None,
) -> dict[str, Any]:
    """Extract {name, birth_date, birth_time, birth_place, question,
    ambiguities, source} from a user turn.

    Returns only fields established by this message plus carried-over prior
    values; `source` is "llm" or "regex_fallback" so the serving path is
    always observable.
    """
    prior = {
        key: value
        for key, value in (prior_profile or {}).items()
        if key in PROFILE_FIELDS and value not in (None, "")
    }

    if llm_provider is not None:
        try:
            prompt = _EXTRACTION_PROMPT.format(
                prior=json.dumps(prior or {"(none)": True}, ensure_ascii=False),
                message=message,
            )
            response = await llm_provider.generate(prompt, temperature=0, max_tokens=400)
            raw = _parse_json_block(getattr(response, "content", "") or "")
            profile = _validate_profile(raw, message)
            # Carry prior values the model did not restate or correct.
            for key, value in prior.items():
                profile.setdefault(key, value)
            if profile.get("birth_place") and profile.get("name") and (
                profile["birth_place"].strip().lower() == profile["name"].strip().lower()
            ):
                profile.pop("birth_place")
            profile["source"] = "llm"
            return profile
        except Exception as exc:
            logger.warning("birth_profile_llm_extraction_failed", error=str(exc))

    profile = _regex_fallback_profile(message)
    for key, value in prior.items():
        profile.setdefault(key, value)
    return profile
