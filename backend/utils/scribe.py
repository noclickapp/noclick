"""ElevenLabs Scribe v2 on OpenRouter's speech-to-text API, the one place the call is made
(https://openrouter.ai/docs/api/api-reference/stt/create-transcription, read 2026-10-21). The media digest
(``nodes.core.media_digest``) sends it a voice note for its text; the platform's transcriptions
(``cloud.platform.ai.providers.scribe``) a whole recording, each word timed and, with voices, each word's
speaker. Both run on the instance's OpenRouter key.

``transcribe`` builds the request and reads the answer; its ``post`` sends the request: ``openrouter_post``,
or a platform's own HTTP client. The whole recording goes in one JSON body (``input_audio``, base64). The API
reads the container from the audio itself, so ``format`` only names it: every container the channels deliver
was read as sent (2026-10-21), Ogg and WebM Opus, MP3, M4A and ADTS AAC, WAV, an iPhone's Core Audio voice
message, AMR and 3GP.

Audio events (laughter, music) aren't tagged: on a long, mostly silent recording tagging them made the model
fill the silence with stray words and fold the last twenty minutes into one untimed event.

Each answer says how many seconds of audio OpenRouter billed and what they cost (``usage``), at Scribe's
listed $0.22 an hour; audio with no speech answers no text and costs nothing.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import httpx

MODEL = "elevenlabs/scribe-v2"
PATH = "/audio/transcriptions"
USD_PER_HOUR = Decimal("0.22")
# The ``format`` each MIME type is named as.
FORMATS: Dict[str, str] = {
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
    "audio/vnd.wave": "wav", "audio/ogg": "ogg", "audio/opus": "ogg", "application/ogg": "ogg",
    "audio/flac": "flac", "audio/x-flac": "flac", "audio/aac": "aac", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
    "audio/m4a": "m4a", "audio/aiff": "aiff", "audio/x-aiff": "aiff", "audio/webm": "webm",
    "audio/x-caf": "caf", "audio/caf": "caf", "audio/amr": "amr", "audio/3gpp": "3gp", "video/3gpp": "3gp",
}

#: Sends one request: the API path and the JSON body, answering the JSON answer.
Post = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


class ScribeError(RuntimeError):
    """OpenRouter refused the call or couldn't be reached: ``status`` is its HTTP status (None when nothing
    answered) and ``said`` its words."""

    def __init__(self, status: Optional[int], said: str):
        super().__init__(f"HTTP {status}: {said}" if status else said)
        self.status, self.said = status, said


@dataclass(frozen=True)
class Heard:
    """One answered call."""

    text: str
    #: As the API names it (ISO 639-3); asked for ``timed`` only.
    language: Optional[str]
    duration_s: float
    #: The spoken words, each timed (``start``, ``end``) and, with voices, its ``speaker_label``; ``timed`` only.
    words: Tuple[Dict[str, Any], ...]
    #: What OpenRouter billed: seconds of audio, and what they cost in US dollars.
    billed_s: Decimal
    vendor_usd: Decimal


def openrouter_post(*, timeout_s: float) -> Post:
    """Requests on the instance's OpenRouter key; ``utils.media_generation.MediaError`` when it has none."""
    from utils.media_generation import OPENROUTER_API, openrouter_headers, openrouter_key

    headers = openrouter_headers(openrouter_key())

    async def post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(f"{OPENROUTER_API}{path}", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise ScribeError(None, f"no answer from OpenRouter ({type(exc).__name__})") from None
        if response.status_code >= 400:
            raise ScribeError(response.status_code, response.text[:500])
        return response.json()

    return post


async def transcribe(audio: bytes, fmt: str, *, post: Post, language: Optional[str] = None, timed: bool = False,
                     diarize: bool = False, speakers: Optional[int] = None) -> Heard:
    """``audio`` (in the container ``fmt`` names) transcribed whole. ``timed`` asks for the words with their
    times and the language heard; ``diarize`` tells the voices apart, exactly ``speakers`` of them when given."""
    options: Dict[str, Any] = {"tag_audio_events": False, **({"num_speakers": speakers} if speakers else {})}
    done = await post(PATH, {
        "model": MODEL, "input_audio": {"data": base64.b64encode(audio).decode(), "format": fmt},
        **({"response_format": "verbose_json", "timestamp_granularities": ["word"]} if timed else {}),
        **({"language": language} if language else {}), **({"diarize": True} if diarize else {}),
        "provider": {"options": {"elevenlabs": options}}})
    usage = done["usage"]
    # Audio with no speech is billed no seconds, and its usage names none.
    billed_s = Decimal(str(usage.get("seconds", 0)))
    return Heard(text=done.get("text") or "", language=done.get("language"),
                 duration_s=float(done.get("duration") or billed_s),
                 words=tuple(w for w in done.get("words") or () if w.get("type") in (None, "word")),
                 billed_s=billed_s, vendor_usd=Decimal(str(usage["cost"])))
