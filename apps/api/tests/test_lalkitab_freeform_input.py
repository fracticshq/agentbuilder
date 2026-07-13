"""Free-form birth-detail understanding for the Lal Kitab agent.

Covers the reported failure: "16 july 1987, 15:26, Delhi India" must be
understood as DOB / TOB / POB with the latitude, longitude, and timezone
auto-resolved — the agent must never ask the user for coordinates.
"""
import pytest

from tools.types import ToolResult

from app.services import lalkitab_runtime as lk
from app.services.agent_turn_planner import AgentTurnPlan
from app.services.context_connector_packs import get_connector_pack


def _lalkitab_config():
    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    return {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}


# ── extraction ───────────────────────────────────────────────────────────────

def test_unlabeled_comma_separated_birth_details_are_extracted():
    normalized, missing = lk.extract_lalkitab_birth_input("16 july 1987, 15:26, Delhi India")
    assert normalized["date"] == "1987-07-16"
    assert normalized["time"] == "15:26:00"
    assert normalized["birth_place"].lower().startswith("delhi")
    assert missing == []  # known place resolved to coordinates + timezone


def test_unlabeled_place_extracted_for_unknown_city():
    normalized, _ = lk.extract_lalkitab_birth_input("16 July 1987, 3:26 pm, Springfield")
    assert normalized["birth_place"] == "Springfield"


def test_unlabeled_place_with_prepositions_and_noise():
    normalized, _ = lk.extract_lalkitab_birth_input(
        "born 25 jan 1975 at 11:00 am in mumbai. career prediction please"
    )
    assert normalized["birth_place"].lower() == "mumbai"


def test_message_contains_birth_details_detection():
    assert lk.message_contains_birth_details("16 july 1987, 15:26, Delhi India") is True
    assert lk.message_contains_birth_details("Will I get married soon?") is False
    assert lk.message_contains_birth_details("hello") is False


# ── clarifications never ask for coordinates ────────────────────────────────

def test_clarification_never_asks_for_latitude_longitude():
    normalized, missing = lk.extract_lalkitab_birth_input(
        "16 July 1987, 3:26 pm, Atlantisville", resolve_known_places=True
    )
    text = lk.format_lalkitab_missing_input_clarification(normalized, missing).lower()
    assert "latitude" not in text
    assert "longitude" not in text
    assert "coordinates" not in text


def test_clarification_asks_for_place_when_nothing_resolved():
    normalized, missing = lk.extract_lalkitab_birth_input("dob 16 July 1987, tob 1526")
    text = lk.format_lalkitab_missing_input_clarification(normalized, missing).lower()
    assert "which city" in text or "birth place" in text
    assert "latitude" not in text


# ── one-shot runtime flow: details only, no astrology keyword ───────────────

@pytest.mark.asyncio
async def test_bare_birth_details_build_chart_first(monkeypatch):
    """A message that is nothing but birth details must engage the runtime,
    resolve the place, and call the chart endpoint before any secondary."""
    connector_calls: list[str] = []

    async def fake_run(self, query, payload=None, **kwargs):
        connector_calls.append(self.endpoint["id"])
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"], "payload": payload})

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    out = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(), "16 july 1987, 15:26, Delhi India"
    )

    assert out.handled is True
    assert out.missing_input == []
    assert out.awaiting_place_choice is False
    nbi = out.normalized_birth_input
    assert nbi["datetime"] == "1987-07-16T15:26:00"
    assert nbi["latitude"] == 28.6139
    assert nbi["timezone"] == "+05:30"
    assert connector_calls, "chart endpoint should have been called"
    assert connector_calls[0] == "lalkitab_chart"
    assert out.api_context.get("chart_context") is not None


@pytest.mark.asyncio
async def test_unknown_place_is_geocoded_not_asked_as_coordinates(monkeypatch):
    """Unknown birthplace goes through the Vedika geocoder automatically."""
    async def fake_geocode(connector, endpoint_id, payload, message):
        if endpoint_id == lk.GEOCODE_SEARCH_ENDPOINT:
            return ToolResult(success=True, data={"results": [{
                "placeId": "IN-GJ-Morbi-1", "name": "Morbi", "adminRegion": "Gujarat",
                "country": "India", "countryCode": "IN", "latitude": 22.81,
                "longitude": 70.83, "population": 194947, "timezone": "Asia/Kolkata",
            }]})
        return ToolResult(success=True, data={
            "place": {"latitude": 22.81, "longitude": 70.83},
            "timezoneAtBirth": {"utcOffsetString": "+05:30"},
        })

    async def fake_run(self, query, payload=None, **kwargs):
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"]})

    monkeypatch.setattr(lk, "_call_geocode_endpoint", fake_geocode)
    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    out = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(), "16 july 1987, 15:26, Morbi Gujarat"
    )
    assert out.handled is True
    assert out.missing_input == []
    assert out.normalized_birth_input["latitude"] == 22.81
    assert out.normalized_birth_input["timezone"] == "+05:30"


# ── turn-plan adaptation keeps lal-kitab on the chart-first runtime ─────────

def _service_with_config(config):
    from app.services.message_service import MessageService

    svc = MessageService.__new__(MessageService)
    svc.agent_config = config
    return svc


def test_adapter_strips_planner_tool_plan_for_lalkitab():
    svc = _service_with_config(_lalkitab_config())
    plan = AgentTurnPlan(
        intent="tool_use",
        action="ready",
        tool_plan=[{"tool_id": "lalkitab_chart", "reason": "", "input": {}, "depends_on": None}],
        context_decision={"use_connectors": False},
    )
    plan = svc._adapt_turn_plan_for_lalkitab(plan)
    assert plan.tool_plan == []
    assert plan.context_decision["use_connectors"] is True


def test_adapter_drops_coordinate_missing_inputs():
    svc = _service_with_config(_lalkitab_config())
    plan = AgentTurnPlan(
        intent="collect_input",
        action="ask_missing_input",
        missing_inputs=[
            {"id": "latitude", "label": "latitude", "type": "number"},
            {"id": "longitude", "label": "longitude", "type": "number"},
        ],
        pending_inputs=[
            {"id": "latitude", "label": "latitude", "type": "number"},
            {"id": "longitude", "label": "longitude", "type": "number"},
        ],
        response_text="Please share latitude and longitude.",
    )
    plan = svc._adapt_turn_plan_for_lalkitab(plan)
    assert plan.missing_inputs == []
    assert plan.action == "ready"
    assert plan.should_short_circuit is False


def test_adapter_builds_chart_instead_of_asking_for_question():
    svc = _service_with_config(_lalkitab_config())
    plan = AgentTurnPlan(
        intent="collect_input",
        action="ask_question",
        resolved_inputs={"birth_date": "1987-07-16", "birth_time": "15:26:00", "birth_place": "Delhi, India"},
        response_text="What would you like to ask?",
    )
    plan = svc._adapt_turn_plan_for_lalkitab(plan)
    assert plan.action == "ready"
    assert plan.should_short_circuit is False
    assert plan.context_decision["use_connectors"] is True


def test_adapter_is_noop_for_non_lalkitab_agents():
    svc = _service_with_config({"domain": {"template": "generic"}})
    plan = AgentTurnPlan(
        intent="tool_use",
        action="ready",
        tool_plan=[{"tool_id": "shopify_search", "reason": "", "input": {}, "depends_on": None}],
    )
    plan = svc._adapt_turn_plan_for_lalkitab(plan)
    assert plan.tool_plan  # untouched


# ── kundali chart summary for the visual widget artifact ────────────────────

def test_kundali_summary_from_planet_list_with_houses():
    api_context = {
        "chart_context": {
            "ascendant": "Pisces",
            "planets": [
                {"name": "Jupiter", "house": 12},
                {"name": "Venus", "house": 12},
                {"name": "Sun", "house": 11},
                {"name": "Mercury", "house": 11},
                {"name": "Mars", "house": 10},
                {"name": "Rahu", "house": 9},
                {"name": "Moon", "house": 4},
                {"name": "Saturn", "house": 4},
                {"name": "Ketu", "house": 3},
            ],
        }
    }
    summary = lk.extract_kundali_chart_summary(api_context)
    assert summary is not None
    assert summary["ascendant"]["name"] == "Pisces"
    by_house = {h["house"]: h for h in summary["houses"]}
    assert by_house[12]["planets"] == ["Ju", "Ve"]
    assert by_house[11]["planets"] == ["Su", "Me"]
    assert by_house[4]["planets"] == ["Mo", "Sa"]
    assert by_house[3]["planets"] == ["Ke"]
    assert by_house[1]["planets"] == []
    assert by_house[1]["rashi"] == "Pisces"  # lagna rashi in house 1


def test_kundali_summary_from_sign_only_placements():
    """Houses derived arithmetically from rashi + lagna when not explicit."""
    api_context = {
        "chart_context": {
            "lagna": {"sign_number": 12},
            "grahas": {
                "Sun": {"rashi": "Capricorn"},
                "Mars": {"sign": 9},
            },
        }
    }
    summary = lk.extract_kundali_chart_summary(api_context)
    assert summary is not None
    by_house = {h["house"]: h for h in summary["houses"]}
    assert by_house[11]["planets"] == ["Su"]   # Capricorn(10) with Pisces lagna → 11th
    assert by_house[10]["planets"] == ["Ma"]   # Sagittarius(9) → 10th


def test_kundali_summary_infers_lagna_from_house_and_sign():
    api_context = {
        "chart_context": {
            "planets": [{"planet": "Sun", "house": 11, "sign": "Capricorn"}],
        }
    }
    summary = lk.extract_kundali_chart_summary(api_context)
    assert summary is not None
    assert summary["ascendant"]["name"] == "Pisces"


def test_kundali_summary_none_without_chart_context():
    assert lk.extract_kundali_chart_summary({}) is None
    assert lk.extract_kundali_chart_summary({"chart_context": {"note": "no placements"}}) is None
    assert lk.extract_kundali_chart_summary(None) is None


@pytest.mark.asyncio
async def test_verbatim_failure_one_shot_chart_with_profile(monkeypatch):
    """The exact production failure must now build the chart in one turn,
    keep the name out of geocoding, and route the 2026 health question."""
    connector_calls: list[str] = []

    async def fake_run(self, query, payload=None, **kwargs):
        connector_calls.append(self.endpoint["id"])
        return ToolResult(success=True, data={"endpoint": self.endpoint["id"]})

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    out = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(),
        "Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026",
        birth_profile={
            "source": "llm",
            "name": "Sandeep Amar",
            "birth_date": "1975-01-25",
            "birth_time": "11:00:00",
            "birth_place": "New Delhi",
            "question": "How is my health going to be in 2026",
        },
    )

    assert out.handled is True
    assert out.missing_input == []
    nbi = out.normalized_birth_input
    assert nbi["name"] == "Sandeep Amar"
    assert nbi["datetime"] == "1975-01-25T11:00:00"
    assert nbi["latitude"] == 28.6139  # New Delhi resolved automatically
    assert connector_calls[0] == "lalkitab_chart"
    assert "lalkitab_varshphal" in out.selected_endpoint_ids  # "in 2026"


@pytest.mark.asyncio
async def test_profile_place_correction_invalidates_stale_coordinates(monkeypatch):
    """A corrected birthplace must clear coordinates resolved for the old one."""
    async def fake_run(self, query, payload=None, **kwargs):
        return ToolResult(success=True, data={})

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    out = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(),
        "Birth place - Mumbai actually",
        pending_state={
            "normalized_birth_input": {
                "date": "1975-01-25", "time": "11:00:00",
                "birth_place": "Delhi", "latitude": 28.6139,
                "longitude": 77.209, "timezone": "+05:30",
            }
        },
        birth_profile={"source": "llm", "birth_place": "Mumbai"},
    )
    assert out.normalized_birth_input["birth_place"] == "Mumbai"
    assert out.normalized_birth_input["latitude"] == 19.076  # re-resolved for Mumbai
