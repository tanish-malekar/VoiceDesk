from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import pytest
from voicedesk.appointments import AppointmentStore, BookingConflict, canonical_start

START = "2026-11-03T09:00:00-05:00"


@pytest.fixture
def store(tmp_path):
    result = AppointmentStore(tmp_path / "appointments.sqlite3", "America/New_York",
                              clock=lambda: datetime(2026, 11, 2, 13, tzinfo=timezone.utc))
    result.initialize()
    return result


def test_equivalent_offsets_share_one_slot():
    assert canonical_start(START) == canonical_start("2026-11-03T14:00:00+00:00")
    with pytest.raises(ValueError):
        canonical_start("2026-11-03T09:00:00")


def test_idempotent_retry_returns_original_confirmation(store):
    first = store.book("room", "stable-key", START, "Alex")
    replay = store.book("room", "stable-key", START, "Alex")
    assert first["id"] == replay["id"] and replay["replayed"]
    with pytest.raises(BookingConflict):
        store.book("room", "stable-key", START, "Jordan")


def test_concurrent_callers_cannot_reserve_the_same_slot(store):
    def attempt(room):
        try:
            store.book(room, room + "-key", START, "Alex")
            return True
        except BookingConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sum(executor.map(attempt, ["one", "two"])) == 1


def test_booking_removes_slot_from_availability(store):
    canonical = canonical_start(START)
    assert canonical in {s["starts_at"] for s in store.availability(date(2026, 11, 3))}
    store.book("room", "stable-key", START, "Alex")
    assert canonical not in {s["starts_at"] for s in store.availability(date(2026, 11, 3))}


def test_weekends_and_off_grid_times_are_unavailable(store):
    assert store.availability(date(2026, 11, 7)) == []
    with pytest.raises(ValueError):
        store.book("room", "key", "2026-11-03T09:15:00-05:00", "Alex")
