from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any


ActivityStatus = "queued | running | waiting_for_user | completed | failed"


GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "namaste",
    "namaskar",
    "good morning",
    "good afternoon",
    "good evening",
}


QUESTION_TERMS = (
    "what",
    "why",
    "how",
    "when",
    "where",
    "which",
    "who",
    "will",
    "should",
    "can",
    "could",
    "would",
    "is",
    "are",
    "do",
    "does",
    "tell me",
    "suggest",
    "recommend",
    "help me",
    "advice",
    "guidance",
    "query",
    "question",
)


@dataclass
class ConversationTurnPlan:
    action: str = "ready"
    resolved_inputs: dict[str, Any] = field(default_factory=dict)
    extracted_inputs: dict[str, Any] = field(default_factory=dict)
    pending_inputs: list[dict[str, Any]] = field(default_factory=list)
    response_text: str = ""
    activities: list[dict[str, Any]] = field(default_factory=list)
    context_decision: dict[str, Any] = field(default_factory=dict)

    @property
    def should_short_circuit(self) -> bool:
        return self.action in {"greeting", "ask_question", "ask_missing_input"}


def make_activity(
    *,
    activity_id: str,
    kind: str,
    status: str,
    label: str,
    summary: str = "",
    visibility: str = "public",
    parent_id: str | None = None,
    data: dict[str, Any] | None = None,
    controls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "parent_id": parent_id,
        "kind": kind,
        "status": status,
        "visibility": visibility,
        "label": label,
        "summary": summary,
        "data": data or {},
        "controls": controls or [],
    }


def activity_stream_response_kwargs(activity: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    return {
        "type": "activity",
        "content": activity.get("summary") or activity.get("label") or "",
        "conversation_id": conversation_id,
        "metadata": {"activity": activity},
    }


def normalize_conversation_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    explicit = config.get("conversation_policy")
    if isinstance(explicit, dict):
        return _merge_policy(_default_policy(config), explicit)
    return _default_policy(config)


def _merge_policy(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {**base, **override}
    for key in ("context_policy", "memory_policy", "public_progress_style", "input_extraction_hints"):
        if isinstance(base.get(key), dict) or isinstance(override.get(key), dict):
            merged[key] = {
                **(base.get(key) if isinstance(base.get(key), dict) else {}),
                **(override.get(key) if isinstance(override.get(key), dict) else {}),
            }
    for list_key in ("required_inputs", "tool_recipes"):
        if isinstance(override.get(list_key), list):
            merged[list_key] = override[list_key]
    return merged


def _default_policy(config: dict[str, Any]) -> dict[str, Any]:
    domain = config.get("domain") if isinstance(config.get("domain"), dict) else {}
    template = domain.get("template") or config.get("agent_template") or config.get("template")
    if not template:
        connector_text = " ".join(
            f"{connector.get('id', '')} {connector.get('name', '')} "
            + " ".join(str(endpoint.get("id", "")) for endpoint in (connector.get("endpoints") or []) if isinstance(endpoint, dict))
            for connector in (config.get("context_connectors") or [])
            if isinstance(connector, dict)
        ).lower()
        if "lalkitab" in connector_text or "lal kitab" in connector_text:
            template = "astrology_lalkitab"
    template = template or "generic"
    base = {
        "goal": "",
        "planner_model": None,
        "required_inputs": [],
        "question_required": False,
        "input_extraction_hints": {"infer_unlabeled_values": True},
        "answer_style": "helpful",
        "tool_recipes": [],
        "public_progress_style": {
            "initial_label": "Reading your message",
            "initial_summary": "I’m checking what is needed before answering.",
        },
        "hide_internal_sources": True,
        "context_policy": {
            "lazy_context": True,
            "use_knowledge_when_needed": True,
            "use_connectors_when_needed": True,
        },
        "memory_policy": {
            "cache_evidence": True,
            "invalidation_fields": [],
        },
        "allowed_capabilities": [],
    }
    if template == "astrology_lalkitab":
        base.update(
            {
                "goal": "Provide human, practical Lal Kitab and Vedic astrology guidance.",
                "planner_model": config.get("planner_model") or "gpt-5.5-low",
                "required_inputs": [
                    {
                        "id": "birth_date",
                        "label": "birth date",
                        "type": "date",
                        "required": True,
                        "aliases": ["birth date", "date of birth", "dob", "born"],
                    },
                    {
                        "id": "birth_time",
                        "label": "birth time",
                        "type": "time",
                        "required": True,
                        "aliases": ["birth time", "time of birth", "tob", "born at"],
                    },
                    {
                        "id": "birth_place",
                        "label": "birth place",
                        "type": "place",
                        "required": True,
                        "aliases": ["birth place", "place of birth", "birthplace", "pob", "born in"],
                    },
                ],
                "question_required": True,
                "answer_style": "human_astrologer",
                "tool_recipes": [
                    {
                        "id": "vedika_lal_kitab_chart_first",
                        "description": "For chart-specific Lal Kitab answers, resolve birthplace if needed, call chart first, then call only the relevant secondary Lal Kitab endpoints.",
                        "steps": [
                            {
                                "tool_id": "lalkitab_chart",
                                "required": True,
                                "order": 1,
                                "reason": "Build the base Lal Kitab chart before using any secondary calculated endpoint.",
                            },
                            {
                                "tool_id": "lalkitab_predictions",
                                "order": 2,
                                "when": "future, career, timing, relocation, relationship, or broad life questions",
                                "depends_on": "lalkitab_chart",
                            },
                            {
                                "tool_id": "lalkitab_remedies",
                                "order": 2,
                                "when": "remedy, upay, totke, problem-solving, or mitigation questions",
                                "depends_on": "lalkitab_chart",
                            },
                            {
                                "tool_id": "lalkitab_totke",
                                "order": 2,
                                "when": "totke or practical remedial action questions",
                                "depends_on": "lalkitab_chart",
                            },
                            {
                                "tool_id": "lalkitab_houses",
                                "order": 2,
                                "when": "house, placement, planet, or chart structure questions",
                                "depends_on": "lalkitab_chart",
                            },
                            {
                                "tool_id": "lalkitab_debts",
                                "order": 2,
                                "when": "debt, rin, karmic, obligation, or ancestral questions",
                                "depends_on": "lalkitab_chart",
                            },
                            {
                                "tool_id": "lalkitab_lucky",
                                "order": 2,
                                "when": "lucky, favorable, color, number, date, or timing questions",
                                "depends_on": "lalkitab_chart",
                            },
                            {
                                "tool_id": "lalkitab_varshphal",
                                "order": 2,
                                "when": "annual, yearly, varshphal, or age/year specific questions",
                                "depends_on": "lalkitab_chart",
                            },
                        ],
                    }
                ],
                "memory_policy": {
                    "cache_evidence": True,
                    "invalidation_fields": ["birth_date", "birth_time", "birth_place"],
                },
            }
        )
    return base


def plan_conversation_turn(
    *,
    message: str,
    policy: dict[str, Any],
    previous_state: dict[str, Any] | None = None,
) -> ConversationTurnPlan:
    previous_state = previous_state or {}
    previous_inputs = previous_state.get("resolved_inputs") if isinstance(previous_state.get("resolved_inputs"), dict) else {}
    previous_pending = previous_state.get("pending_inputs") if isinstance(previous_state.get("pending_inputs"), list) else []
    extracted = extract_inputs_for_policy(message, policy)
    if not extracted.get("birth_place") and _is_pending_field(previous_pending, "birth_place"):
        pending_place = _extract_place_only_reply(message)
        if pending_place:
            extracted["birth_place"] = pending_place
    resolved = {**previous_inputs, **{k: v for k, v in extracted.items() if v not in (None, "")}}
    required = [field for field in policy.get("required_inputs") or [] if isinstance(field, dict) and field.get("required", True)]
    missing = [
        {
            "id": field.get("id"),
            "label": field.get("label") or str(field.get("id", "")).replace("_", " "),
            "type": field.get("type") or "text",
        }
        for field in required
        if field.get("id") and resolved.get(field.get("id")) in (None, "")
    ]

    clean = _clean_message(message)
    has_question = message_has_question(message)
    has_extracted = bool(extracted)
    if is_greeting(message) and not has_extracted:
        return ConversationTurnPlan(
            action="greeting",
            resolved_inputs=resolved,
            extracted_inputs=extracted,
            response_text="Hi, I’m here. Tell me what you’d like help with.",
            context_decision={"use_context": False, "reason": "greeting"},
            activities=[
                make_activity(
                    activity_id="understand:greeting",
                    kind="reasoning",
                    status="completed",
                    visibility="console",
                    label="Recognized greeting",
                    summary="No context or tool work needed.",
                    data={"message": clean},
                )
            ],
        )

    if policy.get("question_required") and has_extracted and not has_question and not missing:
        details = format_resolved_inputs(resolved, policy)
        question = f"I have your details as {details}. What would you like to ask?"
        return ConversationTurnPlan(
            action="ask_question",
            resolved_inputs=resolved,
            extracted_inputs=extracted,
            response_text=question,
            context_decision={"use_context": False, "reason": "details_without_question"},
            activities=[
                make_activity(
                    activity_id="input:details_received",
                    kind="user_input_request",
                    status="waiting_for_user",
                    label="Details received",
                    summary=question,
                    data={"resolved_inputs": resolved},
                    controls=[{"type": "text", "id": "question", "label": "Your question"}],
                )
            ],
        )

    if missing and (has_question or has_extracted):
        response = format_missing_input_request(missing, resolved, policy)
        return ConversationTurnPlan(
            action="ask_missing_input",
            resolved_inputs=resolved,
            extracted_inputs=extracted,
            pending_inputs=missing,
            response_text=response,
            context_decision={"use_context": False, "reason": "missing_required_inputs"},
            activities=[
                make_activity(
                    activity_id="input:missing_required",
                    kind="user_input_request",
                    status="waiting_for_user",
                    label="Need a few details",
                    summary=response,
                    data={"resolved_inputs": resolved, "missing_inputs": missing},
                    controls=[
                        {"type": field.get("type") or "text", "id": field["id"], "label": field["label"]}
                        for field in missing
                    ],
                )
            ],
        )

    return ConversationTurnPlan(
        action="ready",
        resolved_inputs=resolved,
        extracted_inputs=extracted,
        pending_inputs=missing,
        context_decision={"use_context": True, "reason": "ready"},
        activities=[
            make_activity(
                activity_id="understand:ready",
                kind="reasoning",
                status="completed",
                visibility="console",
                label="Conversation turn ready",
                summary="The turn can proceed to context planning.",
                data={"resolved_inputs": resolved, "missing_inputs": missing},
            )
        ],
    )


def extract_inputs_for_policy(message: str, policy: dict[str, Any]) -> dict[str, Any]:
    fields = [field for field in (policy.get("required_inputs") or []) if isinstance(field, dict)]
    if not fields:
        return {}
    text = message or ""
    extracted: dict[str, Any] = {}
    date_value = _extract_date(text)
    time_value = _extract_time(text)
    place_value = _extract_place(text, has_date=bool(date_value), has_time=bool(time_value))
    for field in fields:
        field_id = str(field.get("id") or "")
        field_type = str(field.get("type") or "").lower()
        if field_type == "date" or field_id in {"birth_date", "date", "dob"}:
            if date_value:
                extracted[field_id] = date_value
        elif field_type == "time" or field_id in {"birth_time", "time", "tob"}:
            if time_value:
                extracted[field_id] = time_value
        elif field_type == "place" or field_id in {"birth_place", "place", "city", "location"}:
            if place_value:
                extracted[field_id] = place_value
        elif field_type == "email":
            match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
            if match:
                extracted[field_id] = match.group(0)
        elif field_type == "phone":
            match = re.search(r"\+?\d[\d\s().-]{7,}\d", text)
            if match:
                extracted[field_id] = match.group(0).strip()
        else:
            value = _extract_labeled_value(text, field)
            if value:
                extracted[field_id] = value
    return extracted


def is_greeting(message: str) -> bool:
    text = _clean_message(message).strip(" .!?,")
    return text in GREETINGS


def message_has_question(message: str) -> bool:
    text = _clean_message(message)
    if "?" in message:
        return True
    if re.search(r"\b(question|query)\b\s*[-:=]", text):
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in QUESTION_TERMS)


def format_resolved_inputs(resolved: dict[str, Any], policy: dict[str, Any]) -> str:
    parts = []
    for field in policy.get("required_inputs") or []:
        if not isinstance(field, dict):
            continue
        field_id = field.get("id")
        value = resolved.get(field_id)
        if value in (None, ""):
            continue
        label = field.get("label") or str(field_id).replace("_", " ")
        parts.append(f"{label}: {value}")
    return ", ".join(parts) if parts else "the details you shared"


def format_missing_input_request(missing: list[dict[str, Any]], resolved: dict[str, Any], policy: dict[str, Any]) -> str:
    labels = [item.get("label") or str(item.get("id", "")).replace("_", " ") for item in missing]
    understood = format_resolved_inputs(resolved, policy)
    prefix = "" if understood == "the details you shared" else f"I have {understood}. "
    if len(labels) == 1:
        return f"{prefix}Please share your {labels[0]} so I can answer properly."
    return f"{prefix}Please share your {', '.join(labels[:-1])}, and {labels[-1]} so I can answer properly."


def _extract_date(text: str) -> str | None:
    patterns = [
        r"\b\d{4}-\d{1,2}-\d{1,2}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{1,2}\s*(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{4}\b",
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{1,2}\s+\d{4}\b",
    ]
    formats = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y")
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = match.group(0).replace(",", " ")
        raw = re.sub(
            r"^(\d{1,2})(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
            r"\1 \2",
            raw,
            flags=re.IGNORECASE,
        )
        for fmt in formats:
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def _extract_time(text: str) -> str | None:
    patterns = [
        r"\b(?:time\s*of\s*birth|birth\s*time|tob)\s*[:=]?\s*(\d{3,4})\b",
        r"\b(?:time\s*of\s*birth|birth\s*time|tob)\s*[:=]?\s*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)\b",
        r"\b(?:at)\s+(\d{3,4})\s*(?:hrs|hours?|IST|\(|india)?\b",
        r"\b(\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?)\b",
        r"\b(\d{1,2}\s*(?:am|pm))\b",
        r"\b(\d{3,4})\s*(?:IST|india(?:n)?\s+timezone)\b",
        r"\b(\d{3,4})\s*(?:hrs|hours?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).strip().lower().replace(".", "")
        if re.fullmatch(r"\d{3,4}", raw):
            raw = raw.zfill(4)
            return f"{raw[:2]}:{raw[2:]}:00"
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I %p"):
            try:
                return datetime.strptime(raw.upper(), fmt).strftime("%H:%M:%S")
            except ValueError:
                continue
    return None


def _extract_place(text: str, *, has_date: bool, has_time: bool) -> str | None:
    born_suffix = re.search(
        r"\b([A-Za-z][A-Za-z\s,.-]{1,80})\s+(?:born|birthplace)\b",
        text,
        re.IGNORECASE,
    )
    if born_suffix:
        place = _clean_place(born_suffix.group(1))
        if place:
            parts = [part.strip() for part in re.split(r"[.;\n]+", place) if part.strip()]
            return parts[-1] if parts else place
    labeled = re.search(
        r"\b(?:birth\s*place|birthplace|place\s*of\s*birth|pob|p\.?o\.?b\.?|born\s+in|place|city)\s*[:=]?\s*([A-Za-z][A-Za-z\s,.-]{1,120})",
        text,
        re.IGNORECASE,
    )
    if labeled:
        return _clean_place(labeled.group(1))
    if not (has_date and has_time):
        return None
    after_time = re.search(
        r"(?:\b\d{3,4}\s*(?:hrs|hours?|IST|india(?:n)?\s+timezone)?\b|\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b)\s*(?:[,.)-]|\btime\b)?\s*([A-Za-z][A-Za-z\s,.-]{1,120})",
        text,
        re.IGNORECASE,
    )
    if after_time:
        place = _clean_place(after_time.group(1))
        if place:
            return place
    # Infer unlabeled place after removing obvious date/time/name/question fragments.
    scrubbed = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ", text)
    scrubbed = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", scrubbed)
    scrubbed = re.sub(
        r"\b\d{1,2}\s*(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{4}\b",
        " ",
        scrubbed,
        flags=re.IGNORECASE,
    )
    scrubbed = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|\b\d{3,4}\s*(?:hrs|hours?|ist)?\b", " ", scrubbed, flags=re.IGNORECASE)
    scrubbed = re.sub(r"\b(?:name|dob|date|time|birth|of|place|question|query|ist|india timezone)\b\s*[:=-]?", " ", scrubbed, flags=re.IGNORECASE)
    parts = [
        _clean_place(part)
        for part in re.split(r"[.;\n]+", scrubbed)
        if _clean_place(part)
    ]
    if parts:
        # Names tend to be the first free-text fragment; birthplace is usually
        # the trailing location-like fragment once date/time have been removed.
        return parts[-1]
    return None


def _is_pending_field(pending_inputs: list[dict[str, Any]], field_id: str) -> bool:
    return any(isinstance(item, dict) and item.get("id") == field_id for item in pending_inputs)


def _extract_place_only_reply(text: str) -> str | None:
    cleaned = _clean_place(text or "")
    if not cleaned:
        return None
    if _extract_date(cleaned) or _extract_time(cleaned) or message_has_question(cleaned):
        return None
    if re.search(r"\d", cleaned):
        return None
    words = [word for word in re.split(r"[\s,]+", cleaned) if word]
    if not 1 <= len(words) <= 6:
        return None
    return cleaned


def _extract_labeled_value(text: str, field: dict[str, Any]) -> str | None:
    labels = [field.get("label"), field.get("id"), *((field.get("aliases") or []) if isinstance(field.get("aliases"), list) else [])]
    for label in labels:
        if not label:
            continue
        match = re.search(rf"\b{re.escape(str(label))}\b\s*[:=]\s*([^\n,;]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _clean_place(value: str) -> str:
    cleaned = re.split(
        r"(?:->|→|\|)|\b(?:question|query|ask|will|should|can|dob|tob|date\s+of\s+birth|time\s+of\s+birth|birth\s+time|place\s+of\s+birth)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.sub(r"^(?:hrs?|hours?|time|at)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:hrs?|hours?|time|ist|india timezone)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,-")


def _clean_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())
