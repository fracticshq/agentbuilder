"""Deterministic, provider-shape-agnostic Kundali chart rendering helpers."""

from __future__ import annotations

import re
from typing import Any

KUNDALI_RASHIS = [
    ("Aries", "Mesh"), ("Taurus", "Vrishabh"), ("Gemini", "Mithun"),
    ("Cancer", "Kark"), ("Leo", "Simha"), ("Virgo", "Kanya"),
    ("Libra", "Tula"), ("Scorpio", "Vrishchik"), ("Sagittarius", "Dhanu"),
    ("Capricorn", "Makar"), ("Aquarius", "Kumbh"), ("Pisces", "Meen"),
]

KUNDALI_PLANET_CODES = {
    "sun": "Su", "surya": "Su", "moon": "Mo", "chandra": "Mo",
    "mars": "Ma", "mangal": "Ma", "mercury": "Me", "budh": "Me",
    "budha": "Me", "jupiter": "Ju", "guru": "Ju", "brihaspati": "Ju",
    "venus": "Ve", "shukra": "Ve", "saturn": "Sa", "shani": "Sa",
    "rahu": "Ra", "ketu": "Ke",
}
KUNDALI_PLANET_ORDER = ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"]
_KUNDALI_HOUSE_KEYS = ("house", "house_number", "house_no", "bhava", "bhav", "which_house", "house_id")
_KUNDALI_SIGN_KEYS = (
    "sign", "rashi", "zodiac", "sign_name", "rashi_name", "zodiac_sign",
    "sign_number", "rashi_number", "sign_id", "rashi_id",
)
_KUNDALI_ASC_KEYS = ("ascendant", "lagna", "asc", "lagna_sign", "ascendant_sign", "lagna_rashi")


def _kundali_parse_sign(value: Any, _depth: int = 0) -> int | None:
    if isinstance(value, bool) or value is None or _depth > 2:
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if 1 <= number <= 12 else None
    if isinstance(value, str):
        text = value.strip().lower()
        if text.isdigit():
            number = int(text)
            return number if 1 <= number <= 12 else None
        for index, (english, hindi) in enumerate(KUNDALI_RASHIS):
            if text.startswith(english.lower()) or text.startswith(hindi.lower()):
                return index + 1
        return None
    if isinstance(value, dict):
        for key in ("name", "sign", "rashi", "sign_number", "number", "id"):
            parsed = _kundali_parse_sign(value.get(key), _depth + 1)
            if parsed:
                return parsed
    return None


def _kundali_parse_house(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if 1 <= number <= 12 else None
    if isinstance(value, str):
        match = re.match(r"\s*(\d{1,2})\s*(?:st|nd|rd|th)?\b", value.strip().lower())
        if match:
            number = int(match.group(1))
            return number if 1 <= number <= 12 else None
    return None


def _kundali_first(parser, node: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in node:
            parsed = parser(node[key])
            if parsed:
                return parsed
    return None


def _kundali_walk(node: Any, found: dict[str, dict[str, int]], asc_holder: dict[str, Any]) -> None:
    if isinstance(node, dict):
        if asc_holder.get("sign") is None:
            for key in _KUNDALI_ASC_KEYS:
                if key in node:
                    parsed = _kundali_parse_sign(node[key])
                    if parsed:
                        asc_holder["sign"] = parsed
                        break
        name_value = next(
            (node[name_key] for name_key in ("name", "planet", "planet_name", "graha") if isinstance(node.get(name_key), str)),
            None,
        )
        code = KUNDALI_PLANET_CODES.get(str(name_value).strip().lower()) if name_value else None
        if code:
            entry = found.setdefault(code, {})
            house = _kundali_first(_kundali_parse_house, node, _KUNDALI_HOUSE_KEYS)
            sign = _kundali_first(_kundali_parse_sign, node, _KUNDALI_SIGN_KEYS)
            if house and "house" not in entry:
                entry["house"] = house
            if sign and "sign" not in entry:
                entry["sign"] = sign
        for key, value in node.items():
            key_code = KUNDALI_PLANET_CODES.get(str(key).strip().lower())
            if key_code and isinstance(value, dict):
                entry = found.setdefault(key_code, {})
                house = _kundali_first(_kundali_parse_house, value, _KUNDALI_HOUSE_KEYS)
                sign = _kundali_first(_kundali_parse_sign, value, _KUNDALI_SIGN_KEYS)
                if house and "house" not in entry:
                    entry["house"] = house
                if sign and "sign" not in entry:
                    entry["sign"] = sign
            _kundali_walk(value, found, asc_holder)
    elif isinstance(node, list):
        for item in node:
            _kundali_walk(item, found, asc_holder)


def extract_kundali_chart_summary(api_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Derive a render-ready chart without guessing missing placements."""
    if not isinstance(api_context, dict):
        return None
    chart = api_context.get("chart_context")
    if not isinstance(chart, (dict, list)):
        return None
    found: dict[str, dict[str, int]] = {}
    asc_holder: dict[str, Any] = {"sign": None}
    _kundali_walk(chart, found, asc_holder)
    if not found:
        return None

    asc_sign = asc_holder.get("sign")
    if not asc_sign:
        for entry in found.values():
            if entry.get("house") and entry.get("sign"):
                asc_sign = (entry["sign"] - entry["house"]) % 12 + 1
                break

    placements: dict[int, list[str]] = {}
    for code, entry in found.items():
        house = entry.get("house")
        if house is None and asc_sign and entry.get("sign"):
            house = (entry["sign"] - asc_sign) % 12 + 1
        if house:
            placements.setdefault(house, []).append(code)
    if not placements:
        return None

    houses = []
    for house_number in range(1, 13):
        sign_number = ((asc_sign - 1 + house_number - 1) % 12 + 1) if asc_sign else None
        houses.append({
            "house": house_number,
            "sign_number": sign_number,
            "rashi": KUNDALI_RASHIS[sign_number - 1][0] if sign_number else None,
            "rashi_hindi": KUNDALI_RASHIS[sign_number - 1][1] if sign_number else None,
            "planets": sorted(placements.get(house_number, []), key=KUNDALI_PLANET_ORDER.index),
        })
    ascendant = None
    if asc_sign:
        ascendant = {
            "sign_number": asc_sign,
            "name": KUNDALI_RASHIS[asc_sign - 1][0],
            "hindi": KUNDALI_RASHIS[asc_sign - 1][1],
        }
    return {"style": "north_indian", "ascendant": ascendant, "houses": houses}
