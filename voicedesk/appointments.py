"""Single-calendar, fixed-duration appointments with atomic slot reservation."""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
DURATION = timedelta(minutes=30)


class BookingConflict(ValueError):
    pass


def canonical_start(value):
    start = datetime.fromisoformat(value)
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("Appointment time must include a UTC offset")
    return start.astimezone(UTC).isoformat()


class AppointmentStore:
    def __init__(self, path, timezone_name, clock=None):
        self.path = path
        self.zone = ZoneInfo(timezone_name)
        self.clock = clock or (lambda: datetime.now(UTC))

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY, room TEXT NOT NULL, request_key TEXT NOT NULL,
                starts_at TEXT NOT NULL UNIQUE, ends_at TEXT NOT NULL,
                customer_name TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(room, request_key)
            )""")

    def validate_date(self, day):
        today = self.clock().astimezone(self.zone).date()
        if day < today or day > today + timedelta(days=14):
            raise ValueError("Choose a date within the next 14 days")

    def slots(self, day):
        self.validate_date(day)
        if day.weekday() >= 5:
            return []
        now = self.clock()
        start = datetime.combine(day, time(9), tzinfo=self.zone)
        end = datetime.combine(day, time(17), tzinfo=self.zone)
        slots = []
        while start + DURATION <= end:
            if start > now:
                slots.append(start.astimezone(UTC).isoformat())
            start += DURATION
        return slots

    def availability(self, day):
        candidates = self.slots(day)
        with self.connection() as db:
            occupied = {row[0] for row in db.execute("SELECT starts_at FROM appointments")}
        return [{"starts_at": value,
                 "local_start": datetime.fromisoformat(value).astimezone(self.zone).isoformat(),
                 "duration_minutes": 30} for value in candidates if value not in occupied]

    def book(self, room, request_key, starts_at, customer_name):
        start = canonical_start(starts_at)
        name = customer_name.strip()
        if not name:
            raise ValueError("Customer name is required")
        # Serialize the idempotency lookup and slot reservation in one transaction.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM appointments WHERE room=? AND request_key=?",
                                  (room, request_key)).fetchone()
            if existing:
                if existing["starts_at"] != start or existing["customer_name"] != name:
                    raise BookingConflict("Idempotency key was already used for different details")
                return {**dict(existing), "replayed": True}
            instant = datetime.fromisoformat(start)
            local_day = instant.astimezone(self.zone).date()
            if start not in self.slots(local_day):
                raise ValueError("Appointment is outside available business hours or is in the past")
            try:
                db.execute("INSERT INTO appointments VALUES(?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex, room, request_key, start,
                            (instant + DURATION).isoformat(), name, self.clock().isoformat()))
            except sqlite3.IntegrityError:
                raise BookingConflict("That slot was just booked; check availability again") from None
            record = db.execute("SELECT * FROM appointments WHERE room=? AND request_key=?",
                                (room, request_key)).fetchone()
            return {**dict(record), "replayed": False}
