import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database: Path = Path(os.getenv("VOICEDESK_DB", "data/voicedesk.sqlite3")).resolve()
    timezone: str = os.getenv("VOICEDESK_TIMEZONE", "America/New_York")
    access_token: str = os.getenv("VOICEDESK_ACCESS_TOKEN", "")
    livekit_url: str = os.getenv("LIVEKIT_URL", "")
    livekit_key: str = os.getenv("LIVEKIT_API_KEY", "")
    livekit_secret: str = os.getenv("LIVEKIT_API_SECRET", "")
    api_url: str = os.getenv("VOICEDESK_API_URL", "http://127.0.0.1:8000")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    stt_model: str = os.getenv("DEEPGRAM_STT_MODEL", "nova-3")
    tts_model: str = os.getenv("DEEPGRAM_TTS_MODEL", "aura-2-andromeda-en")

    def require_access_token(self):
        if len(self.access_token) < 32:
            raise ValueError("Set VOICEDESK_ACCESS_TOKEN to at least 32 characters")


settings = Settings()
