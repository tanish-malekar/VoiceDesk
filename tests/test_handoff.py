import pytest
from voicedesk.handoff import HandoffStore


def test_queue_idempotency_and_claimed_identity(tmp_path):
    store = HandoffStore(tmp_path / "voice.sqlite3"); store.initialize()
    first = store.enqueue("caller-room", "booking_uncertain")
    assert store.enqueue("caller-room", "caller_requested")["id"] == first["id"]
    assert first["state"] == "queued"
    claim = store.claim(first["id"])
    assert not store.confirm_join("other-room", claim["operator_identity"])
    assert not store.confirm_join("caller-room", "invented-operator")
    assert store.confirm_join("caller-room", claim["operator_identity"])
    assert not store.pending()
    with pytest.raises(ValueError): store.claim(first["id"])


def test_claim_is_exclusive_and_unknown_reasons_fail(tmp_path):
    store = HandoffStore(tmp_path / "voice.sqlite3"); store.initialize()
    entry = store.enqueue("room", "availability_unavailable")
    store.claim(entry["id"])
    with pytest.raises(ValueError): store.claim(entry["id"])
    with pytest.raises(ValueError): store.enqueue("room2", "raw user transcript")
