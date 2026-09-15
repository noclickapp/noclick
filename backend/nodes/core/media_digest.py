"""Media that reaches an AI agent → something the model can read.

Every channel hands agents media in its own shape: a WhatsApp voice note, a
Telegram photo, an email's audio attachment, a Discord upload, a file dropped
into the chat composer. This is the one place that turns those into text the
model can act on, keyed by media KIND, so how a kind is understood is decided
once for every medium:

    audio    → transcription (AI, credit-gated, charged at provider cost plus
               the platform markup — the same accounting as rehearsals)
    document → text extraction (the free CPU path in utils.content_extraction)
    image    → nothing here: the SDK path injects image URLs as vision content
               (handlers/_media_utils) and CLI harnesses fetch the URL
    video    → nothing yet — the URL stands

Providers describe what an event carried with ``media_entry``
(nodes.core.agent_events) in their ``resolve_agent_event`` result; AgentNode
runs :func:`digest_media` over those entries pre-dispatch and composes the
digests into the turn with :func:`format_media_digests`. A digest never
raises into the turn: media the layer cannot read yields an agent-facing note
instead (format unsupported, too long, no credits, provider down), so the
agent can ask the sender for text rather than guess. A platform may swap a
kind's digester with :func:`register_digester`.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from utils.content_extraction import (
    AI_EXTRACTION_MODEL,
    BillingContext,
    ExtractionError,
    can_extract,
    extract_content,
)

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
MAX_TRANSCRIBE_BYTES = 20 * 1024 * 1024   # a WhatsApp/Telegram voice note is ~100KB/min
MAX_TRANSCRIBE_SECONDS = 10 * 60          # bounds the per-message charge when the duration is known
MAX_AI_DIGESTS_PER_TURN = 3               # bounds a media-heavy message's charge
DEFAULT_DIGEST_CHARS = 8_000              # per-document extracted text carried into the turn
TRANSCRIBE_TIMEOUT_S = 90.0

# Audio input rides OpenRouter's ``input_audio`` content part (base64 + a
# container format) into a model with audio modality — Gemini Flash by
# default, the same family the extraction layer OCRs with.
AI_TRANSCRIPTION_MODEL = os.environ.get("AI_TRANSCRIPTION_MODEL", AI_EXTRACTION_MODEL)

# Formats OpenRouter accepts for input_audio, keyed by the MIME types the
# channels emit (WhatsApp/Telegram/Discord voice notes are Ogg Opus).
_AUDIO_FORMATS: Dict[str, str] = {
    "audio/ogg": "ogg", "audio/opus": "ogg", "application/ogg": "ogg",
    "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a",
    "audio/aac": "aac",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/vnd.wave": "wav",
    "audio/flac": "flac", "audio/x-flac": "flac",
    "audio/aiff": "aiff", "audio/x-aiff": "aiff",
}
_AUDIO_EXTENSIONS: Dict[str, str] = {
    ".ogg": "ogg", ".oga": "ogg", ".opus": "ogg", ".mp3": "mp3", ".m4a": "m4a",
    ".aac": "aac", ".wav": "wav", ".flac": "flac", ".aiff": "aiff", ".aif": "aiff",
}

_TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim, in the language(s) actually spoken. "
    "Output only the transcript: no commentary, no translation, and speaker "
    "labels only when more than one person speaks. If it contains no speech, "
    "output exactly [no speech]."
)
_NO_SPEECH = "[no speech]"

KINDS = ("audio", "image", "video", "document", "file")
_AI_KINDS = frozenset({"audio"})


class DigestError(ValueError):
    """Media this layer cannot turn into text. The message is agent-facing."""


def base_mime(mime_type: Optional[str]) -> str:
    """``audio/ogg; codecs=opus`` → ``audio/ogg``."""
    return (mime_type or "").split(";", 1)[0].strip().lower()


def media_kind(mime_type: Optional[str], filename: Optional[str] = None) -> str:
    """Which digester (if any) understands this media."""
    mime = base_mime(mime_type)
    name = (filename or "").lower()
    if mime.startswith("audio/") or any(name.endswith(ext) for ext in _AUDIO_EXTENSIONS):
        return "audio"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if can_extract(mime, filename):
        return "document"
    return "file"


def audio_format(mime_type: Optional[str], filename: Optional[str] = None) -> Optional[str]:
    """The ``input_audio.format`` for this audio, or ``None`` when no
    supported container matches (a browser's ``audio/webm`` recording)."""
    fmt = _AUDIO_FORMATS.get(base_mime(mime_type))
    if fmt:
        return fmt
    name = (filename or "").lower()
    return next((f for ext, f in _AUDIO_EXTENSIONS.items() if name.endswith(ext)), None)


def media_placeholder(
    kind: Optional[str], *, voice: bool = False, filename: Optional[str] = None
) -> str:
    """The body a caption-less media message reads as — "[voice message]",
    "[image]", "[document: invoice.pdf]" — so the turn says WHAT arrived
    even before (or without) a digest."""
    if kind == "audio":
        return "[voice message]" if voice else "[audio file]"
    if kind in ("image", "video"):
        return f"[{kind}]"
    if kind in ("document", "file"):
        return f"[{kind}: {filename}]" if filename else f"[{kind}]"
    return "[media message]"


# ── Refs and results ─────────────────────────────────────────────────────────

@dataclass
class MediaRef:
    """One piece of media an event carried, resolvable to bytes."""

    kind: str
    mime_type: str
    url: Optional[str] = None
    resource_id: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    duration_s: Optional[float] = None
    voice: bool = False              # a voice note (vs. an audio file)
    source: str = "message"
    # The provider's own dict for this media (the persisted record the chat
    # surface frames), annotated with the digest so the transcript renders
    # under the audio player. Never part of the ref's identity.
    record: Optional[Dict[str, Any]] = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        """How the turn names it: "voice message (0:14)", "audio file x.mp3"."""
        if self.kind == "audio":
            base = "voice message" if self.voice else "audio file"
        elif self.kind == "document":
            base = "document"
        else:
            base = {"image": "image", "video": "video"}.get(self.kind, "file")
        if self.kind != "audio" and self.filename:
            base += f" {self.filename}"
        if self.duration_s:
            secs = int(round(self.duration_s))
            base += f" ({secs // 60}:{secs % 60:02d})"
        return base


def refs_from_entries(entries: Any, *, source: str = "message") -> List[MediaRef]:
    """Normalize the ``media`` list a ``resolve_agent_event`` hook returned
    (see ``agent_events.media_entry``). Entries without a fetchable URL or a
    resource id are dropped — nothing can be read from them."""
    refs: List[MediaRef] = []
    if not isinstance(entries, list):
        return refs
    for e in entries:
        if not isinstance(e, dict):
            continue
        url = e.get("url")
        url = url if isinstance(url, str) and url.startswith(("http://", "https://")) else None
        resource_id = str(e["resource_id"]) if e.get("resource_id") else None
        if not url and not resource_id:
            continue
        mime = str(e.get("mime_type") or "")
        filename = e.get("filename") or None
        size = e.get("size_bytes")
        duration = e.get("duration_s")
        refs.append(
            MediaRef(
                kind=media_kind(mime, filename),
                mime_type=mime,
                url=url,
                resource_id=resource_id,
                filename=str(filename) if filename else None,
                size_bytes=int(size) if isinstance(size, (int, float)) and size >= 0 else None,
                duration_s=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
                voice=bool(e.get("voice")),
                source=str(e.get("source") or source),
                record=e.get("record") if isinstance(e.get("record"), dict) else None,
            )
        )
    return refs


@dataclass
class MediaDigest:
    ref: MediaRef
    text: Optional[str] = None
    method: Optional[str] = None     # 'transcription' | 'document'
    error: Optional[str] = None      # agent-facing reason nothing was produced
    truncated: bool = False
    cost_charged: Optional[Decimal] = None


@dataclass
class DigestContext:
    """Who pays and what is allowed. ``billing`` None or ``allow_ai`` False
    refuses AI digests with a note; free digests still run."""

    billing: Optional[BillingContext] = None
    allow_ai: bool = True
    workflow_id: Optional[str] = None
    char_budget: int = DEFAULT_DIGEST_CHARS


# ── Registry ─────────────────────────────────────────────────────────────────

Digester = Callable[[MediaRef, bytes, DigestContext], Awaitable[MediaDigest]]
_DIGESTERS: Dict[str, Digester] = {}


def register_digester(kind: str, fn: Optional[Digester]) -> None:
    """Install (or, with ``None``, remove) the digester for a media kind."""
    if kind not in KINDS:
        raise ValueError(f"unknown media kind {kind!r}; expected one of {KINDS}")
    if fn is None:
        _DIGESTERS.pop(kind, None)
    else:
        _DIGESTERS[kind] = fn


def digester_for(kind: str) -> Optional[Digester]:
    return _DIGESTERS.get(kind)


# ── Transcription ────────────────────────────────────────────────────────────

async def transcribe_audio(
    data: bytes,
    *,
    mime_type: str,
    filename: Optional[str],
    billing: BillingContext,
    duration_s: Optional[float] = None,
) -> Tuple[str, Optional[Decimal]]:
    """Audio bytes → transcript. Credit-gated BEFORE the model call; charged
    at the provider's reported cost with the platform markup (a
    ``:free`` model records $0). Returns ``(text, cost_charged)``."""
    fmt = audio_format(mime_type, filename)
    if not fmt:
        raise DigestError(
            f"audio format {base_mime(mime_type) or 'unknown'} is not supported for "
            f"transcription (supported: {', '.join(sorted(set(_AUDIO_FORMATS.values())))})"
        )
    if len(data) > MAX_TRANSCRIBE_BYTES:
        raise DigestError(
            f"audio is {len(data) // (1024 * 1024)}MB — transcription is capped at "
            f"{MAX_TRANSCRIBE_BYTES // (1024 * 1024)}MB"
        )
    if duration_s and duration_s > MAX_TRANSCRIBE_SECONDS:
        raise DigestError(
            f"audio is {int(duration_s // 60)} minutes long — transcription is capped at "
            f"{MAX_TRANSCRIBE_SECONDS // 60} minutes"
        )

    from billing.usage_tracker import usage_tracker

    # Pre-flight gate BEFORE any model spend; raises InsufficientBalanceError.
    await usage_tracker.enforce_credit_gate(
        billing.user_id,
        organization_id=billing.organization_id,
        sio=billing.sio,
        sid=billing.sid,
        surface="media_transcription",
    )

    import litellm

    model = AI_TRANSCRIPTION_MODEL
    extra_body: Dict[str, Any] = {}
    if model.startswith("openrouter/"):
        # OpenRouter usage accounting: provider-reported cost rides back on
        # response.usage (this extra_body 400s on other providers).
        extra_body["usage"] = {"include": True}
    response = await litellm.acompletion(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _TRANSCRIBE_PROMPT},
                {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(data).decode(),
                    "format": fmt,
                }},
            ],
        }],
        temperature=0.0,
        timeout=TRANSCRIBE_TIMEOUT_S,
        extra_body=extra_body,
    )
    text = (response.choices[0].message.content or "").strip()
    cost = await _record_transcription_cost(response, billing, model, len(data), duration_s, fmt)
    if not text or text.strip("`\"' ").lower() == _NO_SPEECH:
        raise DigestError("no speech was detected in the audio")
    return text, cost


async def _record_transcription_cost(
    response: Any,
    billing: BillingContext,
    model: str,
    size_bytes: int,
    duration_s: Optional[float],
    fmt: str,
) -> Optional[Decimal]:
    """One ``extraction/ai_transcription`` usage event per transcription —
    recorded even when the provider reported no cost (a $0 row is still the
    record that the call happened)."""
    from billing.markup import apply_platform_markup
    from billing.schema import UsageEventData
    from billing.usage_tracker import usage_tracker
    from coder.openai_agent.litellm_model import extract_cost_from_response

    provider_cost, reported = extract_cost_from_response(response)
    if not reported:
        logger.warning(
            f"[media_digest] {model} reported no cost for a transcription — recording $0"
        )
    charged = apply_platform_markup(
        Decimal(str(provider_cost or 0.0)), user_resource=False, model=model
    )
    usage = getattr(response, "usage", None)
    total_tokens = getattr(usage, "total_tokens", None) or 0
    await usage_tracker.track_usage_event(
        UsageEventData(
            user_id=billing.user_id,
            total_cost=charged,
            usage_type="api_usage",
            usage_subtype="extraction/ai_transcription",
            quantity=Decimal(1),
            unit_type="requests",
            user_resource=False,
            organization_id=billing.organization_id,
            metadata={
                "workflow_id": billing.workflow_id,
                "node_id": billing.node_id,
                "model": model,
                "format": fmt,
                "size_bytes": size_bytes,
                "duration_s": duration_s,
                "tokens": total_tokens,
                "provider_cost": provider_cost,
                "cost_reported": reported,
            },
        ),
        sio=billing.sio,
        sid=billing.sid,
    )
    return charged


async def _digest_audio(ref: MediaRef, data: bytes, ctx: DigestContext) -> MediaDigest:
    assert ctx.billing is not None  # digest_media refuses AI kinds without one
    text, cost = await transcribe_audio(
        data,
        mime_type=ref.mime_type,
        filename=ref.filename,
        billing=ctx.billing,
        duration_s=ref.duration_s,
    )
    return MediaDigest(ref=ref, text=text, method="transcription", cost_charged=cost)


async def _digest_document(ref: MediaRef, data: bytes, ctx: DigestContext) -> MediaDigest:
    """The free CPU path only — a scanned PDF yields the extraction layer's
    own note (AI OCR stays behind an explicit fetch)."""
    content = await extract_content(
        data,
        mime_type=ref.mime_type,
        filename=ref.filename or "document",
        char_budget=ctx.char_budget,
    )
    return MediaDigest(
        ref=ref, text=content.text, method=content.method, truncated=content.truncated
    )


register_digester("audio", _digest_audio)
register_digester("document", _digest_document)


# ── Driver ───────────────────────────────────────────────────────────────────

async def _fetch(ref: MediaRef, ctx: DigestContext, max_bytes: int) -> bytes:
    """Bytes for a ref. A resource id wins over its public URL: it streams
    from a presigned URL without the SSRF guard judging the storage host (a
    self-hosted store may live on a private address)."""
    from nodes.core.media_resolver import resolve_media_input

    value = ref.resource_id or ref.url
    resolved = await resolve_media_input(
        value, max_bytes=max_bytes, default_mime=ref.mime_type or "application/octet-stream",
        workflow_id=ctx.workflow_id,
    )
    if not ref.mime_type and resolved.mime_type:
        ref.mime_type = resolved.mime_type
    return resolved.data


def _annotate(ref: MediaRef, digest: MediaDigest) -> None:
    if ref.record is None:
        return
    if digest.text and digest.method == "transcription":
        ref.record["transcript"] = digest.text
    elif digest.text:
        ref.record["extracted_text"] = digest.text
    elif digest.error:
        ref.record["digest_error"] = digest.error


async def digest_media(refs: List[MediaRef], ctx: DigestContext) -> List[MediaDigest]:
    """Digest every ref that has a digester. Never raises: each ref's failure
    becomes an agent-facing ``error`` on its digest. Our own bugs (a broken
    seam, not an unhappy provider) log at ERROR with the traceback so they
    are never mistaken for bad media."""
    results: List[MediaDigest] = []
    ai_used = 0
    for ref in refs:
        fn = digester_for(ref.kind)
        if fn is None:
            continue
        needs_ai = ref.kind in _AI_KINDS
        if needs_ai and not ctx.allow_ai:
            digest = MediaDigest(ref=ref, error="transcription is turned off for this agent")
        elif needs_ai and ctx.billing is None:
            digest = MediaDigest(ref=ref, error="no billing context for transcription")
        elif needs_ai and ai_used >= MAX_AI_DIGESTS_PER_TURN:
            digest = MediaDigest(
                ref=ref, error=f"at most {MAX_AI_DIGESTS_PER_TURN} audio files are transcribed per message"
            )
        else:
            digest = await _run_one(ref, fn, ctx)
            if needs_ai and digest.text:
                ai_used += 1
        _annotate(ref, digest)
        results.append(digest)
    return results


async def _run_one(ref: MediaRef, fn: Digester, ctx: DigestContext) -> MediaDigest:
    from billing.exceptions import InsufficientBalanceError

    max_bytes = MAX_TRANSCRIBE_BYTES if ref.kind == "audio" else 15 * 1024 * 1024
    try:
        data = await _fetch(ref, ctx, max_bytes)
        return await fn(ref, data, ctx)
    except InsufficientBalanceError as e:
        return MediaDigest(ref=ref, error=str(e))
    except (DigestError, ExtractionError) as e:
        return MediaDigest(ref=ref, error=str(e))
    except (ImportError, AttributeError, TypeError, NameError):
        logger.error(
            f"[media_digest] digester for {ref.kind} is broken ({ref.source})", exc_info=True
        )
        return MediaDigest(ref=ref, error="the media could not be processed (platform error)")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[media_digest] {ref.kind} digest failed ({ref.source}): {e}")
        return MediaDigest(ref=ref, error=f"could not be retrieved or processed ({e})")


# ── Turn text ────────────────────────────────────────────────────────────────

MEDIA_DIGEST_HEADER = "--- Media in this message ---"


def format_media_digests(digests: List[MediaDigest]) -> str:
    """The block composed into the agent's turn under the event text: each
    transcript/extraction fenced, each failure a one-line note that tells the
    agent what to do instead of guessing."""
    lines: List[str] = []
    for d in digests:
        label = d.ref.label
        label = label[0].upper() + label[1:]
        if d.text:
            what = "transcript" if d.method == "transcription" else "extracted text"
            lines += [f"{label} — {what}:", '"""', d.text, '"""']
            if d.truncated:
                lines.append("(truncated — fetch the file for the full text)")
        else:
            hint = (
                "Ask the sender to type it out if its content matters."
                if d.ref.kind == "audio"
                else "Fetch the URL yourself if its content matters."
            )
            lines.append(f"{label}: {d.error or 'could not be processed'}. {hint}")
    if not lines:
        return ""
    return "\n".join([MEDIA_DIGEST_HEADER, *lines])


def rehearsal_media_note(refs: List[MediaRef]) -> str:
    """What a Test Run says instead of digesting: the staged media is
    fabricated, so nothing is fetched, transcribed, or billed."""
    lines = [
        f"{r.label[0].upper() + r.label[1:]}: not transcribed in a Test Run "
        "— live messages are transcribed automatically."
        for r in refs
        if r.kind in _AI_KINDS
    ]
    return "\n".join([MEDIA_DIGEST_HEADER, *lines]) if lines else ""
