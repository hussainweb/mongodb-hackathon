"""ElevenLabs TTS voice briefing and Scribe v2 STT approval helpers."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Literal

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
            model_id=cfg.elevenlabs_tts_model,
            output_format=cfg.elevenlabs_output_format,
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
    result = client.speech_to_text.convert(
        file=buf,
        model_id=cfg.elevenlabs_stt_model,
    )
    return str(getattr(result, "text", "") or "").strip()


VoiceDecision = Literal["approved", "rejected", "not_detected"]

_NEGATED_APPROVAL_RE = re.compile(
    r"\b(?:do\s+not|don't|dont|not|never|no)\s+"
    r"(?:approve|approved|proceed|continue|confirm|go\s+ahead|ship\s+it|do\s+it)\b",
    re.IGNORECASE,
)
_REJECTION_RE = re.compile(
    r"\b(?:abort|halt|rollback|roll\s+back|cancel|stop|reject|rejected|deny|denied|"
    r"decline|declined|disapprove|disapproved|no|nope|negative)\b",
    re.IGNORECASE,
)
_APPROVAL_RE = re.compile(
    r"\b(?:approve|approved|yes|yeah|yep|proceed|continue|confirm|confirmed|"
    r"go\s+ahead|looks\s+good|lgtm|ship\s+it|green|okay|ok|do\s+it|affirmative)\b",
    re.IGNORECASE,
)


def classify_voice_decision(transcript: str) -> tuple[VoiceDecision, str]:
    """Classify an operator's spoken transcript as approved, rejected, or not_detected."""
    text = (transcript or "").strip()
    if not text:
        return (
            "not_detected",
            "Approval not detected — say 'approve' to continue or 'cancel' to halt.",
        )
    if _NEGATED_APPROVAL_RE.search(text) or _REJECTION_RE.search(text):
        return ("rejected", "Rejection detected — halting run.")
    if _APPROVAL_RE.search(text):
        return ("approved", "Approval detected — continuing run.")
    return (
        "not_detected",
        "Approval not detected — say 'approve' to continue or 'cancel' to halt.",
    )
