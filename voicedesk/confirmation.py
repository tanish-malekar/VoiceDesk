"""A deterministic gate between LLM preparation and appointment mutation."""
import hashlib
import re
import time
from dataclasses import dataclass
from .appointments import canonical_start

AFFIRMATIONS = {"yes", "yes please", "confirm", "confirm booking", "book it", "yes book it", "that works"}
DECLINES = {"no", "no thanks", "cancel", "cancel booking", "stop"}


@dataclass
class Draft:
    starts_at: str
    customer_name: str
    created_turn: int
    expires_at: float
    approved: bool = False


class ConfirmationGate:
    def __init__(self, room, clock=time.monotonic):
        self.room = room
        self.clock = clock
        self.turn = 0
        self.pending = None

    def observe_user_turn(self, transcript):
        self.turn += 1
        normalized = re.sub(r"[^a-z ]", "", transcript.lower()).strip()
        normalized = " ".join(normalized.split())
        if not self.pending:
            return
        if self.clock() >= self.pending.expires_at or normalized in DECLINES:
            self.pending = None
            return
        self.pending.approved = (self.turn > self.pending.created_turn and normalized in AFFIRMATIONS)

    def prepare(self, starts_at, customer_name):
        name = customer_name.strip()
        if not name or len(name) > 120:
            raise ValueError("Provide a customer name up to 120 characters")
        self.pending = Draft(canonical_start(starts_at), name, self.turn, self.clock() + 300)
        return self.pending

    def approved_booking(self):
        draft = self.pending
        if not draft or self.clock() >= draft.expires_at or not draft.approved:
            raise ValueError("Read the prepared details and ask the caller to say yes or confirm booking")
        raw = f"{self.room}\0{draft.starts_at}\0{draft.customer_name}".encode()
        return {"room": self.room, "request_key": hashlib.sha256(raw).hexdigest(),
                "starts_at": draft.starts_at, "customer_name": draft.customer_name}

    def finish(self):
        self.pending = None
