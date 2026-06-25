from __future__ import annotations

from app.services.conversation_policy import (
    normalize_conversation_policy,
    plan_conversation_turn,
)


def astrology_policy():
    return normalize_conversation_policy({"domain": {"template": "astrology_lalkitab"}})


def test_greeting_does_not_require_context():
    plan = plan_conversation_turn(message="hi", policy=astrology_policy(), previous_state={})

    assert plan.action == "greeting"
    assert plan.should_short_circuit is True
    assert plan.context_decision["use_context"] is False


def test_unlabeled_birth_details_only_asks_for_question():
    plan = plan_conversation_turn(
        message="Anant, 16 July 1987, 1526 IST, Delhi India",
        policy=astrology_policy(),
        previous_state={},
    )

    assert plan.action == "ask_question"
    assert plan.resolved_inputs["birth_date"] == "1987-07-16"
    assert plan.resolved_inputs["birth_time"] == "15:26:00"
    assert "Delhi" in plan.resolved_inputs["birth_place"]
    assert "What would you like to ask" in plan.response_text


def test_compact_lowercase_birth_details_only_asks_for_question():
    plan = plan_conversation_turn(
        message="anant mendiratta. 16july 1987. 1526 hrs time. delhi.",
        policy=astrology_policy(),
        previous_state={},
    )

    assert plan.action == "ask_question"
    assert plan.resolved_inputs["birth_date"] == "1987-07-16"
    assert plan.resolved_inputs["birth_time"] == "15:26:00"
    assert plan.resolved_inputs["birth_place"].lower() == "delhi"
    assert plan.context_decision["use_context"] is False


def test_place_before_time_with_born_suffix_is_extracted():
    plan = plan_conversation_turn(
        message="anant mendiratta 16 july 1987. delhi born. 1526 hrs.",
        policy=astrology_policy(),
        previous_state={},
    )

    assert plan.action == "ask_question"
    assert plan.resolved_inputs["birth_date"] == "1987-07-16"
    assert plan.resolved_inputs["birth_time"] == "15:26:00"
    assert plan.resolved_inputs["birth_place"].lower() == "delhi"


def test_pending_birth_place_accepts_place_only_followup():
    policy = astrology_policy()
    plan = plan_conversation_turn(
        message="delhi, india.",
        policy=policy,
        previous_state={
            "resolved_inputs": {
                "birth_date": "1987-07-16",
                "birth_time": "15:26:00",
            },
            "pending_inputs": [{"id": "birth_place", "label": "birth place", "type": "place"}],
        },
    )

    assert plan.action == "ask_question"
    assert plan.resolved_inputs["birth_place"].lower() == "delhi, india"


def test_question_without_required_inputs_asks_for_missing_fields():
    plan = plan_conversation_turn(
        message="Will I build a profitable company before 40?",
        policy=astrology_policy(),
        previous_state={},
    )

    assert plan.action == "ask_missing_input"
    assert [item["id"] for item in plan.pending_inputs] == ["birth_date", "birth_time", "birth_place"]
    assert "birth date" in plan.response_text
    assert plan.context_decision["use_context"] is False


def test_complete_question_is_ready_for_context_planning():
    plan = plan_conversation_turn(
        message="Name Anant, 16 July 1987, 1526 IST, Delhi India. Will I build a profitable company before 40?",
        policy=astrology_policy(),
        previous_state={},
    )

    assert plan.action == "ready"
    assert plan.resolved_inputs["birth_date"] == "1987-07-16"
    assert plan.resolved_inputs["birth_time"] == "15:26:00"
    assert "Delhi" in plan.resolved_inputs["birth_place"]
    assert plan.context_decision["use_context"] is True


def test_old_generic_agents_have_no_required_input_gate():
    policy = normalize_conversation_policy({"domain": {"template": "generic"}})
    plan = plan_conversation_turn(message="Can you explain this?", policy=policy, previous_state={})

    assert plan.action == "ready"
    assert plan.pending_inputs == []
