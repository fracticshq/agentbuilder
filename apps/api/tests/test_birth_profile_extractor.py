"""LLM birth-profile extractor: schema validation, merging, and fallback."""
from __future__ import annotations

import json

import pytest

from app.services.birth_profile_extractor import extract_birth_profile


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs):
        self.prompts.append(prompt)
        if isinstance(self.payload, Exception):
            raise self.payload
        if isinstance(self.payload, str):
            return FakeResponse(self.payload)
        return FakeResponse(json.dumps(self.payload))


@pytest.mark.asyncio
async def test_llm_extraction_separates_all_fields():
    llm = FakeLLM({
        "name": "Sandeep Amar",
        "birth_date": "1975-01-25",
        "birth_time": "11:00:00",
        "birth_place": "New Delhi",
        "question": "How is my health going to be in 2026",
        "ambiguities": [],
    })
    profile = await extract_birth_profile(
        "Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026",
        llm_provider=llm,
    )
    assert profile["source"] == "llm"
    assert profile["name"] == "Sandeep Amar"
    assert profile["birth_date"] == "1975-01-25"
    assert profile["birth_time"] == "11:00:00"
    assert profile["birth_place"] == "New Delhi"
    assert "health" in profile["question"]


@pytest.mark.asyncio
async def test_invalid_dates_are_dropped_not_guessed():
    llm = FakeLLM({
        "name": None,
        "birth_date": "not-a-date",
        "birth_time": "25:99",
        "birth_place": "Delhi",
        "question": None,
        "ambiguities": [],
    })
    profile = await extract_birth_profile("gibberish", llm_provider=llm)
    assert "birth_date" not in profile
    assert "birth_time" not in profile
    assert profile["birth_place"] == "Delhi"


@pytest.mark.asyncio
async def test_place_equal_to_name_is_dropped():
    llm = FakeLLM({
        "name": "Sandeep Amar",
        "birth_date": None,
        "birth_time": None,
        "birth_place": "Sandeep Amar",
        "question": None,
        "ambiguities": [],
    })
    profile = await extract_birth_profile("Sandeep Amar", llm_provider=llm)
    assert profile.get("name") == "Sandeep Amar"
    assert "birth_place" not in profile


@pytest.mark.asyncio
async def test_prior_profile_carries_forward_and_corrections_replace():
    llm = FakeLLM({
        "name": "Sandeep Amar",
        "birth_date": None,
        "birth_time": None,
        "birth_place": "Delhi, India",
        "question": None,
        "ambiguities": [],
    })
    prior = {"birth_date": "1975-01-25", "birth_time": "11:00:00", "birth_place": "Sandeep Amar"}
    profile = await extract_birth_profile(
        "Sandeep Amar is my name, Birth place - Delhi, India",
        prior_profile=prior,
        llm_provider=llm,
    )
    assert profile["birth_date"] == "1975-01-25"     # carried forward
    assert profile["birth_time"] == "11:00:00"       # carried forward
    assert profile["birth_place"] == "Delhi, India"  # correction replaced the bad value
    assert profile["name"] == "Sandeep Amar"


@pytest.mark.asyncio
async def test_ambiguities_pass_through():
    llm = FakeLLM({
        "name": None,
        "birth_date": None,
        "birth_time": "10:30:00",
        "birth_place": "Pune",
        "question": None,
        "ambiguities": ["Is 03/04/1990 the 3rd of April or the 4th of March?"],
    })
    profile = await extract_birth_profile("03/04/1990, 10:30, Pune", llm_provider=llm)
    assert profile["ambiguities"] == ["Is 03/04/1990 the 3rd of April or the 4th of March?"]
    assert "birth_date" not in profile


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_regex_with_visible_source():
    llm = FakeLLM(RuntimeError("deployment missing"))
    profile = await extract_birth_profile(
        "Sandeep Amar, DOB 25/01/1975, 11 AM, New Delhi. How is my health going to be in 2026",
        llm_provider=llm,
    )
    assert profile["source"] == "regex_fallback"
    assert profile["birth_date"] == "1975-01-25"
    assert profile["birth_time"] == "11:00:00"
    assert profile["birth_place"].lower().startswith("new delhi")
    assert profile["name"].lower() == "sandeep amar"


@pytest.mark.asyncio
async def test_malformed_llm_json_falls_back():
    llm = FakeLLM("sure! here are the details you asked for:")
    profile = await extract_birth_profile("16 july 1987, 15:26, Delhi India", llm_provider=llm)
    assert profile["source"] == "regex_fallback"
    assert profile["birth_date"] == "1987-07-16"
    assert profile["birth_place"].lower().startswith("delhi")


@pytest.mark.asyncio
async def test_no_llm_provider_uses_regex_fallback():
    profile = await extract_birth_profile("16 july 1987, 15:26, Delhi India", llm_provider=None)
    assert profile["source"] == "regex_fallback"
    assert profile["birth_date"] == "1987-07-16"
