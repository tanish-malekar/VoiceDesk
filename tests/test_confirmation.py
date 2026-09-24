import pytest
from voicedesk.confirmation import ConfirmationGate

START = "2026-11-03T09:00:00-05:00"


def test_preparation_requires_a_subsequent_affirmative_user_turn():
    gate = ConfirmationGate("room")
    gate.observe_user_turn("yes")
    gate.prepare(START, "Alex")
    with pytest.raises(ValueError):
        gate.approved_booking()
    gate.observe_user_turn("Yes, please!")
    assert gate.approved_booking()["customer_name"] == "Alex"


def test_qualified_yes_does_not_approve_or_mutate_details():
    gate = ConfirmationGate("room")
    gate.prepare(START, "Alex")
    gate.observe_user_turn("yes but choose a different time")
    with pytest.raises(ValueError):
        gate.approved_booking()


def test_preparing_different_details_discards_prior_approval():
    gate = ConfirmationGate("room")
    gate.prepare(START, "Alex")
    gate.observe_user_turn("confirm booking")
    previous_key = gate.approved_booking()["request_key"]
    gate.prepare(START, "Jordan")
    with pytest.raises(ValueError):
        gate.approved_booking()
    gate.observe_user_turn("yes")
    assert gate.approved_booking()["request_key"] != previous_key


def test_draft_expiry_and_decline_clear_approval():
    current = [0.0]
    gate = ConfirmationGate("room", clock=lambda: current[0])
    gate.prepare(START, "Alex")
    current[0] = 301.0
    gate.observe_user_turn("yes")
    assert gate.pending is None
    gate.prepare(START, "Alex")
    gate.observe_user_turn("cancel")
    assert gate.pending is None
