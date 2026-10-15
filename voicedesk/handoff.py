"""Durable room handoff queue shared by the API and agent worker."""
from contextlib import contextmanager
import sqlite3
import uuid
from datetime import datetime, timezone


class HandoffStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS handoffs (
                id TEXT PRIMARY KEY, room TEXT NOT NULL UNIQUE,
                reason TEXT NOT NULL, state TEXT NOT NULL,
                operator_identity TEXT, claimed_at TEXT, created_at TEXT NOT NULL
            )""")

    def enqueue(self, room, reason):
        if reason not in {"availability_unavailable", "booking_uncertain", "caller_requested"}:
            raise ValueError("Unknown handoff reason")
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO handoffs VALUES(?,?,?,'queued',NULL,NULL,?)",
                       (uuid.uuid4().hex, room, reason, datetime.now(timezone.utc).isoformat()))
            return dict(db.execute("SELECT * FROM handoffs WHERE room=?", (room,)).fetchone())

    def pending(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM handoffs WHERE state IN ('queued','claimed') ORDER BY created_at LIMIT 100")]

    def claim(self, key):
        now = datetime.now(timezone.utc)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM handoffs WHERE id=?", (key,)).fetchone()
            if not row:
                raise KeyError(key)
            if row["state"] == "connected" or (row["state"] == "claimed" and
                (now - datetime.fromisoformat(row["claimed_at"])).total_seconds() < 120):
                raise ValueError("Another operator holds this handoff")
            identity = "operator-" + uuid.uuid4().hex
            db.execute("UPDATE handoffs SET state='claimed',operator_identity=?,claimed_at=? WHERE id=?",
                       (identity, now.isoformat(), key))
            return {**dict(row), "operator_identity": identity, "state": "claimed"}

    def confirm_join(self, room, identity):
        with self.connect() as db:
            changed = db.execute("""UPDATE handoffs SET state='connected'
                WHERE room=? AND operator_identity=? AND state='claimed'""", (room, identity)).rowcount
            return changed == 1
