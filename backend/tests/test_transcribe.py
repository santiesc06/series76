"""Voice messages (US-22): `POST /api/transcribe`. No Whisper model is loaded here: the API tests
use a fake transcriber, and the limit tests stop before the model (real audio decoding only)."""

import io
import logging
import math
import struct
import wave

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.voice.transcriber import (
    MAX_BYTES,
    Transcript,
    WhisperTranscriber,
    get_transcriber,
    no_speech,
)


def wav(seconds: float, tone: bool = True) -> bytes:
    """A mono 16 kHz WAV: a quiet 440 Hz tone, or silence."""
    frames = int(16_000 * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16_000)
        samples = (
            int(3000 * math.sin(2 * math.pi * 440 * i / 16_000)) if tone else 0
            for i in range(frames)
        )
        out.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return buffer.getvalue()


class FakeTranscriber:
    def __init__(self, text="What is the torque of 763B00-11300000/A?", error=None):
        self.text, self.error, self.received = text, error, []

    def transcribe(self, audio: bytes) -> Transcript:
        self.received.append(audio)
        if self.error:
            raise self.error
        return Transcript(text=self.text, language="en", duration_s=2.0)


@pytest.fixture
def voice(db, make_user):
    app.dependency_overrides[get_db] = lambda: db
    _, token = make_user()
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def post(data: bytes, transcriber=None, filename="question.m4a", headers=None):
        fake = transcriber or FakeTranscriber()
        app.dependency_overrides[get_transcriber] = lambda: fake
        post.fake = fake
        files = {"audio": (filename, data, "audio/mp4")}
        return client.post("/api/transcribe", files=files, headers=headers or {})

    yield post
    app.dependency_overrides.clear()


def test_returns_the_transcript(voice, caplog):  # US-22 AC2
    caplog.set_level(logging.INFO, logger="voice")
    r = voice(b"fake-audio-bytes")
    assert r.status_code == 200
    assert r.json() == {
        "text": "What is the torque of 763B00-11300000/A?",
        "language": "en",
        "duration_s": 2.0,
    }
    assert voice.fake.received == [b"fake-audio-bytes"]
    # The user's words are not logged (like chat queries).
    assert "763B00" not in caplog.text and "torque" not in caplog.text


def test_needs_a_token(db):  # US-21 AC4 applies to voice too
    app.dependency_overrides[get_db] = lambda: db
    try:
        r = TestClient(app).post("/api/transcribe", files={"audio": ("a.m4a", b"x")})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 401


def test_empty_upload_is_rejected(voice):  # US-22 AC4
    r = voice(b"")
    assert r.status_code == 400 and r.json()["error"]["code"] == "audio_empty"
    assert voice.fake.received == []  # never reached the model


def test_upload_over_5_mb_is_rejected(voice):  # US-22 AC4, design V5
    r = voice(b"\0" * (MAX_BYTES + 1))
    assert r.status_code == 413 and r.json()["error"]["code"] == "audio_too_large"
    assert voice.fake.received == []


def test_silence_gives_no_speech(voice):  # US-22 AC4
    r = voice(b"silence", FakeTranscriber(error=no_speech()))
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_speech"


def test_unreadable_audio_is_rejected_before_the_model():  # US-22 AC4
    transcriber = WhisperTranscriber("small")
    with pytest.raises(Exception) as caught:
        transcriber.transcribe(b"this is not audio")
    assert caught.value.code == "audio_invalid"
    assert transcriber._model is None  # nothing loaded or downloaded


def test_recording_over_60_seconds_is_rejected_before_the_model():  # US-22 AC4, V5
    transcriber = WhisperTranscriber("small")
    with pytest.raises(Exception) as caught:
        transcriber.transcribe(wav(62, tone=False))
    assert caught.value.code == "audio_too_large"
    assert transcriber._model is None


def test_errors_use_the_standard_format_without_internals(voice):  # C4, US-18 AC2
    body = voice(b"").json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    assert "whisper" not in body["error"]["message"].lower()
