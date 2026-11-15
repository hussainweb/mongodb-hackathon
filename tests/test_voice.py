"""Unit tests ensuring voice helpers use low-cost ElevenLabs models and compressed output."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mongodb_hackathon import voice
from mongodb_hackathon.config import Settings


def test_default_elevenlabs_settings_use_low_cost_flash_model() -> None:
    """Default ElevenLabs config avoids expensive v4/highest-bitrate tiers for testing."""
    cfg = Settings()
    assert cfg.elevenlabs_tts_model == "eleven_flash_v2_5"
    assert cfg.elevenlabs_output_format == "mp3_22050_32"
    assert cfg.elevenlabs_stt_model == "scribe_v2"


def test_voice_helpers_pass_configured_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify TTS and STT pass configured low-cost model_id and output_format."""
    captured: dict[str, object] = {}

    class _FakeTTS:
        def convert(self, **kwargs: object) -> list[bytes]:
            captured["tts"] = kwargs
            return [b"ID3"]

    class _FakeSTT:
        def convert(self, **kwargs: object) -> SimpleNamespace:
            captured["stt"] = kwargs
            return SimpleNamespace(text="Approved")

    class _FakeClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key
            self.text_to_speech = _FakeTTS()
            self.speech_to_text = _FakeSTT()

    monkeypatch.setattr(voice, "ElevenLabs", _FakeClient)
    cfg = Settings()
    cfg.elevenlabs_api_key = "test-key"

    filename = voice.synthesize_briefing(
        "run1", "Confirm gate.", tmp_path, settings=cfg
    )
    assert filename == "briefing-run1.mp3"
    assert (tmp_path / filename).read_bytes() == b"ID3"
    assert captured["tts"] == {
        "text": "Confirm gate.",
        "voice_id": cfg.elevenlabs_voice_id,
        "model_id": "eleven_flash_v2_5",
        "output_format": "mp3_22050_32",
    }

    transcript = voice.transcribe_operator_audio(b"fake-audio", settings=cfg)
    assert transcript == "Approved"
    stt_call = captured["stt"]
    assert isinstance(stt_call, dict)
    assert stt_call["model_id"] == "scribe_v2"


@pytest.mark.parametrize(
    ("transcript", "expected_decision"),
    [
        ("I approve, go ahead", "approved"),
        ("Yes, proceed with deployment", "approved"),
        ("LGTM, ship it", "approved"),
        ("I do not approve", "rejected"),
        ("Don't approve this", "rejected"),
        ("No, cancel and rollback", "rejected"),
        ("Halt the deployment", "rejected"),
        ("Wait what did you say?", "not_detected"),
        ("", "not_detected"),
    ],
)
def test_classify_voice_decision(transcript: str, expected_decision: str) -> None:
    """Verify voice decision classifier distinguishes approvals, negations, and unclear speech."""
    decision, label = voice.classify_voice_decision(transcript)
    assert decision == expected_decision
    assert label
