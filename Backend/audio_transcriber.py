
"""
Cloud-first audio transcription for Sakhi-Sahayak.

Provider order:
1. Sarvam AI speech-to-text API
2. Local Whisper fallback

Gemini and OpenRouter are not used.

Environment variables:
    SARVAM_API_KEY
    SARVAM_STT_MODEL=saaras:v4
    TRANSCRIPTION_LANGUAGE=hi
    WHISPER_MODEL=base
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger("sakhi-sahayak.transcription")

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Sarvam accepts these common audio formats.
SUPPORTED_SUFFIXES = {
    ".webm", ".weba", ".wav", ".mp3", ".mpeg", ".mpga",
    ".m4a", ".mp4", ".ogg", ".oga", ".opus", ".flac",
    ".aac", ".aiff", ".aif", ".amr", ".wma",
}

# Sarvam expects BCP-47 language codes.
LANGUAGE_CODES = {
    "en": "en-IN",
    "hi": "hi-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "od": "od-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "ur": "ur-IN",
    "as": "as-IN",
    "ne": "ne-IN",
    "kok": "kok-IN",
    "ks": "ks-IN",
    "sd": "sd-IN",
    "sa": "sa-IN",
    "sat": "sat-IN",
    "mni": "mni-IN",
    "brx": "brx-IN",
    "mai": "mai-IN",
    "doi": "doi-IN",
}


def _language_guess(text: str) -> str:
    """Best-effort language fallback for Hindi/Marathi and English."""
    if re.search(r"[\u0900-\u097F]", text):
        return os.getenv("TRANSCRIPTION_LANGUAGE", "hi").strip().lower() or "hi"

    return os.getenv("TRANSCRIPTION_LANGUAGE", "en").strip().lower() or "en"


def _normalize_language(language: str | None, transcript: str) -> str:
    """Return a short language code such as hi, mr, or en."""
    language = (language or "").strip().lower()

    if language and language not in {"unknown", "und", "none"}:
        return language.split("-")[0]

    return _language_guess(transcript)


def _sarvam_language_code() -> str:
    """Convert a configured language hint into Sarvam's format."""
    language = os.getenv("TRANSCRIPTION_LANGUAGE", "").strip().lower()

    if not language or language in {"auto", "unknown", "und"}:
        return "unknown"

    if language in LANGUAGE_CODES:
        return LANGUAGE_CODES[language]

    if language.endswith("-in"):
        return language

    raise ValueError(
        f"Unsupported TRANSCRIPTION_LANGUAGE: {language}. "
        "Use a supported language code such as hi, mr, en, or auto."
    )


async def _sarvam_transcribe(
    contents: bytes,
    suffix: str,
) -> tuple[str, str]:
    """Transcribe audio using Sarvam AI's speech-to-text REST API."""
    api_key = os.getenv("SARVAM_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("SARVAM_API_KEY is not configured")

    if not contents:
        raise ValueError("Audio file is empty")

    suffix = suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported audio file extension: {suffix}")

    model = os.getenv("SARVAM_STT_MODEL", "saaras:v4").strip()
    language_code = _sarvam_language_code()

    # Sarvam expects a multipart/form-data upload, not base64 JSON.
    data = {
        "model": model,
        "mode": "transcribe",
        "language_code": language_code,
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(58.0, connect=10.0)
    ) as client:
        response = await client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": api_key},
            data=data,
            files={
                "file": (
                    f"audio{suffix}",
                    contents,
                    "application/octet-stream",
                )
            },
        )

    if response.is_error:
        raise RuntimeError(
            f"Sarvam transcription failed ({response.status_code}): "
            f"{response.text[:500]}"
        )

    result = response.json()
    transcript = str(result.get("transcript") or "").strip()
    language = str(result.get("language_code") or "").strip()

    if not transcript:
        raise RuntimeError("Sarvam returned an empty transcript")

    return transcript, _normalize_language(language, transcript)


async def _local_whisper_transcribe(
    tmp_name: str,
) -> tuple[str, str]:
    """Run local Whisper without blocking the async server."""
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Local Whisper is not installed. Run: pip install openai-whisper"
        ) from exc

    model_name = os.getenv("WHISPER_MODEL", "base").strip()

    # Load the model in a worker thread.
    model = await asyncio.to_thread(whisper.load_model, model_name)

    # Leave language unset so Whisper can auto-detect it.
    result = await asyncio.to_thread(
        model.transcribe,
        tmp_name,
        fp16=False,
    )

    transcript = str(result.get("text") or "").strip()
    language = str(result.get("language") or "").strip()

    if not transcript:
        raise RuntimeError("Local Whisper did not recognize any speech")

    return transcript, _normalize_language(language, transcript)


async def transcribe_audio(
    contents: bytes,
    suffix: str,
    tmp_name: str | None = None,
    prefer_audio_understanding: bool = False,
) -> tuple[str, str, str]:
    """
    Return (transcript, language, provider).

    Sarvam is attempted first. Local Whisper is the fallback.

    `prefer_audio_understanding` is retained for compatibility with
    existing callers; it does not enable audio-event detection.
    """
    del prefer_audio_understanding

    if not contents:
        raise ValueError("Audio file is empty")

    errors: list[str] = []

    # First attempt: Sarvam cloud transcription.
    try:
        transcript, language = await _sarvam_transcribe(contents, suffix)
        logger.info("Transcription completed using Sarvam AI")
        return transcript, language, "sarvam"
    except Exception as exc:
        logger.warning(
            "Sarvam transcription failed; trying local Whisper: %s", exc
        )
        errors.append(f"Sarvam: {exc}")

    # Ensure Whisper always has an actual file to read.
    created_temp_file = False
    whisper_path = tmp_name

    try:
        if not whisper_path:
            with tempfile.NamedTemporaryFile(
                suffix=suffix if suffix.startswith(".") else ".webm",
                delete=False,
            ) as temp_file:
                temp_file.write(contents)
                whisper_path = temp_file.name
                created_temp_file = True

        transcript, language = await _local_whisper_transcribe(whisper_path)

        logger.info("Transcription completed using local Whisper")
        return transcript, language, "local_whisper"

    except Exception as exc:
        logger.exception("Local Whisper transcription failed")
        errors.append(f"Local Whisper: {exc}")

    finally:
        if created_temp_file and whisper_path:
            try:
                Path(whisper_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary audio file")

    raise RuntimeError(" | ".join(errors))
