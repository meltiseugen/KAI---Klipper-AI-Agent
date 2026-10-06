from klipperai_agent.application.intent import (
    ChatIntentOutput,
    classify_deterministic_intent,
    route_for_intent,
)


def test_intent_normalization_and_remaining_deterministic_routes() -> None:
    assert ChatIntentOutput(intent="debug", rationale=None).rationale == ""

    explained = classify_deterministic_intent("Explain what [fan] does")
    assert explained.intent == "config_explain"
    assert route_for_intent(explained) == "config"

    edited = classify_deterministic_intent("Change [fan] to use PA2")
    assert edited.intent == "edit_existing_config"
    assert route_for_intent(edited) == "config"
