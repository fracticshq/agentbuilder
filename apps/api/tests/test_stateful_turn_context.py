from types import SimpleNamespace

from app.services.stateful_turn_context import build_stateful_turn_context


def test_build_stateful_turn_context_preserves_history_and_restores_full_state():
    old_metadata = {
        "cart_id": "cart-old",
        "checkout_url": "https://checkout.example/old",
        "cart_lines": [{"id": "line-old"}],
        "captured_ids": {"speaker": "variant-old"},
        "last_searched": {"speaker": "variant-old"},
        "active_product_focus": [{"id": "product-old"}],
        "product_reference_map": {"1": {"id": "product-old"}},
        "last_user_query": "show speakers",
        "last_search_query": "speakers",
        "last_constraints": {"budget": 1000},
        "rerank_results": [{"id": "product-old", "rank": 1}],
        "connector_inputs": {"birth_place": "Delhi", "account_id": "old-account"},
    }
    latest_metadata = {
        "cart_id": "cart-new",
        "captured_ids": {"speaker": "variant-new"},
        "product_reference_map": {"1": {"id": "product-new"}},
        "last_search_query": "wireless speakers",
        "last_constraints": {"budget": 2000},
        "connector_inputs": {"account_id": "new-account", "birth_time": "10:30"},
    }
    messages = [
        SimpleNamespace(
            role="user",
            content="Do not trust this state",
            metadata={"cart_id": "user-controlled", "connector_inputs": {"account_id": "user"}},
        ),
        SimpleNamespace(role="assistant", content="Earlier answer", metadata=old_metadata),
        SimpleNamespace(role="assistant", content="Latest answer", metadata=latest_metadata),
    ]
    memory = {"summaries": ["semantic memory"]}

    turn_context = build_stateful_turn_context(
        conversation_summary="Earlier conversation summary.",
        recent_messages=messages,
        prompt_runtime={"locale": "en-IN"},
        prompt_metadata={"prompt_version": "v1"},
        capability_scope={"action": "allow"},
        commerce={"default_currency": "INR"},
        memory=memory,
    )

    assert turn_context.chat_history == [
        {
            "role": "system",
            "content": "Conversation memory so far (earlier turns):\nEarlier conversation summary.",
            "metadata": {"memory_summary": True},
        },
        {"role": "user", "content": "Do not trust this state", "metadata": messages[0].metadata},
        {"role": "assistant", "content": "Earlier answer", "metadata": old_metadata},
        {"role": "assistant", "content": "Latest answer", "metadata": latest_metadata},
    ]
    assert turn_context.session_state == {
        "cart_id": "cart-new",
        "checkout_url": "https://checkout.example/old",
        "cart_lines": [{"id": "line-old"}],
        "captured_ids": {"speaker": "variant-new"},
        "last_searched": {"speaker": "variant-old"},
        "active_product_focus": [{"id": "product-old"}],
        "product_reference_map": {"1": {"id": "product-new"}},
        "last_user_query": "show speakers",
        "last_search_query": "wireless speakers",
        "last_constraints": {"budget": 2000},
        "rerank_results": [{"id": "product-old", "rank": 1}],
        "connector_inputs": {
            "birth_place": "Delhi",
            "account_id": "new-account",
            "birth_time": "10:30",
        },
    }
    assert turn_context.context == {
        "session_state": turn_context.session_state,
        "prompt_runtime": {"locale": "en-IN"},
        "prompt_metadata": {"prompt_version": "v1"},
        "capability_scope": {"action": "allow"},
        "commerce": {"default_currency": "INR"},
        "memory": memory,
    }


def test_build_stateful_turn_context_omits_optional_memory_and_commerce():
    turn_context = build_stateful_turn_context(
        conversation_summary="",
        recent_messages=[],
        prompt_runtime={},
        prompt_metadata={},
        capability_scope=None,
    )

    assert turn_context.chat_history == []
    assert turn_context.session_state == {}
    assert turn_context.context == {
        "session_state": {},
        "prompt_runtime": {},
        "prompt_metadata": {},
        "capability_scope": None,
    }
