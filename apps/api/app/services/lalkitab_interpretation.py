"""Read-only structured interpretation context for the Lal Kitab LLM prompt.

This module never calls the Vedika API, never geocodes, and never invents or
recalculates chart data. It only reshapes the *already-calculated and
already-validated* ``api_context["chart_context"]`` (plus any secondary
endpoint results ``lalkitab_runtime.py`` already fetched and cached) into an
explicit, LLM-friendly structure: planets, houses, ascendant, dasha, and
divisional charts.

``api_context["chart_context"]`` remains the single source of truth for both
the visual kundali chart (``kundali_chart.py`` / ``KundaliChart.tsx``) and
this interpretation context — this module is a projection over that same
data, not a second calculation path.
"""

from __future__ import annotations

import re
from typing import Any

_DASHA_KEY_PATTERN = re.compile(r"dasha", re.IGNORECASE)
_DIVISIONAL_KEY_PATTERN = re.compile(
    r"^(?:d\d{1,2}|navamsa|dashamsa|hora|drekkana|saptamsa|dasamsa|"
    r"divisional|varga|shodasavarga)\b",
    re.IGNORECASE,
)

# Generic greetings / small talk / "what can you do" style capability
# questions must never be answered from chart data, even once a confirmed
# chart already exists for the conversation — a Lal Kitab agent should still
# be able to say hello or describe itself without dragging in astrology.
_META_OR_GREETING_PATTERN = re.compile(
    r"^\s*(?:hi|hello|hey|namaste|namaskar|thanks|thank you|ok|okay|yes|no|bye|goodbye)\s*[.!?]*\s*$"
    r"|\bwhat (?:can|do|you can) you do\b"
    r"|\bwhat you can do\b"
    r"|\bwho are you\b"
    r"|\bwhat are you\b"
    r"|\bhow (?:do|does) (?:this|it|you) work\b"
    r"|\bwhat is this\b",
    re.IGNORECASE,
)


# lalkitab_runtime.py's own astrology-intent keyword list (kept unchanged
# there deliberately) does not cover every term a Lal Kitab agent should
# still recognize — "dasha" in particular is entirely absent, so a message
# like "What is my current dasha?" fails its `message_requires_lalkitab_api`
# check, is treated as not handled, and falls through to the generic
# Orchestrator, which then calls raw Vedika connector tools directly and
# skips the safe chart-first ordering/caching that runtime provides. This
# is a supplementary check, additive only: it is used to force such a
# message onto the dedicated Lal Kitab runtime rather than replacing any
# existing detection.
_SUPPLEMENTARY_ASTROLOGY_INTENT_PATTERN = re.compile(
    r"\bdasha\b|\bmahadasha\b|\bantardasha\b|\bbhukti\b|"
    r"\bnavamsa\b|\bdashamsa\b|\bdivisional\s+chart\b|"
    r"\brich\b|\bwealthy\b|\bfortune\b|\bdestiny\b|"
    # Any keyword-list approach is inherently incomplete against natural
    # phrasing ("married" vs "marriage", "job" vs "career", "money" vs
    # "wealth"...). Once a validated chart already exists for this
    # conversation, virtually any question the user asks is meant for that
    # chart — so life-topic words are covered broadly here rather than one
    # exact keyword at a time.
    r"\bmarr(?:y|ied|iage)\b|\bspouse\b|\bhusband\b|\bwife\b|"
    r"\bjob\b|\bwork\b|\bbusiness\b|\bpromotion\b|\bincome\b|\bmoney\b|"
    r"\bfinance\b|\beducation\b|\bstudy\b|\bstudies\b|\bexam\b|"
    r"\bhealth\b|\billness\b|\bdisease\b|\btravel\b|"
    r"\bchildren\b|\bkids\b|\bfamily\b|\blove\b|\brelationship\b",
    re.IGNORECASE,
)


def is_lalkitab_astrology_intent_message(message: str) -> bool:
    """True for messages carrying astrology intent that
    lalkitab_runtime.py's own keyword detection does not cover (see the
    module note above) — additive only, never used to exclude a message
    that runtime would already recognize on its own."""
    return bool(_SUPPLEMENTARY_ASTROLOGY_INTENT_PATTERN.search(message or ""))


def is_lalkitab_probe_forced_by_existing_chart(
    message: str,
    cached_chart_context: Any,
) -> bool:
    """True when a validated chart already exists for this conversation and
    the message is not a meta/greeting question — meaning it should be
    treated as astrology intent regardless of any keyword list.

    This is the durable fix for the underlying problem keyword lists keep
    running into: once the user already has a confirmed, validated chart on
    screen, almost anything they type next ("where will I get married?",
    "how's my job?", "what about kids?"...) is a real question about that
    chart, not something a fixed vocabulary can ever fully enumerate.
    lalkitab_runtime.py's own `is_valid_lalkitab_context_payload` already
    defines what counts as a validated chart; this function only reads that
    same signal, it does not duplicate or alter it.
    """
    if is_lalkitab_meta_or_greeting_message(message):
        return False
    from .lalkitab_runtime import is_valid_lalkitab_context_payload

    return is_valid_lalkitab_context_payload(cached_chart_context)


def is_lalkitab_meta_or_greeting_message(message: str) -> bool:
    """True for generic greetings/small talk/capability questions that should
    never be routed into chart-based answering, even with a cached chart."""
    text = (message or "").strip()
    if not text:
        return True
    return bool(_META_OR_GREETING_PATTERN.search(text))


def _collect_matching_subtrees(node: Any, pattern: re.Pattern, *, _depth: int = 0) -> dict[str, Any]:
    """Collect ``{key: value}`` for any dict key at any depth matching `pattern`.

    Provider response shapes vary, so dasha/divisional-chart data may live
    under any nesting level and under several plausible field names. This
    only reads keys that are already present in the calculated payload —
    it never fabricates a key or value.
    """
    found: dict[str, Any] = {}
    if _depth > 6:
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and pattern.search(key):
                found.setdefault(str(key), value)
            found.update(_collect_matching_subtrees(value, pattern, _depth=_depth + 1))
    elif isinstance(node, list):
        for item in node:
            found.update(_collect_matching_subtrees(item, pattern, _depth=_depth + 1))
    return found


def strip_unchanged_birth_fields(
    birth_profile: dict[str, Any] | None,
    cached_normalized_birth_input: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Drop birth_date/time/place from a birth profile when they merely
    restate the already-cached, already-charted values rather than
    genuinely new information for this turn.

    The birth-profile extractor deliberately carries forward the
    confirmed date/time/place on every later turn (so a follow-up like
    "what about my career?" never needs to repeat them) — but
    ``build_lalkitab_runtime_context`` treats the mere *presence* of those
    fields on ``birth_profile`` as "the user just gave new birth details,
    recalculate the chart." Passed through unfiltered, that combination
    means a cached, still-valid chart gets silently ignored and Vedika is
    re-queried on literally every turn, which is both unnecessary and the
    direct cause of hitting the provider's rate limit far more than a real
    conversation should. Once a value here matches the cached one, it is
    not new — dropping it here does not affect anything if the values
    genuinely differ (a real correction/new detail is still passed through).
    """
    if not isinstance(birth_profile, dict):
        return birth_profile
    cached = cached_normalized_birth_input if isinstance(cached_normalized_birth_input, dict) else {}
    if not cached:
        return birth_profile

    def _same(profile_key: str, *cache_keys: str) -> bool:
        value = birth_profile.get(profile_key)
        if not value:
            return False
        value_text = str(value).strip().lower()
        return any(str(cached.get(key) or "").strip().lower() == value_text for key in cache_keys)

    filtered = dict(birth_profile)
    if _same("birth_date", "date", "birth_date"):
        filtered.pop("birth_date", None)
    if _same("birth_time", "time", "birth_time"):
        filtered.pop("birth_time", None)
    if _same("birth_place", "birth_place", "birth_place_resolved"):
        filtered.pop("birth_place", None)
    return filtered


def build_lalkitab_interpretation_context(api_context: dict[str, Any] | None) -> dict[str, Any]:
    """Build a clean, explicit interpretation context from the validated
    chart context (plus already-fetched secondary endpoint results).

    ``api_context["chart_context"]`` remains the single source of truth;
    this function only reads and reorganizes already-calculated data — it
    never calls Vedika, never geocodes, and never fills in a value that is
    not present in the data. Callers should treat every field here as
    directly answerable to the user without hedging, and treat every
    missing field as genuinely unavailable (never guessed).
    """
    context = api_context if isinstance(api_context, dict) else {}
    chart = context.get("chart_context")
    secondaries = (
        context.get("secondary_endpoint_results")
        if isinstance(context.get("secondary_endpoint_results"), dict)
        else {}
    )

    interpretation: dict[str, Any] = {
        "ascendant": None,
        "planets": chart if isinstance(chart, (dict, list)) else None,
        "houses": None,
        "dasha": None,
        "divisional_charts": None,
        "debts": None,
        "predictions": None,
        "remedies": None,
        "totke": None,
        "lucky_factors": None,
        "varshphal": None,
    }

    if isinstance(chart, dict):
        for key in ("ascendant", "lagna", "asc"):
            if chart.get(key) is not None:
                interpretation["ascendant"] = chart.get(key)
                break
        for key in ("houses", "house_list", "bhava_chart"):
            if chart.get(key) is not None:
                interpretation["houses"] = chart.get(key)
                break
        for key in ("debts", "rin", "karmic_debts"):
            if chart.get(key) is not None:
                interpretation["debts"] = chart.get(key)
                break

    dasha_hits: dict[str, Any] = {}
    dasha_hits.update(_collect_matching_subtrees(chart, _DASHA_KEY_PATTERN))
    dasha_hits.update(_collect_matching_subtrees(secondaries, _DASHA_KEY_PATTERN))
    if dasha_hits:
        interpretation["dasha"] = dasha_hits

    divisional_hits: dict[str, Any] = {}
    divisional_hits.update(_collect_matching_subtrees(chart, _DIVISIONAL_KEY_PATTERN))
    divisional_hits.update(_collect_matching_subtrees(secondaries, _DIVISIONAL_KEY_PATTERN))
    if divisional_hits:
        interpretation["divisional_charts"] = divisional_hits

    if isinstance(secondaries, dict):
        if secondaries.get("lalkitab_predictions") is not None:
            interpretation["predictions"] = secondaries.get("lalkitab_predictions")
        if secondaries.get("lalkitab_remedies") is not None:
            interpretation["remedies"] = secondaries.get("lalkitab_remedies")
        if secondaries.get("lalkitab_totke") is not None:
            interpretation["totke"] = secondaries.get("lalkitab_totke")
        if secondaries.get("lalkitab_lucky") is not None:
            interpretation["lucky_factors"] = secondaries.get("lalkitab_lucky")
        if secondaries.get("lalkitab_varshphal") is not None:
            interpretation["varshphal"] = secondaries.get("lalkitab_varshphal")
        if secondaries.get("lalkitab_houses") is not None and interpretation["houses"] is None:
            interpretation["houses"] = secondaries.get("lalkitab_houses")
        if secondaries.get("lalkitab_debts") is not None and interpretation["debts"] is None:
            interpretation["debts"] = secondaries.get("lalkitab_debts")

    # Drop empty/None keys so the LLM sees a compact, honest context — no
    # placeholder nulls that could be misread as "this field exists but is
    # empty" when the data was simply never fetched or never present.
    return {key: value for key, value in interpretation.items() if value not in (None, {}, [])}
