import pytest

from tools.types import ToolResult

from app.services import lalkitab_runtime as lk
from app.services.context_connector_packs import get_connector_pack


SPRINGFIELD = [
    {"placeId": "US-MO-Springfield-4409896", "name": "Springfield", "adminRegion": "Missouri",
     "country": "United States", "countryCode": "US", "latitude": 37.2, "longitude": -93.3,
     "population": 166810, "timezone": "America/Chicago"},
    {"placeId": "US-MA-Springfield-4951788", "name": "Springfield", "adminRegion": "Massachusetts",
     "country": "United States", "countryCode": "US", "latitude": 42.1, "longitude": -72.5,
     "population": 154341, "timezone": "America/New_York"},
    {"placeId": "US-IL-Springfield-4250542", "name": "Springfield", "adminRegion": "Illinois",
     "country": "United States", "countryCode": "US", "latitude": 39.8, "longitude": -89.6,
     "population": 116565, "timezone": "America/Chicago"},
]
HYDERABAD = [
    {"placeId": "IN-40-Hyderabad-1269843", "name": "Hyderabad", "adminRegion": "Telangana",
     "country": "India", "countryCode": "IN", "latitude": 17.38, "longitude": 78.45,
     "population": 3597816, "timezone": "Asia/Kolkata"},
    {"placeId": "PK-05-Hyderabad-1176734", "name": "Hyderabad", "adminRegion": "Sindh",
     "country": "Pakistan", "countryCode": "PK", "latitude": 25.39, "longitude": 68.37,
     "population": 1386330, "timezone": "Asia/Karachi"},
]


def _candidates(rows):
    return [lk._normalize_candidate(r) for r in rows]


def _fake_geocoder(search_rows, resolve_offset="+05:30"):
    """Return a stand-in for _call_geocode_endpoint over the two geocode endpoints."""
    async def _call(connector, endpoint_id, payload, message):
        if endpoint_id == lk.GEOCODE_SEARCH_ENDPOINT:
            return ToolResult(success=True, data={"success": True, "count": len(search_rows), "results": search_rows})
        if endpoint_id == lk.GEOCODE_RESOLVE_ENDPOINT:
            chosen = next((r for r in search_rows if r["placeId"] == payload.get("placeId")), search_rows[0])
            return ToolResult(success=True, data={
                "success": True,
                "place": {"latitude": chosen["latitude"], "longitude": chosen["longitude"],
                          "timezone": chosen["timezone"]},
                "timezoneAtBirth": {"utcOffsetString": resolve_offset},
            })
        return ToolResult(success=False, data=None, error="unknown endpoint")
    return _call


def test_country_hint_detection():
    assert lk._country_hint_from_text("born in Hyderabad, Pakistan") == "PK"
    assert lk._country_hint_from_text("Mumbai India") == "IN"
    assert lk._country_hint_from_text("just a city") is None


def test_match_place_choice_region_beats_number_word():
    cands = _candidates(SPRINGFIELD)
    # "one" in "the Illinois one" must NOT win as ordinal-first.
    assert lk.match_place_choice("the Illinois one", cands)["adminRegion"] == "Illinois"
    assert lk.match_place_choice("2", cands)["adminRegion"] == "Massachusetts"
    assert lk.match_place_choice("first", cands)["adminRegion"] == "Missouri"
    assert lk.match_place_choice("nonsense", cands) is None


def test_get_geocoding_config_merges_overrides():
    connector = {"input_resolution": {"geocoding": {"default_country": "US", "max_candidates": 3}}}
    cfg = lk.get_geocoding_config(connector)
    assert cfg["default_country"] == "US"
    assert cfg["max_candidates"] == 3
    assert cfg["enabled"] is True  # untouched default


@pytest.mark.asyncio
async def test_resolve_single_match(monkeypatch):
    monkeypatch.setattr(lk, "_call_geocode_endpoint", _fake_geocoder(SPRINGFIELD[2:3]))
    out = await lk.resolve_birthplace_via_geocoding(
        connector={}, geocoding_cfg=lk.default_geocoding_config(),
        birth_place="Springfield", datetime_iso="1990-05-15T10:30:00", message="born in Springfield")
    assert out["status"] == "resolved"
    assert out["latitude"] == 39.8 and out["timezone"] == "+05:30"


@pytest.mark.asyncio
async def test_default_country_bias_auto_picks(monkeypatch):
    monkeypatch.setattr(lk, "_call_geocode_endpoint", _fake_geocoder(HYDERABAD))
    cfg = lk.default_geocoding_config()  # default_country=IN
    out = await lk.resolve_birthplace_via_geocoding(
        connector={}, geocoding_cfg=cfg,
        birth_place="Hyderabad", datetime_iso="1990-05-15T10:30:00", message="born in Hyderabad")
    assert out["status"] == "resolved"
    assert out["label"].endswith("India")


@pytest.mark.asyncio
async def test_ambiguous_asks_when_no_bias_match(monkeypatch):
    monkeypatch.setattr(lk, "_call_geocode_endpoint", _fake_geocoder(SPRINGFIELD))
    out = await lk.resolve_birthplace_via_geocoding(
        connector={}, geocoding_cfg=lk.default_geocoding_config(),
        birth_place="Springfield", datetime_iso="1990-05-15T10:30:00", message="born in Springfield")
    assert out["status"] == "ambiguous"
    assert len(out["candidates"]) == 3


@pytest.mark.asyncio
async def test_user_hint_overrides_default_country(monkeypatch):
    monkeypatch.setattr(lk, "_call_geocode_endpoint", _fake_geocoder(HYDERABAD, resolve_offset="+05:00"))
    out = await lk.resolve_birthplace_via_geocoding(
        connector={}, geocoding_cfg=lk.default_geocoding_config(),
        birth_place="Hyderabad", datetime_iso="1990-05-15T10:30:00", message="born in Hyderabad, Pakistan")
    assert out["status"] == "resolved"
    assert out["label"].endswith("Pakistan")


@pytest.mark.asyncio
async def test_build_disambiguation_then_resume(monkeypatch):
    monkeypatch.setattr(lk, "_call_geocode_endpoint", _fake_geocoder(SPRINGFIELD))
    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    cfg = {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}

    t1 = await lk.build_lalkitab_runtime_context(
        cfg, "Born in Springfield, dob 15 May 1990, time of birth 10:30 AM. lalkitab remedies.")
    assert t1.awaiting_place_choice is True
    assert len(t1.place_candidates) == 3
    assert t1.pending_state["normalized_birth_input"]["birth_place"].lower() == "springfield"

    # Resume with a bare follow-up that lacks any astrology keyword.
    t2 = await lk.build_lalkitab_runtime_context(cfg, "Illinois", pending_state=t1.pending_state)
    assert t2.handled is True
    assert t2.awaiting_place_choice is False
    nbi = t2.normalized_birth_input
    assert nbi["birth_place_resolved"].endswith("Illinois, United States")
    assert nbi["latitude"] == 39.8


@pytest.mark.asyncio
async def test_missing_input_accumulates_across_turns(monkeypatch):
    monkeypatch.setattr(lk, "_call_geocode_endpoint", _fake_geocoder(SPRINGFIELD[2:3]))
    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    cfg = {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}

    a1 = await lk.build_lalkitab_runtime_context(cfg, "born in Springfield, dob 15 May 1990. lalkitab chart")
    assert "time" in a1.missing_input
    assert a1.pending_state["normalized_birth_input"]["birth_place"].lower() == "springfield"

    a2 = await lk.build_lalkitab_runtime_context(cfg, "time of birth 10:30 AM", pending_state=a1.pending_state)
    # date+place from turn 1 are preserved and merged with the new time.
    assert a2.handled is True
    assert not a2.awaiting_place_choice
    assert a2.normalized_birth_input["latitude"] == 39.8
