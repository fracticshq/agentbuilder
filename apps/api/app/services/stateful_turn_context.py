"""Pure assembly of reusable state for a conversational agent turn."""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


_UNSET = object()

# These are written to assistant-message metadata after a turn and restored for
# the next one. Keep this list aligned with session fields consumed by the
# commerce and connector runtimes.
SESSION_STATE_FIELDS = (
    "cart_id",
    "checkout_url",
    "cart_lines",
    "captured_ids",
    "last_searched",
    "active_product_focus",
    "product_reference_map",
    "last_user_query",
    "last_search_query",
    "last_constraints",
    "rerank_results",
)


@dataclass
class StatefulTurnContext:
    """History and runtime context assembled without storage or service I/O."""

    chat_history: list[dict]
    session_state: dict
    context: dict


def _message_role(message: Any) -> str:
    role = getattr(message, "role", "")
    return role.value if hasattr(role, "value") else str(role)


def build_stateful_turn_context(
    *,
    conversation_summary: str | None,
    recent_messages: Iterable[Any] | None,
    prompt_runtime: Any,
    prompt_metadata: Any,
    capability_scope: Any,
    commerce: Any = _UNSET,
    memory: Any = _UNSET,
) -> StatefulTurnContext:
    """Build ordered history and restore state from assistant messages only.

    Scalar state uses the newest assistant value. Connector inputs accumulate
    across assistant turns so an input supplied earlier remains available until
    a later turn replaces that specific field.
    """
    chat_history: list[dict] = []
    session_state: dict = {}

    if conversation_summary:
        chat_history.append(
            {
                "role": "system",
                "content": f"Conversation memory so far (earlier turns):\n{conversation_summary}",
                "metadata": {"memory_summary": True},
            }
        )

    for message in recent_messages or []:
        role = _message_role(message)
        metadata = getattr(message, "metadata", None) or {}
        chat_history.append(
            {
                "role": role,
                "content": getattr(message, "content", None),
                "metadata": metadata,
            }
        )

        if role != "assistant" or not isinstance(metadata, Mapping):
            continue

        for field in SESSION_STATE_FIELDS:
            if field in metadata:
                session_state[field] = metadata.get(field)

        connector_inputs = metadata.get("connector_inputs")
        if isinstance(connector_inputs, Mapping):
            session_state["connector_inputs"] = {
                **session_state.get("connector_inputs", {}),
                **connector_inputs,
            }

    context = {
        "session_state": session_state,
        "prompt_runtime": prompt_runtime,
        "prompt_metadata": prompt_metadata,
        "capability_scope": capability_scope,
    }
    if commerce is not _UNSET:
        context["commerce"] = commerce
    if memory is not _UNSET:
        context["memory"] = memory

    return StatefulTurnContext(
        chat_history=chat_history,
        session_state=session_state,
        context=context,
    )
