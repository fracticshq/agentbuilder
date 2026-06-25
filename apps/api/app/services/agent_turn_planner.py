from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

import structlog

from .conversation_policy import ConversationTurnPlan, make_activity, plan_conversation_turn


logger = structlog.get_logger(__name__)


VALID_INTENTS = {"greeting", "collect_input", "answer", "tool_use", "clarify", "handoff"}


@dataclass
class AgentTurnPlan:
    """LLM-first, schema-guided turn plan.

    This intentionally mirrors the legacy ConversationTurnPlan surface so
    MessageService can migrate incrementally while keeping deterministic parsing
    as fallback only.
    """

    intent: str = "answer"
    action: str = "ready"
    resolved_inputs: dict[str, Any] = field(default_factory=dict)
    extracted_inputs: dict[str, Any] = field(default_factory=dict)
    missing_inputs: list[dict[str, Any]] = field(default_factory=list)
    pending_inputs: list[dict[str, Any]] = field(default_factory=list)
    question: str | None = None
    context_decision: dict[str, Any] = field(default_factory=dict)
    tool_plan: list[dict[str, Any]] = field(default_factory=list)
    public_response: str | None = None
    response_text: str = ""
    activities: list[dict[str, Any]] = field(default_factory=list)
    source: str = "llm"
    raw_plan: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def should_short_circuit(self) -> bool:
        return self.action in {"greeting", "ask_question", "ask_missing_input", "clarify", "handoff"}


class AgentTurnPlanner:
    """LLM-first turn understanding for NOVA agents.

    The planner understands user turns against agent configuration and returns a
    structured plan. It does not execute tools. Deterministic policy parsing is
    only used when the LLM planner is unavailable or returns an unsafe plan.
    """

    def __init__(self, llm_provider: Any | None):
        self.llm_provider = llm_provider

    async def plan(
        self,
        *,
        message: str,
        policy: dict[str, Any],
        previous_state: dict[str, Any],
        tool_schemas: list[dict[str, Any]],
        system_prompt: str,
        fallback_plan: ConversationTurnPlan | None = None,
    ) -> AgentTurnPlan:
        fallback_plan = fallback_plan or plan_conversation_turn(
            message=message,
            policy=policy,
            previous_state=previous_state,
        )
        if not self.llm_provider:
            return self._from_fallback(fallback_plan, reason="llm_provider_unavailable")

        prompt = self._build_prompt(
            message=message,
            policy=policy,
            previous_state=previous_state,
            tool_schemas=tool_schemas,
            system_prompt=system_prompt,
            fallback_plan=fallback_plan,
        )
        try:
            response = await self.llm_provider.generate(prompt, temperature=0, max_tokens=1600)
            plan_data = self._parse_json(response.content)
            return self._coerce_plan(plan_data, fallback_plan=fallback_plan)
        except Exception as exc:
            logger.warning("agent_turn_planner_failed", error=str(exc))
            return self._from_fallback(fallback_plan, reason=str(exc))

    def _build_prompt(
        self,
        *,
        message: str,
        policy: dict[str, Any],
        previous_state: dict[str, Any],
        tool_schemas: list[dict[str, Any]],
        system_prompt: str,
        fallback_plan: ConversationTurnPlan,
    ) -> str:
        compact_tools = []
        for schema in tool_schemas:
            fn = schema.get("function") if isinstance(schema, dict) else {}
            if not isinstance(fn, dict):
                continue
            compact_tools.append(
                {
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "parameters": fn.get("parameters"),
                }
            )

        return f"""
You are NOVA's LLM-first turn planner. Understand the user like a capable agent,
not like a regex parser. Use the agent policy, memory state, and available tools
to decide what should happen next. Do not execute tools.

Agent system prompt:
{system_prompt}

Conversation policy:
{json.dumps(policy, indent=2, sort_keys=True, default=str)}

Previous conversation state:
{json.dumps(previous_state, indent=2, sort_keys=True, default=str)}

Available tools/connectors:
{json.dumps(compact_tools, indent=2, sort_keys=True, default=str)}

Fallback deterministic interpretation, for reference only:
{json.dumps({
    "action": fallback_plan.action,
    "resolved_inputs": fallback_plan.resolved_inputs,
    "pending_inputs": fallback_plan.pending_inputs,
    "context_decision": fallback_plan.context_decision,
}, indent=2, sort_keys=True, default=str)}

User message:
{message}

Return ONLY strict JSON with this shape:
{{
  "intent": "greeting | collect_input | answer | tool_use | clarify | handoff",
  "resolved_inputs": {{}},
  "missing_inputs": [],
  "question": "string or null",
  "context_decision": {{
    "use_memory": true,
    "use_knowledge": false,
    "use_connectors": false,
    "reuse_cached_evidence": false,
    "reason": "short reason"
  }},
  "tool_plan": [
    {{
      "tool_id": "exact tool name or endpoint id",
      "reason": "why this tool is needed",
      "input": {{}},
      "depends_on": null
    }}
  ],
  "public_response": "short direct user-facing response if no tool work is needed, otherwise null",
  "activity": [
    {{
      "activity_id": "stable id",
      "kind": "reasoning | retrieval | tool_call | connector_call | user_input_request | observation | final_answer | custom",
      "status": "queued | running | waiting_for_user | completed | failed",
      "visibility": "public | console | hidden",
      "label": "human progress label",
      "summary": "short public-safe summary",
      "data": {{}},
      "controls": []
    }}
  ]
}}

Rules:
- For greetings, set intent=greeting, no tools, and public_response as a natural greeting.
- If required inputs are missing, set intent=collect_input and missing_inputs.
- If the user gave required details but no question and question_required=true, ask what they want to ask.
- If the agent has enough information and tools are needed, set intent=tool_use with a tool_plan.
- For ordered recipes, include the prerequisite step first.
- If a place/date/time is phrased naturally or unlabeled, still extract it.
- Public response must not mention API, RAG, chunks, connectors, endpoint names, tool calls, or runtime internals unless policy allows it.
"""

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _coerce_plan(self, data: dict[str, Any], *, fallback_plan: ConversationTurnPlan) -> AgentTurnPlan:
        if not isinstance(data, dict):
            raise ValueError("Planner returned non-object JSON")
        intent = str(data.get("intent") or "answer").strip().lower()
        if intent not in VALID_INTENTS:
            intent = "answer"

        resolved = data.get("resolved_inputs") if isinstance(data.get("resolved_inputs"), dict) else {}
        if not resolved and fallback_plan.resolved_inputs:
            resolved = dict(fallback_plan.resolved_inputs)

        missing = data.get("missing_inputs") if isinstance(data.get("missing_inputs"), list) else []
        missing = [self._normalize_missing_input(item) for item in missing if item]
        missing = [item for item in missing if item.get("id")]

        tool_plan = data.get("tool_plan") if isinstance(data.get("tool_plan"), list) else []
        tool_plan = [self._normalize_tool_step(step) for step in tool_plan if isinstance(step, dict)]
        tool_plan = [step for step in tool_plan if step.get("tool_id")]

        public_response = data.get("public_response")
        if public_response is not None:
            public_response = str(public_response).strip() or None

        question = data.get("question")
        if question is not None:
            question = str(question).strip() or None

        context_decision = data.get("context_decision") if isinstance(data.get("context_decision"), dict) else fallback_plan.context_decision
        action = "ready"
        if intent == "greeting":
            action = "greeting"
            public_response = public_response or "Hi, I’m here. Tell me what you’d like help with."
        elif intent == "collect_input" and missing:
            action = "ask_missing_input"
            public_response = public_response or fallback_plan.response_text
        elif intent in {"clarify", "handoff"}:
            action = intent
            public_response = public_response or fallback_plan.response_text
        elif public_response and not tool_plan and not context_decision.get("use_knowledge") and not context_decision.get("use_connectors"):
            action = "ask_question" if self._looks_like_question_prompt(public_response) else "greeting"

        activities = data.get("activity") if isinstance(data.get("activity"), list) else []
        activities = [self._normalize_activity(item) for item in activities if isinstance(item, dict)]
        if not activities:
            activities = self._default_activities(intent, public_response, missing)

        response_text = public_response or ""
        return AgentTurnPlan(
            intent=intent,
            action=action,
            resolved_inputs=resolved,
            extracted_inputs=resolved,
            missing_inputs=missing,
            pending_inputs=missing,
            question=question,
            context_decision=context_decision,
            tool_plan=tool_plan,
            public_response=public_response,
            response_text=response_text,
            activities=activities,
            raw_plan=data,
        )

    def _from_fallback(self, fallback_plan: ConversationTurnPlan, *, reason: str) -> AgentTurnPlan:
        intent = {
            "greeting": "greeting",
            "ask_question": "collect_input",
            "ask_missing_input": "collect_input",
        }.get(fallback_plan.action, "answer")
        return AgentTurnPlan(
            intent=intent,
            action=fallback_plan.action,
            resolved_inputs=fallback_plan.resolved_inputs,
            extracted_inputs=fallback_plan.extracted_inputs,
            missing_inputs=fallback_plan.pending_inputs,
            pending_inputs=fallback_plan.pending_inputs,
            context_decision=fallback_plan.context_decision,
            public_response=fallback_plan.response_text or None,
            response_text=fallback_plan.response_text,
            activities=fallback_plan.activities,
            source="deterministic_fallback",
            error=reason,
        )

    def _normalize_missing_input(self, item: Any) -> dict[str, Any]:
        if isinstance(item, str):
            return {"id": item, "label": item.replace("_", " "), "type": "text"}
        if not isinstance(item, dict):
            return {}
        field_id = str(item.get("id") or item.get("field") or item.get("name") or "").strip()
        return {
            "id": field_id,
            "label": item.get("label") or field_id.replace("_", " "),
            "type": item.get("type") or "text",
        }

    def _normalize_tool_step(self, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool_id": str(step.get("tool_id") or step.get("tool_name") or step.get("endpoint_id") or "").strip(),
            "reason": str(step.get("reason") or step.get("thought") or "").strip(),
            "input": step.get("input") if isinstance(step.get("input"), dict) else {},
            "depends_on": step.get("depends_on"),
        }

    def _normalize_activity(self, item: dict[str, Any]) -> dict[str, Any]:
        return make_activity(
            activity_id=str(item.get("activity_id") or item.get("id") or item.get("kind") or "activity"),
            kind=str(item.get("kind") or "reasoning"),
            status=str(item.get("status") or "completed"),
            visibility=str(item.get("visibility") or "public"),
            label=str(item.get("label") or item.get("summary") or "Working"),
            summary=str(item.get("summary") or ""),
            parent_id=item.get("parent_id"),
            data=item.get("data") if isinstance(item.get("data"), dict) else {},
            controls=item.get("controls") if isinstance(item.get("controls"), list) else [],
        )

    def _default_activities(self, intent: str, public_response: str | None, missing: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if intent == "collect_input":
            return [
                make_activity(
                    activity_id="input:collect",
                    kind="user_input_request",
                    status="waiting_for_user",
                    visibility="public",
                    label="Need a few details",
                    summary=public_response or "I need a little more information before answering.",
                    controls=[
                        {"type": item.get("type") or "text", "id": item["id"], "label": item.get("label") or item["id"]}
                        for item in missing
                        if item.get("id")
                    ],
                )
            ]
        return [
            make_activity(
                activity_id=f"planner:{intent}",
                kind="reasoning",
                status="completed",
                visibility="console",
                label="Understood the turn",
                summary="The planner selected the next action.",
            )
        ]

    def _looks_like_question_prompt(self, text: str) -> bool:
        return bool(re.search(r"\b(what would you like|what do you want|what is your question|please share your question)\b", text or "", re.IGNORECASE))
