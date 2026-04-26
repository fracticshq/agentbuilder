from types import SimpleNamespace

import pytest

from agent_runtime.orchestrator import Orchestrator


class FakeTools:
    def get_tool_schemas(self):
        return []

    def get(self, _name):
        return None


class FailingPlannerLLM:
    async def generate(self, prompt):
        if "Planning Phase" in prompt:
            raise RuntimeError("planner unavailable")
        return SimpleNamespace(content="Direct fallback answer")


class FullyFailingLLM:
    async def generate(self, _prompt):
        raise RuntimeError("llm unavailable")


@pytest.mark.asyncio
async def test_orchestrator_returns_direct_answer_fallback_on_planning_failure():
    orchestrator = Orchestrator(llm=FailingPlannerLLM(), tools=FakeTools())

    result = await orchestrator.run("What is the warranty?")

    assert result.answer == "Direct fallback answer"
    assert result.metadata["fallback"] is True
    assert result.metadata["fallback_stage"] == "direct_answer"
    assert result.metadata["fallback_reason"] == "planning_failed"


@pytest.mark.asyncio
async def test_orchestrator_returns_safe_canned_fallback_when_fallback_llm_fails():
    orchestrator = Orchestrator(llm=FullyFailingLLM(), tools=FakeTools())

    result = await orchestrator.run("What is the warranty?")

    assert result.metadata["fallback"] is True
    assert result.metadata["fallback_stage"] == "safe_canned"
    assert result.metadata["fallback_reason"] == "planning_failed"
    assert "not able to answer that reliably" in result.answer
