"""Offline verification for the Lal Kitab chart-answering fix.

Exercises _generate_lalkitab_agent_result directly with a mocked LLM
provider (captures the prompt, returns a scripted answer) and a realistic
validated chart_context, then runs the real claim-evidence guard on the
result. No network/LLM calls.
"""

import pytest
from types import SimpleNamespace

from app.services.lalkitab_interpretation import (
    build_lalkitab_interpretation_context,
    is_lalkitab_meta_or_greeting_message,
)
from app.services.response_validator import validate_claim_evidence


def _api_context():
    return {
        "normalized_birth_input": {
            "date": "1990-05-16", "time": "10:30:00", "birth_place": "Delhi, India",
        },
        "chart_context": {
            "ascendant": "Cancer",
            "houses": [
                {"house": 1, "planets": ["Sun", "Mercury"], "effects": ["Sun exalted - excellent results"]},
                {"house": 5, "planets": ["Mars"], "effects": []},
                {"house": 8, "planets": ["Moon", "Saturn"], "effects": []},
                {"house": 9, "planets": ["Rahu"], "effects": []},
            ],
            "mahadasha": "Saturn",
            "antardasha": "Moon",
            "debts": [],
        },
        "secondary_endpoint_results": {
            "lalkitab_predictions": {"currentAge": 34, "placements": ["career steady"]},
            "lalkitab_remedies": {"overallStrength": "Mixed chart", "placements": ["offer wheat on Sundays"]},
        },
        "source_provenance": [{"endpoint_id": "lalkitab_chart", "endpoint_name": "Lal Kitab Chart"}],
    }


class _CapturingLLM:
    def __init__(self, answer: str):
        self.answer = answer
        self.last_prompt = None

    async def generate(self, prompt: str, **kwargs):
        self.last_prompt = prompt
        return SimpleNamespace(content=self.answer)


@pytest.mark.parametrize("question,answer", [
    (
        "Where is my Moon?",
        "Beta, your Moon sits in the 8th house, together with Saturn. This can bring "
        "emotional depth but also some ups and downs around health and transformation.",
    ),
    (
        "How is my career?",
        "Beta, looking at your chart, your career is steady this year, especially with "
        "the exalted Sun in the 1st house giving you leadership drive and confidence.",
    ),
    (
        "Tell me about my life",
        "Beta, your ascendant is Cancer, with Sun and Mercury exalted in the 1st house "
        "giving you strong self-confidence, while Moon and Saturn in the 8th house bring "
        "emotional depth. Mars in the 5th house adds courage in matters of children.",
    ),
    (
        "When will I get rich?",
        "Beta, your chart shows career steadiness (as noted in the calculated predictions), "
        "and the exalted Sun in the 1st house supports steady financial growth over time.",
    ),
    (
        "What is my current dasha?",
        "Beta, your current dasha is Saturn mahadasha with Moon antardasha, which brings "
        "a period of introspection and steady, disciplined effort in your life.",
    ),
])
@pytest.mark.asyncio
async def test_chart_backed_questions_are_answered_not_refused(question, answer):
    api_context = _api_context()
    interpretation_context = build_lalkitab_interpretation_context(api_context)
    # Sanity: the interpretation context must actually carry dasha data,
    # otherwise the "what is my current dasha" case is not a real test.
    assert interpretation_context.get("dasha") == {"mahadasha": "Saturn", "antardasha": "Moon"}

    metadata = {
        "lalkitab_runtime": True,
        "lalkitab_api_context_full": api_context,
        "lalkitab_rag_context_full": {"chunks": [
            {"doc_id": "lalkitab_document_1", "content": "Sun exalted in the first house grants excellent results and confidence."}
        ]},
        "lalkitab_interpretation_context_full": interpretation_context,
    }
    result = validate_claim_evidence(answer, tool_results={}, runtime_metadata=metadata)
    assert result.is_valid, f"Q: {question!r} -> rejected: {result.metadata}"
    assert not is_lalkitab_meta_or_greeting_message(question), f"{question!r} was wrongly classified as meta/greeting"


@pytest.mark.parametrize("message", [
    "what you can do",
    "what can you do",
    "hi",
    "hello",
    "who are you",
])
def test_meta_and_greetings_never_treated_as_chart_questions(message):
    assert is_lalkitab_meta_or_greeting_message(message) is True


@pytest.mark.parametrize("message", [
    "Where is my Moon?",
    "How is my career?",
    "Tell me about my life",
    "When will I get rich?",
    "What is my current dasha?",
])
def test_real_astrology_questions_never_treated_as_meta(message):
    assert is_lalkitab_meta_or_greeting_message(message) is False


@pytest.mark.asyncio
async def test_end_to_end_generate_lalkitab_agent_result_answers_moon_question():
    """Exercises the real _generate_lalkitab_agent_result (prompt build +
    LLM call + post-response guard) with a mocked LLM, mirroring
    test_lalkitab_safety.py's existing pattern. No network/LLM calls."""
    from app.services.message_service import MessageService

    service = MessageService.__new__(MessageService)
    answer = (
        "Beta, your Moon is placed in the 8th house, sitting with Saturn. "
        "This brings emotional depth but also some ups and downs in health matters."
    )
    service.llm_provider = _CapturingLLM(answer)
    service.system_prompt = "You are a Lal Kitab guide."
    service.agent_config = {"domain": {"template": "astrology_lalkitab"}}
    from app.config import Settings
    service.settings = Settings()

    api_context = _api_context()
    plan = SimpleNamespace(
        api_context=api_context,
        tool_results={},
        selected_endpoint_ids=["lalkitab_chart"],
        chart_validated=True,
        requires_safe_abstention=False,
        used_cached_context=True,
    )

    result = await service._generate_lalkitab_agent_result(
        message="Where is my Moon?",
        chat_history=[],
        lalkitab_plan=plan,
        rag_context={},
        rag_tool_result=None,
    )

    assert result.answer == answer
    assert result.metadata["validation_passed"] is True
    # The prompt actually sent to the LLM must contain the structured
    # interpretation context (dasha in this case) so the model can look the
    # value up directly instead of parsing the raw nested payload.
    assert "Chart Interpretation Context" in service.llm_provider.last_prompt
    assert "mahadasha" in service.llm_provider.last_prompt

    guard_result = service._apply_post_response_guardrails(result.answer, result.metadata)
    final_text, final_metadata = guard_result
    assert final_text == answer
    assert final_metadata.get("fallback") is not True


def test_full_reading_with_mandatory_empty_house_table_rows_is_not_rejected():
    """Regression test: when the kundali_chart visual artifact is disabled,
    the prompt mandates a full 12-row markdown table including empty houses
    (e.g. "| 10 | — | — |"). Those placeholder rows must never be treated as
    unsupported factual claims about the number 10/11/12 — that was the
    exact bug causing every full-format reading to be discarded."""
    api_context = {
        "normalized_birth_input": {"date": "1987-07-16", "time": "15:26:00", "birth_place": "Lucknow, India"},
        "chart_context": {
            "ascendant": "Cancer",
            "houses": [
                {"house": 1, "planets": ["Sun", "Mercury"], "effects": []},
                {"house": 8, "planets": ["Moon", "Saturn"], "effects": []},
            ],
        },
        "secondary_endpoint_results": {
            "lalkitab_predictions": {"currentAge": 34, "placements": []},
            "lalkitab_remedies": {"overallStrength": "Mixed chart", "placements": []},
        },
    }
    metadata = {
        "lalkitab_runtime": True,
        "lalkitab_api_context_full": api_context,
        "lalkitab_rag_context_full": {},
    }
    answer = (
        "Beta, your birth details are confirmed: 16 July 1987, 15:26, Lucknow, India.\n\n"
        "| House | Rashi | Planets |\n"
        "|-------|-------|---------|\n"
        "| 1 | Cancer | Sun, Mercury |\n"
        "| 2 | — | — |\n"
        "| 3 | — | — |\n"
        "| 8 | Aquarius | Moon, Saturn |\n"
        "| 10 | — | — |\n"
        "| 11 | — | — |\n"
        "| 12 | — | — |\n\n"
        "Where the planets sit: In the 1st house, Sun sits with Mercury, giving you natural "
        "leadership. In the 8th house, Moon sits with Saturn, bringing depth but some emotional "
        "ups and downs.\n\n"
        "Career: with Sun and Mercury in the 1st house, you carry sharp thinking and confidence.\n\n"
        "Lal Kitab remedies: Offer jaggery to birds every Wednesday.\n\n"
        "The final word: with steady effort, beta, this chart has real strength to build on.\n\n"
        "Lal Kitab reading is a guidance tradition, not a guarantee - your own conduct and effort "
        "remain the biggest remedy."
    )
    result = validate_claim_evidence(answer, tool_results={}, runtime_metadata=metadata)
    assert result.is_valid, result.metadata


def test_fabricated_house_row_in_table_is_still_rejected():
    """A table row with a real (non-empty) fabricated placement must still
    fail — the empty-row exemption must not become a hallucination hole."""
    api_context = {
        "chart_context": {
            "ascendant": "Cancer",
            "houses": [{"house": 1, "planets": ["Sun"], "effects": []}],
        },
    }
    metadata = {
        "lalkitab_runtime": True,
        "lalkitab_api_context_full": api_context,
        "lalkitab_rag_context_full": {},
    }
    bad_answer = "| House | Rashi | Planets |\n|-------|-------|---------|\n| 3 | Leo | Venus, Rahu |"
    result = validate_claim_evidence(bad_answer, tool_results={}, runtime_metadata=metadata)
    assert result.is_valid is False


def test_planet_abbreviation_and_ordinal_house_answers_are_not_falsely_rejected():
    """Regression test: Vedika's chart/predictions payloads store planets as
    short codes ("Me", "Ra", "Su"...) and house numbers as plain integers,
    while a correct Lal Kitab reading writes full planet names ("Mercury",
    "Rahu") and ordinals ("10th house") per the prompt's own formatting
    rules. Before the token-canonicalization fix, this vocabulary mismatch
    caused entirely correct, well-grounded readings to be randomly
    discarded as "unsupported.\""""
    api_context = {
        "normalized_birth_input": {"date": "2005-03-10", "time": "13:05:00", "birth_place": "Lucknow, India"},
        "chart_context": {
            "success": True,
            "data": {
                "ascendant": "Leo",
                "houses": [
                    {"house": 4, "planets": ["Ju", "Ke"], "effects": []},
                    {"house": 10, "planets": ["Me", "Ra"], "effects": []},
                    {"house": 11, "planets": ["Ma"], "effects": []},
                ],
            },
        },
        "secondary_endpoint_results": {
            "lalkitab_predictions": {"success": True, "data": {"currentAge": 21, "placements": []}},
        },
    }
    metadata = {
        "lalkitab_runtime": True,
        "lalkitab_api_context_full": api_context,
        "lalkitab_rag_context_full": {},
    }
    answer = (
        "Beta, your birth details are confirmed: 10 March 2005, 13:05, Lucknow, India. "
        "Your ascendant is Leo.\n\n"
        "Where the planets sit: In the 4th house, Jupiter and Ketu sit together. "
        "In the 10th house, Mercury and Rahu sit. In the 11th house, Mars sits alone.\n\n"
        "Career: with Mercury and Rahu in the 10th house of career, you have sharp "
        "communication skills and unconventional thinking.\n\n"
        "The final word: with steady effort, beta, this combination brings real growth.\n\n"
        "Lal Kitab reading is a guidance tradition, not a guarantee - your own conduct "
        "and effort remain the biggest remedy."
    )
    result = validate_claim_evidence(answer, tool_results={}, runtime_metadata=metadata)
    assert result.is_valid, result.metadata


def test_planet_in_wrong_house_still_fails_after_canonicalization_fix():
    """The abbreviation/ordinal canonicalization must not create a new
    hallucination hole: a real, non-empty, but wrong house/planet claim
    (Mars claimed in house 10, but the chart has it in house 11) must still
    fail the anchor check."""
    api_context = {
        "chart_context": {"data": {"houses": [{"house": 11, "planets": ["Ma"], "effects": []}]}},
    }
    metadata = {
        "lalkitab_runtime": True,
        "lalkitab_api_context_full": api_context,
        "lalkitab_rag_context_full": {},
    }
    bad_answer = "House 10: Mars. This placement in the 10th house of career brings great success."
    result = validate_claim_evidence(bad_answer, tool_results={}, runtime_metadata=metadata)
    assert result.is_valid is False


@pytest.mark.asyncio
async def test_unchanged_birth_profile_reuses_cached_chart_without_recalling_vedika(monkeypatch):
    """Regression test: the confirmed birth profile is carried forward on
    every later turn (so follow-ups never repeat birth details) — but
    passing it through unfiltered made build_lalkitab_runtime_context treat
    its mere presence as "new birth details," recalculating the chart from
    Vedika on literally every single question and needlessly burning the
    provider's rate limit. strip_unchanged_birth_fields must remove
    birth_date/time/place once they only restate the cached chart's own
    values, so an ordinary follow-up reuses the cached chart instead."""
    from app.services import lalkitab_runtime as lk
    from app.services.context_connector_packs import get_connector_pack
    from app.services.lalkitab_interpretation import strip_unchanged_birth_fields

    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    config = {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}

    connector_calls = []

    async def fake_run(self, query, payload=None, **kwargs):
        connector_calls.append(self.endpoint["id"])
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"], "ascendant": "Leo"})

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    birth_profile = {
        "source": "llm",
        "name": "Arjuna Singh",
        "birth_date": "1985-07-04",
        "birth_time": "06:10:00",
        "birth_place": "Lucknow, India",
        "question": "Tell me about my life",
    }
    cached_normalized = {
        "date": "1985-07-04", "time": "06:10:00", "birth_place": "Lucknow, India",
        "latitude": 26.8467, "longitude": 80.9462, "timezone": "+05:30",
    }
    pending_state = {
        "api_context": {
            "chart_context": {"ascendant": "Leo", "houses": [{"house": 1, "planets": ["Su", "Ma"], "effects": []}]},
            "secondary_endpoint_results": {
                "lalkitab_predictions": {"currentAge": 40, "placements": []},
                "lalkitab_remedies": {"overallStrength": "Mixed chart", "placements": []},
            },
            "normalized_birth_input": cached_normalized,
        },
    }

    filtered_profile = strip_unchanged_birth_fields(birth_profile, cached_normalized)
    assert "birth_date" not in filtered_profile
    assert "birth_time" not in filtered_profile
    assert "birth_place" not in filtered_profile
    assert filtered_profile["question"] == "Tell me about my life"

    out = await lk.build_lalkitab_runtime_context(
        config,
        "Tell me about my life",
        pending_state=pending_state,
        birth_profile=filtered_profile,
    )
    assert connector_calls == [], "cached chart should be reused, not re-fetched from Vedika"
    assert out.used_cached_context is True


def test_strip_unchanged_birth_fields_still_passes_through_a_real_correction():
    """A genuine correction (a new place that differs from the cache) must
    not be stripped — only fields that merely restate the cache are dropped."""
    from app.services.lalkitab_interpretation import strip_unchanged_birth_fields

    birth_profile = {"birth_date": "1985-07-04", "birth_time": "06:10:00", "birth_place": "Mumbai, India"}
    cached_normalized = {"date": "1985-07-04", "time": "06:10:00", "birth_place": "Lucknow, India"}
    filtered = strip_unchanged_birth_fields(birth_profile, cached_normalized)
    assert filtered["birth_place"] == "Mumbai, India"
    assert "birth_date" not in filtered
    assert "birth_time" not in filtered


def test_lalkitab_probe_message_appends_hint_only_when_runtime_would_miss_intent():
    """Regression test: lalkitab_runtime.py's own keyword list has no
    "dasha" term, so "What is my current dasha?" alone was falling through
    to the generic Orchestrator (which calls raw Vedika tools directly and
    skips chart-first ordering/caching) instead of the dedicated Lal Kitab
    runtime. _lalkitab_probe_message must append a recognized hint only in
    that gap — never for messages the runtime already understands, and
    never affecting the real message used for the actual answer."""
    from app.services.message_service import MessageService

    service = MessageService.__new__(MessageService)

    probed = service._lalkitab_probe_message("What is my current dasha?")
    assert probed != "What is my current dasha?"
    assert "lal kitab" in probed.lower()

    # Runtime already recognizes these — must pass through unchanged.
    for message in ("How is my career?", "Where is my Moon?", "DOB 1990-01-01, 10:00, Delhi"):
        assert service._lalkitab_probe_message(message) == message


@pytest.mark.asyncio
async def test_dasha_only_question_is_now_handled_by_lalkitab_runtime(monkeypatch):
    """End-to-end confirmation: with the probe applied, a bare dasha
    question is now routed to (and handled by) the dedicated Lal Kitab
    runtime instead of falling through to the generic Orchestrator."""
    from app.services import lalkitab_runtime as lk
    from app.services.context_connector_packs import get_connector_pack
    from app.services.message_service import MessageService

    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    config = {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}

    async def fake_run(self, query, payload=None, **kwargs):
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"], "ascendant": "Leo"})

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    service = MessageService.__new__(MessageService)
    probed_message = service._lalkitab_probe_message("What is my current dasha?")

    # Without the probe, this question is NOT handled (reproduces the bug).
    unprobed = await lk.build_lalkitab_runtime_context(
        config, "What is my current dasha?", pending_state={}, birth_profile=None,
    )
    assert unprobed.handled is False

    # With the probe applied (as message_service.py now does), it IS handled.
    probed_result = await lk.build_lalkitab_runtime_context(
        config, probed_message, pending_state={}, birth_profile=None,
    )
    assert probed_result.handled is True


def test_probe_forced_by_existing_chart_for_married_question():
    """Regression test matching the exact reported bug: with a validated
    chart already on screen, "where I will get married" (no exact keyword
    match in lalkitab_runtime.py's own list — "marry"/"married" is not
    "marriage") was falling through to the generic Orchestrator instead of
    the dedicated Lal Kitab runtime (fewer steps, RAG/chart-context skipped,
    wrong "no verified chart data" answer). Once a validated chart exists,
    any non-meta question must be forced onto the dedicated runtime."""
    from app.services.lalkitab_interpretation import is_lalkitab_probe_forced_by_existing_chart

    chart = {"ascendant": "Scorpio", "houses": [{"house": 1, "planets": ["Ke"], "effects": []}]}
    assert is_lalkitab_probe_forced_by_existing_chart("where I will get married", chart) is True
    assert is_lalkitab_probe_forced_by_existing_chart("How is my career?", chart) is True
    # Greetings/meta questions must still be excluded even with a chart.
    assert is_lalkitab_probe_forced_by_existing_chart("hi", chart) is False
    assert is_lalkitab_probe_forced_by_existing_chart("what can you do", chart) is False
    # No chart yet -> must not force routing (there's nothing to answer from).
    assert is_lalkitab_probe_forced_by_existing_chart("where I will get married", None) is False
    assert is_lalkitab_probe_forced_by_existing_chart("where I will get married", {}) is False


def test_probe_message_uses_broadened_check_with_cached_chart():
    from app.services.message_service import MessageService

    service = MessageService.__new__(MessageService)
    chart = {"ascendant": "Scorpio", "houses": [{"house": 1, "planets": ["Ke"], "effects": []}]}

    probed = service._lalkitab_probe_message("where I will get married", chart)
    assert probed != "where I will get married"
    assert "lal kitab" in probed.lower()

    # "married" is itself a recognized life-topic keyword (see
    # _SUPPLEMENTARY_ASTROLOGY_INTENT_PATTERN), so it is probed even
    # without a cached chart — the chart-presence check exists as a
    # broader catch-all for words that pattern doesn't happen to cover.
    assert service._lalkitab_probe_message("where I will get married", None) != "where I will get married"

    # A truly unrecognized message with no chart is left unchanged (there
    # is nothing yet to route it against).
    assert service._lalkitab_probe_message("what a lovely day", None) == "what a lovely day"

    # A message the runtime already understands passes through untouched
    # regardless of chart presence.
    assert service._lalkitab_probe_message("How is my career?", chart) == "How is my career?"


@pytest.mark.asyncio
async def test_married_question_with_existing_chart_is_now_handled_end_to_end(monkeypatch):
    from app.services import lalkitab_runtime as lk
    from app.services.context_connector_packs import get_connector_pack
    from app.services.message_service import MessageService

    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    config = {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}

    async def fake_run(self, query, payload=None, **kwargs):
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"], "ascendant": "Scorpio"})

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    service = MessageService.__new__(MessageService)
    chart = {"ascendant": "Scorpio", "houses": [{"house": 1, "planets": ["Ke"], "effects": []}]}
    probed_message = service._lalkitab_probe_message("where I will get married", chart)

    pending_state = {"api_context": {"chart_context": chart, "normalized_birth_input": {
        "date": "2003-03-10", "time": "01:10:00", "birth_place": "Lucknow, India",
    }}}

    unprobed = await lk.build_lalkitab_runtime_context(
        config, "where I will get married", pending_state=pending_state, birth_profile=None,
    )
    assert unprobed.handled is False  # reproduces the bug

    probed_result = await lk.build_lalkitab_runtime_context(
        config, probed_message, pending_state=pending_state, birth_profile=None,
    )
    assert probed_result.handled is True  # fixed


def test_hallucinated_dasha_without_evidence_is_still_rejected():
    metadata = {
        "lalkitab_runtime": True,
        "lalkitab_api_context_full": {"chart_context": {"ascendant": "Aries"}},
        "lalkitab_rag_context_full": {},
        "lalkitab_interpretation_context_full": {"ascendant": "Aries"},
    }
    bad_answer = "Your current dasha is Venus mahadasha with Rahu antardasha."
    result = validate_claim_evidence(bad_answer, tool_results={}, runtime_metadata=metadata)
    assert result.is_valid is False
