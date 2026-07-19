"""Safety regressions for chart-first Lal Kitab answers."""

import json
from types import SimpleNamespace

import pytest

from tools.types import ToolResult

from app.services import lalkitab_runtime as lk
from app.services.context_connector_packs import get_connector_pack
from app.services.message_service import MessageService


def _lalkitab_config():
    pack = get_connector_pack("vedika_lal_kitab")
    pack["auth"] = {"type": "bearer", "token": "test"}
    return {"domain": {"template": "astrology_lalkitab"}, "context_connectors": [pack]}


@pytest.mark.asyncio
async def test_chart_connector_failure_requires_safe_abstention_and_hides_provider_error(monkeypatch):
    calls: list[str] = []
    provider_error = "Vedika upstream timeout for 1987-07-16 at 15:26:00"

    async def fake_run(self, query, payload=None, **kwargs):
        calls.append(self.endpoint["id"])
        return ToolResult(success=False, data=None, error=provider_error)

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    result = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(),
        "DOB 1987-07-16 time 15:26:00 lat 28.6139 lon 77.209 timezone Asia/Kolkata. Give remedies.",
    )

    assert calls == [lk.LAL_KITAB_CHART_ENDPOINT]
    assert result.chart_validated is False
    assert result.requires_safe_abstention is True
    assert result.api_context["chart_context"] is None

    public_events = json.dumps(result.events)
    assert provider_error not in public_events
    assert "1987-07-16" not in public_events
    assert "15:26:00" not in public_events
    assert "28.6139" not in public_events


@pytest.mark.asyncio
async def test_malformed_chart_payload_stops_secondary_calls_and_requires_abstention(monkeypatch):
    calls: list[str] = []

    async def fake_run(self, query, payload=None, **kwargs):
        calls.append(self.endpoint["id"])
        return ToolResult(
            success=True,
            data={"error": "provider returned an invalid chart payload"},
        )

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    result = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(),
        "DOB 1987-07-16 time 15:26:00 lat 28.6139 lon 77.209 timezone Asia/Kolkata. Give remedies.",
    )

    assert calls == [lk.LAL_KITAB_CHART_ENDPOINT]
    assert result.chart_validated is False
    assert result.requires_safe_abstention is True
    assert result.api_context["chart_context"] is None
    assert "invalid chart payload" not in json.dumps(result.events)


@pytest.mark.asyncio
async def test_missing_chart_connector_requires_safe_abstention():
    result = await lk.build_lalkitab_runtime_context(
        {"domain": {"template": "astrology_lalkitab"}},
        "Will my career improve according to Lal Kitab?",
    )

    assert result.handled is True
    assert result.chart_validated is False
    assert result.requires_safe_abstention is True
    assert result.abstention_reason == "chart_connector_unavailable"


@pytest.mark.asyncio
async def test_partial_secondary_context_requires_abstention_without_remedy_synthesis(monkeypatch):
    calls: list[str] = []

    async def fake_run(self, query, payload=None, **kwargs):
        endpoint_id = self.endpoint["id"]
        calls.append(endpoint_id)
        if endpoint_id == lk.LAL_KITAB_CHART_ENDPOINT:
            return ToolResult(success=True, data={"chart": {"ascendant": "Aries"}})
        return ToolResult(success=False, data=None, error="remedies provider timeout")

    monkeypatch.setattr(lk.ContextConnectorTool, "run", fake_run)

    result = await lk.build_lalkitab_runtime_context(
        _lalkitab_config(),
        "DOB 1987-07-16 time 15:26:00 lat 28.6139 lon 77.209 timezone Asia/Kolkata. Give remedies.",
    )

    assert calls == [lk.LAL_KITAB_CHART_ENDPOINT, "lalkitab_remedies"]
    assert result.chart_validated is True
    assert result.requires_safe_abstention is True
    assert "remedies provider timeout" not in json.dumps(result.events)


class _NoGenerationProvider:
    async def generate(self, prompt):  # pragma: no cover - must not be reached
        raise AssertionError("Lal Kitab synthesis must not run without a validated chart")


@pytest.mark.asyncio
async def test_missing_validated_chart_returns_deterministic_abstention_without_llm():
    service = MessageService.__new__(MessageService)
    service.llm_provider = _NoGenerationProvider()
    plan = SimpleNamespace(
        api_context={
            "normalized_birth_input": {
                "date": "1987-07-16",
                "time": "15:26:00",
                "latitude": 28.6139,
                "longitude": 77.209,
                "timezone": "+05:30",
            },
            "chart_context": None,
            "secondary_endpoint_results": {},
        },
        tool_results={},
        selected_endpoint_ids=[lk.LAL_KITAB_CHART_ENDPOINT],
        chart_validated=False,
        requires_safe_abstention=True,
        used_cached_context=False,
    )

    result = await service._generate_lalkitab_agent_result(
        message="Will my career improve?",
        chat_history=[],
        lalkitab_plan=plan,
        rag_context={},
        rag_tool_result=None,
    )

    assert result.answer == lk.LAL_KITAB_CHART_UNAVAILABLE_MESSAGE
    assert result.metadata["validation_passed"] is False
    assert result.metadata["validation_confidence"] == 0.0
    assert result.metadata["api_context"] == {
        "chart_available": False,
        "chart_validated": False,
        "secondary_endpoint_ids": [],
        "source_provenance": [],
    }


class _SuccessfulGenerationProvider:
    async def generate(self, prompt):
        return SimpleNamespace(content="Verified chart reading.")


@pytest.mark.asyncio
async def test_validated_chart_keeps_successful_generation_and_public_metadata_private():
    service = MessageService.__new__(MessageService)
    service.llm_provider = _SuccessfulGenerationProvider()
    service.system_prompt = "You are a Lal Kitab guide."
    service.agent_config = _lalkitab_config()
    plan = SimpleNamespace(
        api_context={
            "normalized_birth_input": {
                "date": "1987-07-16",
                "time": "15:26:00",
                "birth_place": "Delhi, India",
                "latitude": 28.6139,
                "longitude": 77.209,
                "timezone": "+05:30",
            },
            "chart_context": {
                "ascendant": "Aries",
                "planets": [{"name": "Sun", "house": 1}],
            },
            "secondary_endpoint_results": {},
            "source_provenance": [{"endpoint_id": "lalkitab_chart", "endpoint_name": "Lal Kitab Chart"}],
        },
        tool_results={},
        selected_endpoint_ids=[lk.LAL_KITAB_CHART_ENDPOINT],
        chart_validated=True,
        requires_safe_abstention=False,
        used_cached_context=False,
    )

    result = await service._generate_lalkitab_agent_result(
        message="What does my chart say?",
        chat_history=[],
        lalkitab_plan=plan,
        rag_context={},
        rag_tool_result=None,
    )

    assert result.answer == "Verified chart reading."
    assert result.metadata["validation_passed"] is True
    assert result.metadata["validation_confidence"] == 1.0
    assert "normalized_birth_input" not in result.metadata["api_context"]
    assert "1987-07-16" not in json.dumps(result.metadata["api_context"])
    assert "birth" not in result.metadata["kundali_chart"]
