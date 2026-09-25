"""LiveKit voice pipeline and LLM appointment tools."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, TurnHandlingOptions, cli
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, openai, silero

from .appointments import canonical_start
from .config import settings
from .confirmation import ConfirmationGate
from .telemetry import attach_telemetry
from .tool_client import AppointmentClient, ToolAPIError

class SupportAgent(Agent):
    def __init__(self, room, appointments):
        today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
        super().__init__(instructions=f"""You are VoiceDesk, a concise voice support assistant.
Today is {today}; the appointment timezone is {settings.timezone}.
Explain that you are an AI assistant. Use short spoken sentences, without markdown.
Appointments are 30-minute support calls, weekdays 9 AM to 5 PM, within 14 days.
Always check real availability using check_availability; never invent a slot.
Resolve relative dates to YYYY-MM-DD and clearly state the timezone.
Ask for the caller's name and preferred slot. Use prepare_booking to stage details.
Read the prepared name, local date, time, timezone, and duration aloud, then ask
'Would you like to confirm? Say yes or confirm booking.' Stop and wait for a new turn.
Only call confirm_booking after that new, explicit affirmative user turn.
The application enforces this rule independently of your tool arguments.
Never say booked until confirm_booking returns status booked with a confirmation ID.
If a slot conflicts, offer to check availability again. If the service is unavailable,
explain the problem; do not invent success. Availability is not a reservation.
Barge-in stops your speech; it does not undo a confirmed booking.
You cannot cancel existing appointments, send messages, or access external calendars.
Never request payment details, passwords, or unrelated private information.
""")
        self.appointments = appointments
        self.gate = ConfirmationGate(room)

    async def on_enter(self):
        await self.session.say(
            "Hi, I'm VoiceDesk, an AI assistant. I can check support appointment times and help you book one.",
            allow_interruptions=True,
        )

    async def on_user_turn_completed(self, turn_ctx, new_message):
        # Only a final user turn can approve a draft. The LLM cannot set this flag.
        self.gate.observe_user_turn(new_message.text_content or "")

    @function_tool
    async def check_availability(self, day: str) -> str:
        """List available support appointments for a local date.

        Args:
            day: Local date in YYYY-MM-DD format, within the next 14 days.
        """
        try:
            return json.dumps(await self.appointments.availability(day))
        except ToolAPIError as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @function_tool
    async def prepare_booking(self, starts_at: str, customer_name: str) -> str:
        """Prepare a slot; read its details and wait for the caller's confirmation.

        Args:
            starts_at: Exact offset-aware starts_at value from check_availability.
            customer_name: Name explicitly provided by the caller.
        """
        turn = self.gate.turn
        try:
            start = canonical_start(starts_at)
            local = datetime.fromisoformat(start).astimezone(ZoneInfo(settings.timezone))
            available = await self.appointments.availability(local.date().isoformat())
            if turn != self.gate.turn:
                return json.dumps({"status": "superseded", "message": "Ask the caller for their current preference"})
            if start not in {slot["starts_at"] for slot in available["slots"]}:
                return json.dumps({"status": "unavailable", "message": "Check availability again"})
            draft = self.gate.prepare(start, customer_name)
            return json.dumps({"status": "awaiting_confirmation", "name": draft.customer_name,
                               "local_start": local.isoformat(), "timezone": settings.timezone,
                               "duration_minutes": 30, "instruction": "Read these details and wait for an explicit yes"})
        except (ValueError, ToolAPIError) as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @function_tool
    async def confirm_booking(self) -> str:
        """Book the prepared appointment after a subsequent explicit affirmative user turn."""
        try:
            payload = self.gate.approved_booking()
            draft = self.gate.pending
            result = await self.appointments.book(payload)
            if self.gate.pending is draft:
                self.gate.finish()
            return json.dumps({"status": "booked", "confirmation_id": result["id"],
                               "starts_at": result["starts_at"], "timezone": settings.timezone,
                               "replayed": result["replayed"]})
        except (ValueError, ToolAPIError) as exc:
            return json.dumps({"status": "error", "message": str(exc)})


server = AgentServer()


def prewarm(process):
    process.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="voicedesk")
async def entrypoint(ctx: JobContext):
    settings.require_access_token()
    appointments = AppointmentClient(settings.api_url, settings.access_token)
    ctx.add_shutdown_callback(appointments.close)
    session = AgentSession(
        stt=deepgram.STT(model=settings.stt_model, language="en-US", interim_results=True),
        llm=openai.LLM(model=settings.llm_model),
        tts=deepgram.TTS(model=settings.tts_model),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            turn_detection="vad",
            endpointing={"min_delay": 0.25, "max_delay": 1.0},
            interruption={"enabled": True, "mode": "vad", "min_duration": 0.2,
                          "min_words": 0, "resume_false_interruption": False},
            preemptive_generation={"enabled": False},
        ),
        max_tool_steps=4,
    )
    attach_telemetry(session)
    await session.start(room=ctx.room, agent=SupportAgent(ctx.room.name, appointments), record=False)


if __name__ == "__main__":
    cli.run_app(server)
