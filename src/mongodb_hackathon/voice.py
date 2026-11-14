"""ElevenLabs TTS voice briefing and Scribe v2 STT approval helpers."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
from elevenlabs import ElevenLabs
from elevenlabs.core.api_error import ApiError

from mongodb_hackathon.config import Settings, get_settings


def synthesize_briefing(
    run_id: str,
    text: str,
    output_dir: Path,
    settings: Settings | None = None,
) -> str:
    """Generate an MP3 voice escalation via ElevenLabs; return filename or '' if unavailable."""
    cfg = settings or get_settings()
    if not cfg.elevenlabs_api_key:
        return ""

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"briefing-{run_id}.mp3"
    dest = output_dir / filename
    try:
        client = ElevenLabs(api_key=cfg.elevenlabs_api_key)
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=cfg.elevenlabs_voice_id,
            model_id="eleven_flash_v2_5",
        )
        with dest.open("wb") as handle:
            for chunk in audio:
                handle.write(chunk)
        return filename
    except ApiError, httpx.HTTPError, OSError, RuntimeError, ValueError:
        return ""


def transcribe_operator_audio(
    audio_bytes: bytes,
    filename: str = "approval.webm",
    settings: Settings | None = None,
) -> str:
    """Transcribe spoken operator approval/command via ElevenLabs Scribe v2."""
    cfg = settings or get_settings()
    if not cfg.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    client = ElevenLabs(api_key=cfg.elevenlabs_api_key)
    buf = io.BytesIO(audio_bytes)
    buf.name = filename
    result = client.speech_to_text.convert(file=buf, model_id="scribe_v2")
    return str(getattr(result, "text", "") or "").strip()
