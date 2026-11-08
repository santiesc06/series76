"""Voice messages (US-22): audio in, text out. The app puts the text in the message box (V1)."""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.schemas import ErrorResponse, TranscribeResponse
from app.auth.deps import CurrentUser
from app.voice.transcriber import (
    MAX_BYTES,
    Transcriber,
    audio_empty,
    audio_too_large,
    get_transcriber,
)

router = APIRouter(prefix="/api", tags=["voice"])
log = logging.getLogger("voice")


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    responses={code: {"model": ErrorResponse} for code in (400, 401, 413, 422, 503)},
)
def transcribe(
    user: CurrentUser,
    transcriber: Annotated[Transcriber, Depends(get_transcriber)],
    audio: Annotated[UploadFile, File(description="Recording: M4A/AAC, WAV, MP3 or OGG, max 60 s")],
) -> TranscribeResponse:
    """Transcribes one recording with faster-whisper. The audio is not stored (design V5)."""
    data = audio.file.read(MAX_BYTES + 1)
    if not data:
        raise audio_empty()
    if len(data) > MAX_BYTES:
        raise audio_too_large()
    started = time.perf_counter()
    result = transcriber.transcribe(data)
    # No transcript in the log: it is the user's words (like the chat, which logs no query).
    log.info(
        "transcribe",
        extra={
            "duration_s": result.duration_s,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "language": result.language,
            "chars": len(result.text),
        },
    )
    return TranscribeResponse(
        text=result.text, language=result.language, duration_s=result.duration_s
    )
