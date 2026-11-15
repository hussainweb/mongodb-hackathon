"""ElevenLabs TTS voice briefing and Scribe v2 STT approval helpers."""

from __future__ import annotations

import io
import random
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
_STAR_TREK_EXPLICIT_AUTH_RE = re.compile(
    r"\bauthorization\b(?:\s+[a-z0-9-]+){2,}",
    re.IGNORECASE,
)
_STAR_TREK_NAME_RE = re.compile(
    r"\b(?:picard|kirk|janeway|sisko|riker|spock|vulcan|vulkan|data|worf|uhura|"
    r"laforge|crusher|troi|pike|burnham|sulu|chekov|scotty|mccoy|tuvok|dax|"
    r"enterprise|defiant|voyager)\b",
    re.IGNORECASE,
)
_STAR_TREK_CALLSIGN_RE = re.compile(
    r"\b(?:alpha|beta|gamma|delta|epsilon|theta|omega|sigma|zeta|tango|foxtrot|"
    r"\d+|one|two|three|four|five|six|seven|eight|nine|zero)\b",
    re.IGNORECASE,
)

_ST_CAPTAINS = ("Picard", "Janeway", "Sisko", "Kirk", "Pike", "Riker")
_ST_GREEK_PRIMARY = ("Alpha", "Beta", "Gamma", "Delta", "Omega", "Theta")
_ST_GREEK_SECONDARY = ("Gamma", "Epsilon", "Sigma", "Zeta", "Tango")
_ST_OFFICERS = (
    "Vulcan Spock",
    "Vulcan Tuvok",
    "Android Data",
    "Klingon Worf",
    "Betazoid Troi",
    "Trill Dax",
)


def is_star_trek_auth_code(text: str) -> bool:
    """Return True if text looks like a Star Trek-style authorization code."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if _STAR_TREK_EXPLICIT_AUTH_RE.search(cleaned):
        return True
    return bool(_STAR_TREK_NAME_RE.search(cleaned) and _STAR_TREK_CALLSIGN_RE.search(cleaned))


def generate_star_trek_auth_code() -> str:
    """Generate a whimsical Star Trek-style authorization code."""
    captain = random.choice(_ST_CAPTAINS)
    greek1 = random.choice(_ST_GREEK_PRIMARY)
    digit = random.randint(1, 9)
    greek2 = random.choice(_ST_GREEK_SECONDARY)
    officer = random.choice(_ST_OFFICERS)
    return f"Authorization {captain} {greek1} {digit} {greek2} {officer}"


def ensure_star_trek_auth_code(text: str) -> str:
    """Return the operator's Star Trek code if present, otherwise generate one."""
    cleaned = (text or "").strip()
    if is_star_trek_auth_code(cleaned):
        return cleaned
    return generate_star_trek_auth_code()


def classify_voice_decision(transcript: str) -> tuple[VoiceDecision, str]:
    """Classify an operator's spoken transcript as approved, rejected, or not_detected."""
    text = (transcript or "").strip()
    if not text:
        return (
            "not_detected",
            "Approval not detected — say 'approve' or your authorization code to continue, or 'cancel' to halt.",
        )
    if _NEGATED_APPROVAL_RE.search(text) or _REJECTION_RE.search(text):
        return ("rejected", "Rejection detected — halting run.")
    if is_star_trek_auth_code(text):
        return ("approved", f"Authorization code accepted ({text}) — continuing run.")
    if _APPROVAL_RE.search(text):
        code = generate_star_trek_auth_code()
        return ("approved", f"Approval detected ({code}) — continuing run.")
    return (
        "not_detected",
        "Approval not detected — say 'approve' or your authorization code to continue, or 'cancel' to halt.",
    )
