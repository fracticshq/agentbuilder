from __future__ import annotations

import json

import pytest

from app.services.agent_turn_planner import AgentTurnPlanner
from app.services.conversation_policy import normalize_conversation_policy, plan_conversation_turn


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    def __init__(self, payload: dict | Exception):
        self.payload = payload

    async def generate(self, prompt: str, **kwargs):
        if isinstance(self.payload, Exception):
            raise self.payload
        return FakeResponse(json.dumps(self.payload))


def astrology_policy():
    return normalize_conversation_policy({"domain": {"template": "astrology_lalkitab"}})


@pytest.mark.asyncio
async def test_llm_planner_extracts_unlabeled_details_without_fallback_action():
    planner = AgentTurnPlanner(FakeLLM({
        "intent": "collect_input",
        "resolved_inputs": {
            "birth_date": "1987-07-16",
            "birth_time": "15:26:00",
            "birth_place": "Delhi, India",
        },
        "missing_inputs": [],
        "question": None,
        "context_decision": {"use_memory": True, "use_knowledge": False, "use_connectors": False, "reuse_cached_evidence": False},
        "tool_plan": [],
        "public_response": "I have your birth date, time, and place. What would you like to ask?",
        "activity": [],
    }))
    fallback = plan_conversation_turn(
        message="anant mendiratta 16 july 1987. delhi born. 1526 hrs.",
        policy=astrology_policy(),
        previous_state={},
    )

    plan = await planner.plan(
        message="anant mendiratta 16 july 1987. delhi born. 1526 hrs.",
        policy=astrology_policy(),
        previous_state={},
        tool_schemas=[],
        system_prompt="",
        fallback_plan=fallback,
    )

    assert plan.source == "llm"
    assert plan.action == "ask_question"
    assert plan.resolved_inputs["birth_place"] == "Delhi, India"
    assert plan.should_short_circuit is True


@pytest.mark.asyncio
async def test_llm_planner_can_return_chart_first_tool_plan():
    planner = AgentTurnPlanner(FakeLLM({
        "intent": "tool_use",
        "resolved_inputs": {
            "birth_date": "1987-07-16",
            "birth_time": "15:26:00",
            "birth_place": "Delhi, India",
        },
        "missing_inputs": [],
        "question": "Will I build a billion dollar company before 40?",
        "context_decision": {"use_memory": True, "use_knowledge": True, "use_connectors": True, "reuse_cached_evidence": False},
        "tool_plan": [
            {"tool_id": "lalkitab_chart", "reason": "Build chart first", "input": {"payload": {"birth_date": "1987-07-16"}}, "depends_on": None},
            {"tool_id": "lalkitab_predictions", "reason": "Assess career timing", "input": {}, "depends_on": "lalkitab_chart"},
        ],
        "public_response": None,
        "activity": [],
    }))
    fallback = plan_conversation_turn(
        message="Will I build a billion dollar company before 40?",
        policy=astrology_policy(),
        previous_state={"resolved_inputs": {"birth_date": "1987-07-16", "birth_time": "15:26:00", "birth_place": "Delhi, India"}},
    )

    plan = await planner.plan(
        message="Will I build a billion dollar company before 40?",
        policy=astrology_policy(),
        previous_state={"resolved_inputs": {"birth_date": "1987-07-16", "birth_time": "15:26:00", "birth_place": "Delhi, India"}},
        tool_schemas=[],
        system_prompt="",
        fallback_plan=fallback,
    )

    assert plan.action == "ready"
    assert [step["tool_id"] for step in plan.tool_plan] == ["lalkitab_chart", "lalkitab_predictions"]


@pytest.mark.asyncio
async def test_planner_failure_uses_deterministic_fallback_only_as_guardrail():
    fallback = plan_conversation_turn(message="hi", policy=astrology_policy(), previous_state={})
    planner = AgentTurnPlanner(FakeLLM(RuntimeError("planner unavailable")))

    plan = await planner.plan(
        message="hi",
        policy=astrology_policy(),
        previous_state={},
        tool_schemas=[],
        system_prompt="",
        fallback_plan=fallback,
    )

    assert plan.source == "deterministic_fallback"
    assert plan.action == "greeting"
    assert "Hi" in plan.response_text
