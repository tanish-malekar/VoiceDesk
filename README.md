# VoiceDesk

A real-time voice support agent built with **Python, asyncio, LiveKit, WebRTC,
Deepgram, and FastAPI**. Callers speak through a browser, ask about available
support appointments, review the details, and confirm a booking by voice.
The agent's speech is interruptible, so callers can correct or redirect it
without waiting for a response to finish.

## Architecture

```text
Browser microphone
    -> LiveKit WebRTC room
    -> Deepgram streaming speech-to-text + Silero voice activity detection
    -> LLM conversation and function tools
         check_availability -> FastAPI -> SQLite
         prepare_booking    -> session-local confirmation gate
         confirm_booking    -> FastAPI -> atomic appointment reservation
    -> Deepgram text-to-speech
    -> LiveKit WebRTC audio -> browser speaker
```

The FastAPI service issues short-lived room tokens and provides appointment
endpoints. A separate LiveKit agent worker handles streaming speech, tool calls,
turn detection, and playback interruption. The browser client provides microphone
controls, an audio-permission button, connection state, and a live transcript.

## Features

- Streaming Deepgram transcription and speech output through LiveKit provider plugins.
- WebRTC media transport with browser echo cancellation and microphone controls.
- Voice activity detection that interrupts speech when the caller starts talking.
- LLM tools for live availability lookup, preparation, and confirmed booking.
- Application-enforced verbal confirmation after appointment details are prepared.
- Atomic slot reservation and idempotent retries in a local SQLite calendar.
- Offset-aware timestamps and business hours in a configurable appointment timezone.
- Content-free component timing logs and a server-side response timing proxy.

## Local setup

Use Python 3.11+ and a Node version matching `frontend/package.json`'s `engines`
field. You need a LiveKit project or self-hosted server, a Deepgram API key, and
an API key for the configured LLM provider.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Fill in `.env` with the LiveKit and provider credentials. Generate a workspace
access token and set `VOICEDESK_ACCESS_TOKEN` to that value:

```sh
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

The same workspace token is used by the API, agent worker, and browser caller.
The browser accepts it in a password field and keeps no token in local storage.
Provider keys and LiveKit signing secrets remain server-side.

Download the agent's model assets:

```sh
python -m voicedesk.agent download-files
```

Start each component in its own terminal from the repository root:

```sh
# Terminal 1: appointment and session API
source .venv/bin/activate
uvicorn voicedesk.api:app --host 127.0.0.1 --port 8000

# Terminal 2: LiveKit agent worker
source .venv/bin/activate
python -m voicedesk.agent dev

# Terminal 3: browser client
cd frontend
npm ci
npm run dev
```

Open [VoiceDesk](http://127.0.0.1:5173), enter the workspace token, and select
**Start conversation**. Grant microphone access and use **Enable sound** if the
browser requests a playback gesture. Headphones help prevent speaker audio from
feeding back into the microphone.

Each call receives a random room name and a room-scoped token with a ten-minute
join lifetime. The token requests dispatch to the worker named `voicedesk`.
The worker must be registered against the same LiveKit project. The token grants
microphone publication and subscriptions, with no room administration rights.

## Booking conversation

1. Ask for support availability on a date, such as “What times are open tomorrow?”
2. Choose a returned slot and provide your name.
3. The agent prepares the appointment and reads back the local date, time,
   timezone, name, and 30-minute duration.
4. After the confirmation question, say **yes**, **yes please**, or **confirm booking**.
5. The booking tool reserves the slot and returns a confirmation ID for the agent
   to announce. A conflict sends the conversation back to availability lookup.

A preparation call does not reserve a slot. A later, final user turn must contain
one of the confirmation gate's explicit affirmative phrases. Approval is derived
from the caller's transcript; the LLM cannot supply a `confirmed=true` argument.
New preparation replaces the draft, and drafts expire after five minutes.
An exact decline such as “no” or “cancel” clears a pending draft.

The API stores **local demo appointments**, not entries in a connected Google,
Microsoft, or other external calendar. There is one calendar, fixed 30-minute
slots, weekday hours from 9 AM to 5 PM, and a fourteen-day booking horizon.
Slot timestamps are stored in UTC and spoken in `VOICEDESK_TIMEZONE`.
SQLite holds the caller's provided name and booking details.

## Barge-in and asyncio

The session uses Silero VAD, a 200 ms minimum interruption duration, and immediate
word-count eligibility. LiveKit's session runtime interrupts active speech and
clears pending playback when the interruption is detected. Automatic resumption
of false interruptions is disabled, keeping an old response from restarting.
Preemptive generation is disabled to keep booking tools out of speculative turns.

Appointment calls use an asynchronous HTTP client with bounded connection pools
and a five-second operation deadline. Booking writes are shielded from speech-turn
cancellation. A unique `(room, request_key)` makes retrying a booking return the
original confirmation instead of reserving twice; a unique start timestamp prevents
two callers from taking the same slot. Both checks occur in one SQLite transaction.

Interrupting speech does not undo a booking already committed. If a call ends
before the confirmation is heard, a repeated request with the same details and
room can recover the same confirmation. Cancellation of existing appointments
is outside this project's tool set.

## Configuration

| Variable | Purpose |
| --- | --- |
| `LIVEKIT_URL` | LiveKit WebSocket URL |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Room token signing and worker credentials |
| `DEEPGRAM_API_KEY` | Direct Deepgram STT and TTS authentication |
| `OPENAI_API_KEY` | Authentication for the default LLM plugin |
| `LLM_MODEL` | LLM model, default `gpt-4.1-mini` |
| `DEEPGRAM_STT_MODEL` | Transcription model, default `nova-3` |
| `DEEPGRAM_TTS_MODEL` | Voice model, default `aura-2-andromeda-en` |
| `VOICEDESK_ACCESS_TOKEN` | Shared workspace secret, at least 32 characters |
| `VOICEDESK_API_URL` | Appointment API address used by the worker |
| `VOICEDESK_TIMEZONE` | Appointment timezone, default `America/New_York` |
| `VOICEDESK_DB` | SQLite path, default `data/voicedesk.sqlite3` |

`.env` loads in the Python processes and is excluded from Git. Keep the API and
agent timezone configuration aligned. The browser's Vite proxy sends `/api` to
`127.0.0.1:8000`; production hosting needs an equivalent reverse proxy.
Microphones require a secure browser context, with localhost supported for local
use. A shared workspace token is intended for trusted local callers; an internet
service should use per-user authentication, room authorization, rate limits, and TLS.

## API

Authenticated endpoints require `Authorization: Bearer <workspace-token>`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service settings and health |
| POST | `/api/sessions` | Create a room token and agent dispatch configuration |
| GET | `/api/availability?day=YYYY-MM-DD` | List available local-date slots |
| POST | `/api/bookings` | Reserve an appointment with a stable request key |

Interactive endpoint schemas are available at [API docs](http://127.0.0.1:8000/docs).
The API's booking endpoint is for trusted clients; the conversational confirmation
gate lives in the agent and is not a substitute for authorization at the API.

## Timing and observability

`voicedesk.telemetry` logs component timings emitted by the SDK and
`user_stop_to_agent_speaking_proxy_ms`, measured between the user's speaking-to-
listening state transition and the agent's next speaking transition.
This is a server state timing proxy, distinct from end-of-speech to audible sound
at the caller. Browser buffering, network transit, and playout affect the latter.

To assess end-to-end latency, capture the caller's audio timeline, identify the
last input speech sample and first audible response sample, and report the
percentile distribution across normal turns, tool calls, and interrupted turns.
Keep region, provider model, endpointing settings, and network conditions alongside
the measurements. Timing logs exclude transcripts, names, and token contents.
The browser transcript stays in page memory and can be cleared during a call.

## Development

```sh
python -m pytest
cd frontend && npm run build
```

The test specifications cover confirmation ordering, expiry, slot conflicts,
timezone normalization, and idempotency. The main modules are:

- `voicedesk/agent.py` — streaming session and LLM tools
- `voicedesk/confirmation.py` — deterministic verbal confirmation state
- `voicedesk/appointments.py` — scheduling rules and atomic persistence
- `voicedesk/tool_client.py` — asynchronous appointment API calls
- `voicedesk/api.py` — FastAPI endpoints and room token generation
- `voicedesk/telemetry.py` — state timing and component metrics
- `frontend/` — browser microphone, playback, controls, and transcript

Provider and framework references: [LiveKit Agents](https://docs.livekit.io/agents/),
[Deepgram STT integration](https://docs.livekit.io/agents/models/stt/deepgram/),
[Deepgram TTS integration](https://docs.livekit.io/agents/models/tts/deepgram/), and
[LiveKit text streams](https://docs.livekit.io/transport/data/text-streams/).

MIT licensed.
