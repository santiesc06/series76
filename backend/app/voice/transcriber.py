"""Speech to text with faster-whisper (US-22, design O2, V2-V6).

The audio is decoded in memory and discarded after transcription; nothing is written to disk or
to the database (V5). The model is loaded once, on first use, and shared by all requests.
"""

import io
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.config import get_settings

log = logging.getLogger("voice")

SAMPLE_RATE = 16_000
MAX_SECONDS = 60  # V5
MAX_BYTES = 5 * 1024 * 1024  # V5

# V4: catalog vocabulary, so Whisper writes part numbers and units the way the catalog does.
VOCABULARY_HINT = (
    "Series 76 electric actuators. Part numbers like 763B00-11300000/A or 761A00-11320000/A. "
    "Torque in Nm and in-lbs, 110V, 220V, 24V AC, single phase, three phase, 50 Hz, 60 Hz, "
    "weatherproof, explosionproof, modulating, On/Off, duty cycle."
)


class VoiceError(Exception):
    """A problem with the recording that the user can fix; `code` is the API error code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def audio_empty() -> VoiceError:
    return VoiceError(400, "audio_empty", "The recording is empty.")


def audio_too_large() -> VoiceError:
    return VoiceError(
        413, "audio_too_large", f"Recordings can be up to {MAX_SECONDS} seconds long."
    )


def audio_invalid() -> VoiceError:
    return VoiceError(400, "audio_invalid", "The recording could not be read.")


def no_speech() -> VoiceError:
    return VoiceError(422, "no_speech", "No speech was recognized. Try again, closer to the mic.")


def unavailable() -> VoiceError:
    return VoiceError(503, "transcription_unavailable", "Voice transcription is not available.")


@dataclass
class Transcript:
    text: str
    language: str
    duration_s: float


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> Transcript: ...


class WhisperTranscriber:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()  # one transcription at a time; CPU-bound anyway

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # heavy import, only when voice is used

            try:
                # int8 on CPU (V2). In Docker the weights are already in the image (V3).
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            except Exception as exc:
                log.exception("whisper model failed to load", extra={"model": self.model_name})
                raise unavailable() from exc
        return self._model

    def transcribe(self, audio: bytes) -> Transcript:
        from faster_whisper import decode_audio

        try:
            samples = decode_audio(io.BytesIO(audio), sampling_rate=SAMPLE_RATE)
        except Exception as exc:  # PyAV raises many types for broken or unknown files
            raise audio_invalid() from exc
        duration = len(samples) / SAMPLE_RATE
        if duration == 0:
            raise audio_empty()
        if duration > MAX_SECONDS + 1:  # 1 s of slack for the recorder's own stop delay
            raise audio_too_large()

        with self._lock:
            model = self._load()
            segments, info = model.transcribe(
                samples,
                language=None,  # V6: auto-detect
                initial_prompt=VOCABULARY_HINT,
                vad_filter=True,  # skips silence, so a silent clip gives no text
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            raise no_speech()
        return Transcript(text=text, language=info.language, duration_s=round(duration, 1))


@lru_cache
def get_transcriber() -> Transcriber:
    """FastAPI dependency; tests override it with a fake (no model, no download)."""
    return WhisperTranscriber(get_settings().whisper_model)
