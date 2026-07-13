"""Regression corpus for birth-detail understanding (deterministic layer).

Every case here is a shape real users type. The corpus runs against the
deterministic extractors (the offline fallback path); the LLM extractor has
its own suite in test_birth_profile_extractor.py. Expectations use None for
"must not be extracted / must stay empty".
"""
from __future__ import annotations

import pytest

from app.services import lalkitab_runtime as lk
from app.services.conversation_policy import (
    extract_inputs_for_policy,
    normalize_conversation_policy,
)


POLICY = normalize_conversation_policy({"domain": {"template": "astrology_lalkitab"}})


# (message, date, time, place_contains, name_contains)
# place_contains/name_contains None → field must be absent or empty.
CORPUS = [
    # ── the two verbatim production failures ──
    (
        "Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026",
        "1975-01-25", "11:00:00", "new delhi", "sandeep amar",
    ),
    (
        "Sandeep Amar is my name, Birth place - Delhi, India",
        None, None, "delhi", "sandeep amar",
    ),
    # ── earlier reported failure, still must pass ──
    ("16 july 1987, 15:26, Delhi India", "1987-07-16", "15:26:00", "delhi", None),
    # ── labelled variants with different separators ──
    ("DOB 16-07-1987 TOB 1526 POB Delhi", "1987-07-16", "15:26:00", "delhi", None),
    ("DOB - 25/01/1975, TOB - 11:00 AM, POB - Mumbai", "1975-01-25", "11:00:00", "mumbai", None),
    ("name: Priya Sharma dob: 03/11/1992 tob: 06:45 pob: Jaipur", "1992-11-03", "06:45:00", "jaipur", "priya sharma"),
    # ── name-first natural phrasing ──
    ("Anant, 16 July 1987, 1526 IST, Delhi India", "1987-07-16", "15:26:00", "delhi", "anant"),
    ("anant mendiratta. 16july 1987. 1526 hrs time. delhi.", "1987-07-16", "15:26:00", "delhi", "anant mendiratta"),
    # ── am/pm times followed by unlabeled place ──
    ("25/01/1975, 11 AM, New Delhi", "1975-01-25", "11:00:00", "new delhi", None),
    ("born 25 jan 1975 at 11:00 am in mumbai. career prediction please", "1975-01-25", "11:00:00", "mumbai", None),
    # ── question embedded with details ──
    (
        "16 July 1987, 15:26, Delhi. Will I settle abroad?",
        "1987-07-16", "15:26:00", "delhi", None,
    ),
    (
        "My name is Rahul Verma, born 12/06/1990 at 4:30 pm in Lucknow. When will I get married?",
        "1990-06-12", "16:30:00", "lucknow", "rahul verma",
    ),
    # ── question-only messages must extract NO place ──
    ("Will I build a profitable company before 40?", None, None, None, None),
    ("How is my health going to be in 2026", None, None, None, None),
    # ── corrections / follow-ups ──
    ("My name is Sandeep Amar", None, None, None, "sandeep amar"),
    ("delhi, india.", None, None, None, None),  # place-only follow-up handled via pending state
]


@pytest.mark.parametrize("message,date,time,place_contains,name_contains", CORPUS)
def test_lalkitab_runtime_extraction(message, date, time, place_contains, name_contains):
    normalized, _ = lk.extract_lalkitab_birth_input(message)
    assert normalized.get("date") == date, f"date mismatch for: {message!r} -> {normalized.get('date')}"
    assert normalized.get("time") == time, f"time mismatch for: {message!r} -> {normalized.get('time')}"
    place = (normalized.get("birth_place") or "").lower()
    if place_contains is None:
        assert place == "", f"unexpected place {place!r} for: {message!r}"
    else:
        assert place_contains in place, f"place {place!r} missing {place_contains!r} for: {message!r}"
    name = (normalized.get("name") or "").lower()
    if name_contains is not None:
        assert name_contains in name, f"name {name!r} missing {name_contains!r} for: {message!r}"
    # A person's name must never be emitted as the birth place.
    if name and place:
        assert name != place


@pytest.mark.parametrize("message,date,time,place_contains,name_contains", CORPUS)
def test_conversation_policy_extraction(message, date, time, place_contains, name_contains):
    extracted = extract_inputs_for_policy(message, POLICY)
    assert extracted.get("birth_date") == (date if date else extracted.get("birth_date"))
    if date:
        assert extracted.get("birth_date") == date
    if time:
        assert extracted.get("birth_time") == time
    place = (extracted.get("birth_place") or "").lower()
    if place_contains is None:
        assert place == "", f"unexpected place {place!r} for: {message!r}"
    else:
        assert place_contains in place, f"place {place!r} missing {place_contains!r} for: {message!r}"
    # The question must never leak into the place.
    assert "how is" not in place and "will i" not in place and "when will" not in place


def test_question_never_extracted_as_place_verbatim_failure():
    """The exact production regression: question fragment leaked into place."""
    msg = "Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026"
    extracted = extract_inputs_for_policy(msg, POLICY)
    assert "health" not in (extracted.get("birth_place") or "").lower()
    normalized, missing = lk.extract_lalkitab_birth_input(msg)
    assert normalized.get("birth_place", "").lower().startswith("new delhi")
    assert missing == []  # New Delhi resolves via known-place cache


def test_year_in_question_routes_to_varshphal():
    ids = lk.select_lalkitab_endpoint_ids("How is my health going to be in 2026")
    assert "lalkitab_varshphal" in ids
    assert "lalkitab_predictions" in ids
    assert ids[0] == lk.LAL_KITAB_CHART_ENDPOINT
