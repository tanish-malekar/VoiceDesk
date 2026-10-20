import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from livekit import api as livekit_api
from pydantic import BaseModel, Field

from .appointments import AppointmentStore, BookingConflict
from .config import settings
from .handoff import HandoffStore

store = AppointmentStore(settings.database, settings.timezone)
handoffs = HandoffStore(settings.database)
bearer = HTTPBearer(auto_error=False)


def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials or not secrets.compare_digest(credentials.credentials.encode(), settings.access_token.encode()):
        raise HTTPException(401, "A valid VoiceDesk access token is required")


@asynccontextmanager
async def lifespan(app):
    settings.require_access_token()
    store.initialize()
    handoffs.initialize()
    yield


app = FastAPI(title="VoiceDesk", version="0.1.0", lifespan=lifespan)


class BookingInput(BaseModel):
    room: str = Field(min_length=1, max_length=120)
    request_key: str = Field(min_length=16, max_length=128)
    starts_at: str = Field(min_length=1, max_length=64)
    customer_name: str = Field(min_length=1, max_length=120)


@app.get("/api/health")
def health():
    return {"status": "ok", "timezone": settings.timezone, "appointment_minutes": 30}


@app.post("/api/sessions", dependencies=[Depends(authorized)])
def create_session(response: Response):
    if not all((settings.livekit_url, settings.livekit_key, settings.livekit_secret)):
        raise HTTPException(503, "Configure LiveKit credentials on the server")
    room = "voicedesk-" + uuid.uuid4().hex
    identity = "caller-" + uuid.uuid4().hex
    token = (livekit_api.AccessToken(settings.livekit_key, settings.livekit_secret)
             .with_identity(identity).with_name("VoiceDesk caller")
             .with_ttl(timedelta(minutes=10))
             .with_grants(livekit_api.VideoGrants(room_join=True, room=room,
                          can_publish=True, can_subscribe=True, can_publish_data=False,
                          can_publish_sources=["microphone"]))
             .with_room_config(livekit_api.RoomConfiguration(
                 agents=[livekit_api.RoomAgentDispatch(agent_name="voicedesk")]))
             .to_jwt())
    response.headers["Cache-Control"] = "no-store"
    return {"url": settings.livekit_url, "token": token, "room": room, "identity": identity}


@app.get("/api/availability", dependencies=[Depends(authorized)])
def availability(day: date = Query()):
    try:
        return {"date": day.isoformat(), "timezone": settings.timezone, "slots": store.availability(day)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/api/bookings", dependencies=[Depends(authorized)])
def book(body: BookingInput):
    try:
        return store.book(body.room, body.request_key, body.starts_at, body.customer_name)
    except BookingConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


operator_bearer = HTTPBearer(auto_error=False)


def operator_authorized(credentials: HTTPAuthorizationCredentials | None = Depends(operator_bearer)):
    token = settings.operator_token
    if len(token) < 32 or not credentials or not secrets.compare_digest(
        credentials.credentials.encode(), token.encode()
    ):
        raise HTTPException(401, "A valid operator token is required")


@app.get("/api/handoffs", dependencies=[Depends(operator_authorized)])
def pending_handoffs(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"handoffs": handoffs.pending()}


@app.post("/api/handoffs/{handoff_id}/join", dependencies=[Depends(operator_authorized)])
def join_handoff(handoff_id: str, response: Response):
    if not all((settings.livekit_url, settings.livekit_key, settings.livekit_secret)):
        raise HTTPException(503, "Configure LiveKit credentials")
    try:
        record = handoffs.claim(handoff_id)
    except KeyError:
        raise HTTPException(404, "Unknown handoff") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    token = (livekit_api.AccessToken(settings.livekit_key, settings.livekit_secret)
             .with_identity(record["operator_identity"]).with_name("Human support")
             .with_ttl(timedelta(minutes=2))
             .with_grants(livekit_api.VideoGrants(room_join=True, room=record["room"],
                 can_publish=True, can_subscribe=True, can_publish_data=False,
                 can_publish_sources=["microphone"]))
             .to_jwt())
    response.headers["Cache-Control"] = "no-store"
    return {"url": settings.livekit_url, "token": token, "room": record["room"]}
