"""Media digest layer (nodes/core/media_digest.py).

Contracts under test:
- kind classification + the OpenRouter ``input_audio`` format mapping
  (a WhatsApp/Telegram voice note is ``audio/ogg; codecs=opus`` → ogg);
- transcription credit-gates BEFORE the model call — a gate raise means
  zero spend and no usage row;
- one transcription records ONE ``extraction/ai_transcription`` usage event
  at the provider's reported cost × platform markup through the Owner Pays
  choke point, and a provider that reports no cost still lands a $0 row;
- byte/duration caps, an unsupported container and a ``[no speech]`` answer
  refuse with an agent-facing DigestError;
- digest_media NEVER raises: a ref's failure is a note on its digest,
  AI kinds are refused without billing or with allow_ai=False, the per-turn
  AI cap holds, and a broken seam logs at ERROR instead of blaming media;
- documents digest through the free extraction path and never bill;
- refs_from_entries drops entries with nothing to fetch; a digest annotates
  the provider's record (``transcript``) for the chat surface;
- format_media_digests fences what was read and says what to do about
  what wasn't.
"""

import asyncio
import logging
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing.exceptions import InsufficientBalanceError
from billing.markup import apply_platform_markup
from nodes.core import media_digest as md
from nodes.core.agent_events import media_entry
from nodes.core.media_resolver import ResolvedMedia
from tests.mocks.pdf_fixtures import text_pdf
from utils.content_extraction import BillingContext

TEST_USER = "00000000-0000-4000-8000-000000000001"


def _billing() -> BillingContext:
    return BillingContext(user_id=TEST_USER, organization_id=None, workflow_id="w1", node_id="n1")


def _response(text="hello from the voice note", cost=0.0012, tokens=80):
    usage = SimpleNamespace(cost=cost, total_tokens=tokens) if cost is not None else SimpleNamespace(total_tokens=tokens)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=usage,
        _hidden_params={},
    )


def _tracker():
    tracker = MagicMock()
    tracker.enforce_credit_gate = AsyncMock()
    tracker.track_usage_event = AsyncMock()
    return tracker


def _voice_ref(**kw) -> md.MediaRef:
    base = dict(
        kind="audio", mime_type="audio/ogg; codecs=opus", url="https://assets.example/v.oga",
        filename="v.oga", voice=True, duration_s=14, record={}, source="whatsapp",
    )
    base.update(kw)
    return md.MediaRef(**base)


# ── classification ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "mime, filename, kind",
    [
        ("audio/ogg; codecs=opus", None, "audio"),
        ("application/octet-stream", "memo.m4a", "audio"),
        ("image/jpeg", None, "image"),
        ("video/mp4", None, "video"),
        ("application/pdf", "a.pdf", "document"),
        ("text/plain", None, "document"),
        ("application/zip", "x.zip", "file"),
    ],
)
def test_media_kind(mime, filename, kind):
    assert md.media_kind(mime, filename) == kind


@pytest.mark.parametrize(
    "mime, filename, fmt",
    [
        ("audio/ogg; codecs=opus", None, "ogg"),
        ("audio/opus", None, "ogg"),
        ("audio/mpeg", None, "mp3"),
        ("audio/x-m4a", None, "m4a"),
        ("audio/wav", None, "wav"),
        ("application/octet-stream", "note.OGA", "ogg"),
        ("audio/webm", "clip.webm", None),
    ],
)
def test_audio_format(mime, filename, fmt):
    assert md.audio_format(mime, filename) == fmt


def test_placeholder_names_what_arrived():
    assert md.media_placeholder("audio", voice=True) == "[voice message]"
    assert md.media_placeholder("audio") == "[audio file]"
    assert md.media_placeholder("document", filename="q.pdf") == "[document: q.pdf]"
    assert md.media_placeholder(None) == "[media message]"


def test_refs_from_entries_keeps_only_fetchable_media():
    record = {"url": "https://a/x.oga"}
    entries = [
        media_entry(url="https://a/x.oga", mime_type="audio/ogg", duration_s=3, voice=True, record=record),
        media_entry(resource_id="00000000-0000-4000-8000-0000000000aa", mime_type="application/pdf", filename="q.pdf"),
        media_entry(url="file_id_only", mime_type="audio/ogg"),   # no URL, no resource — dropped
        "junk",
    ]
    refs = md.refs_from_entries(entries, source="telegram")
    assert [r.kind for r in refs] == ["audio", "document"]
    assert refs[0].record is record and refs[0].voice and refs[0].duration_s == 3
    assert refs[1].resource_id == "00000000-0000-4000-8000-0000000000aa"
    assert refs[0].source == "telegram"
    assert refs[0].label == "voice message (0:03)"
    assert refs[1].label == "document q.pdf"


# ── transcription: gate, billing, caps ───────────────────────────────────────

def test_transcription_gates_before_model_and_records_cost_with_markup():
    calls = []
    tracker = _tracker()
    tracker.enforce_credit_gate.side_effect = lambda *a, **k: calls.append("gate")

    async def fake_completion(**kwargs):
        calls.append("model")
        # The audio rides as OpenRouter's input_audio part, base64 + container.
        part = kwargs["messages"][0]["content"][1]
        assert part["type"] == "input_audio"
        assert part["input_audio"]["format"] == "ogg"
        assert kwargs["extra_body"].get("usage") == {"include": True}  # cost accounting on
        return _response(cost=0.0012, tokens=80)

    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("litellm.acompletion", new=fake_completion), \
         patch.object(md, "AI_TRANSCRIPTION_MODEL", "openrouter/google/gemini-3.5-flash"):
        text, cost = asyncio.run(md.transcribe_audio(
            b"ogg-bytes", mime_type="audio/ogg; codecs=opus", filename="v.oga",
            billing=_billing(), duration_s=14,
        ))

    assert calls == ["gate", "model"]
    assert text == "hello from the voice note"
    expected = apply_platform_markup(Decimal("0.0012"), user_resource=False, model="x")
    assert cost == expected
    tracker.enforce_credit_gate.assert_awaited_once()
    assert tracker.enforce_credit_gate.await_args.kwargs["surface"] == "media_transcription"
    tracker.track_usage_event.assert_awaited_once()
    event = tracker.track_usage_event.await_args.args[0]
    assert event.user_id == TEST_USER          # raw runner — Owner Pays resolves the pool
    assert event.usage_type == "api_usage"
    assert event.usage_subtype == "extraction/ai_transcription"
    assert event.total_cost == expected
    assert event.unit_type == "requests" and event.quantity == 1
    assert event.metadata["duration_s"] == 14
    assert event.metadata["cost_reported"] is True
    assert event.metadata["tokens"] == 80


def test_gate_raise_means_zero_spend():
    tracker = _tracker()
    tracker.enforce_credit_gate.side_effect = InsufficientBalanceError("Insufficient credits: 0 < 1 required")
    model = AsyncMock(return_value=_response())
    with patch("billing.usage_tracker.usage_tracker", tracker), patch("litellm.acompletion", new=model):
        with pytest.raises(InsufficientBalanceError):
            asyncio.run(md.transcribe_audio(
                b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()
            ))
    model.assert_not_awaited()
    tracker.track_usage_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_uses_bounded_probe_and_bills_provider_cost(monkeypatch):
    tracker = _tracker()
    model = AsyncMock(return_value=_response("At 0:02, the sign reads Main Street."))
    duration = AsyncMock(return_value=10.0)
    monkeypatch.setattr("utils.video_probe.video_duration", duration)
    ref = md.MediaRef(kind="video", mime_type="video/mp4")
    with patch("billing.usage_tracker.usage_tracker", tracker), patch("litellm.acompletion", model):
        digest = await md.digester_for("video")(ref, b"video", md.DigestContext(billing=_billing()))
        assert digest.method == "video_description" and "Main Street" in digest.text
        assert model.await_args.kwargs["messages"][0]["content"][1]["video_url"]["url"] == "data:video/mp4;base64,dmlkZW8="
        assert tracker.track_usage_event.await_args.args[0].usage_subtype == "extraction/ai_video_digest"
        model.reset_mock()
        duration.return_value = md.MAX_VIDEO_SECONDS + 1
        with pytest.raises(md.DigestError, match="two-minute"):
            await md.digester_for("video")(ref, b"video", md.DigestContext(billing=_billing()))
        model.assert_not_awaited()
        duration.return_value = 10
        tracker.enforce_credit_gate.side_effect = InsufficientBalanceError("Out of credits")
        with pytest.raises(InsufficientBalanceError):
            await md.digester_for("video")(ref, b"video", md.DigestContext(billing=_billing()))
        model.assert_not_awaited()


def test_unreported_cost_still_lands_a_zero_row(caplog):
    tracker = _tracker()
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("litellm.acompletion", new=AsyncMock(return_value=_response(cost=None))), \
         caplog.at_level(logging.WARNING):
        text, cost = asyncio.run(md.transcribe_audio(
            b"x", mime_type="audio/mpeg", filename="a.mp3", billing=_billing()
        ))
    assert text and cost == Decimal("0")
    event = tracker.track_usage_event.await_args.args[0]
    assert event.total_cost == Decimal("0") and event.metadata["cost_reported"] is False
    assert "reported no cost" in caplog.text


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (dict(data=b"x", mime_type="audio/webm", filename="clip.webm"), "not supported"),
        (dict(data=b"x" * (md.MAX_TRANSCRIBE_BYTES + 1), mime_type="audio/ogg", filename="v.oga"), "capped"),
        (dict(data=b"x", mime_type="audio/ogg", filename="v.oga", duration_s=md.MAX_TRANSCRIBE_SECONDS + 1), "minutes"),
    ],
)
def test_caps_refuse_before_any_spend(kwargs, match):
    tracker = _tracker()
    model = AsyncMock(return_value=_response())
    with patch("billing.usage_tracker.usage_tracker", tracker), patch("litellm.acompletion", new=model):
        with pytest.raises(md.DigestError, match=match):
            asyncio.run(md.transcribe_audio(billing=_billing(), **kwargs))
    tracker.enforce_credit_gate.assert_not_awaited()
    model.assert_not_awaited()


def test_no_speech_is_a_refusal_not_a_transcript():
    tracker = _tracker()
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("litellm.acompletion", new=AsyncMock(return_value=_response(text="[no speech]"))):
        with pytest.raises(md.DigestError, match="no speech"):
            asyncio.run(md.transcribe_audio(b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()))
    tracker.track_usage_event.assert_awaited_once()  # the call happened and is recorded


# ── digest_media: never raises, gates AI, annotates ─────────────────────────

def _resolver(data=b"ogg-bytes", mime="audio/ogg"):
    return AsyncMock(return_value=ResolvedMedia(data=data, mime_type=mime, filename="f"))


def test_digest_media_transcribes_and_annotates_the_record():
    tracker = _tracker()
    record = {"url": "https://assets.example/v.oga", "rehosted": True}
    ref = _voice_ref(record=record)
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("litellm.acompletion", new=AsyncMock(return_value=_response(text="call me back"))), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()) as resolver:
        (digest,) = asyncio.run(md.digest_media([ref], md.DigestContext(billing=_billing(), workflow_id="w1")))
    assert digest.method == "transcription" and digest.text == "call me back"
    assert record["transcript"] == "call me back"
    resolver.assert_awaited_once()
    assert resolver.await_args.args[0] == ref.url


def test_digest_media_prefers_the_resource_id_over_the_public_url():
    tracker = _tracker()
    ref = _voice_ref(resource_id="00000000-0000-4000-8000-0000000000aa")
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("litellm.acompletion", new=AsyncMock(return_value=_response())), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()) as resolver:
        asyncio.run(md.digest_media([ref], md.DigestContext(billing=_billing(), workflow_id="w1")))
    assert resolver.await_args.args[0] == ref.resource_id
    assert resolver.await_args.kwargs["workflow_id"] == "w1"


def test_digest_media_refuses_ai_without_billing_or_when_disabled():
    model = AsyncMock(return_value=_response())
    with patch("litellm.acompletion", new=model), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        (off,) = asyncio.run(md.digest_media([_voice_ref()], md.DigestContext(billing=_billing(), allow_ai=False)))
        (unpaid,) = asyncio.run(md.digest_media([_voice_ref()], md.DigestContext(billing=None)))
    assert off.text is None and "turned off" in off.error
    assert unpaid.text is None and "billing" in unpaid.error
    model.assert_not_awaited()


def test_digest_media_caps_ai_digests_per_turn():
    tracker = _tracker()
    refs = [_voice_ref(url=f"https://a/{i}.oga") for i in range(md.MAX_AI_DIGESTS_PER_TURN + 2)]
    model = AsyncMock(return_value=_response())
    with patch("billing.usage_tracker.usage_tracker", tracker), patch("litellm.acompletion", new=model), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        digests = asyncio.run(md.digest_media(refs, md.DigestContext(billing=_billing())))
    assert sum(1 for d in digests if d.text) == md.MAX_AI_DIGESTS_PER_TURN
    assert all("at most" in d.error for d in digests if not d.text)
    assert model.await_count == md.MAX_AI_DIGESTS_PER_TURN


def test_digest_media_turns_failures_into_notes_never_raises(caplog):
    tracker = _tracker()
    tracker.enforce_credit_gate.side_effect = InsufficientBalanceError("Insufficient credits: 0 < 1 required")
    broke = _voice_ref(url="https://a/broke.oga", record={})
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        (unpaid,) = asyncio.run(md.digest_media([_voice_ref()], md.DigestContext(billing=_billing())))
    assert "Insufficient credits" in unpaid.error

    # A provider/transport failure is a warning + note; our own bug is an ERROR
    # with traceback, still a note — the turn always proceeds.
    with patch("nodes.core.media_resolver.resolve_media_input", AsyncMock(side_effect=ValueError("Resource not found"))), \
         caplog.at_level(logging.WARNING):
        (gone,) = asyncio.run(md.digest_media([_voice_ref()], md.DigestContext(billing=_billing())))
    assert "Resource not found" in gone.error

    async def broken_digester(ref, data, ctx):
        raise TypeError("seam mismatch")

    with patch.dict(md._DIGESTERS, {"audio": broken_digester}), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()), \
         caplog.at_level(logging.ERROR):
        (bug,) = asyncio.run(md.digest_media([broke], md.DigestContext(billing=_billing())))
    assert "platform error" in bug.error
    assert broke.record["digest_error"] == bug.error
    assert any(r.levelno == logging.ERROR and "broken" in r.getMessage() for r in caplog.records)


def test_documents_digest_free_and_passthrough_kinds_produce_nothing():
    tracker = _tracker()
    doc = md.MediaRef(kind="document", mime_type="application/pdf", url="https://a/q.pdf", filename="q.pdf", record={})
    img = md.MediaRef(kind="image", mime_type="image/png", url="https://a/p.png")
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver(text_pdf(), "application/pdf")):
        digests = asyncio.run(md.digest_media([img, doc], md.DigestContext(billing=None)))
    assert len(digests) == 1 and digests[0].ref is doc
    assert digests[0].method == "document" and "$10" in digests[0].text
    assert doc.record["extracted_text"] == digests[0].text
    tracker.enforce_credit_gate.assert_not_awaited()
    tracker.track_usage_event.assert_not_awaited()


def test_register_digester_swaps_a_kind_and_rejects_unknown_kinds():
    async def describe(ref, data, ctx):
        return md.MediaDigest(ref=ref, text="a red bicycle", method="description")

    original = md.digester_for("image")
    try:
        md.register_digester("image", describe)
        with patch("nodes.core.media_resolver.resolve_media_input", _resolver(b"png", "image/png")):
            (d,) = asyncio.run(md.digest_media(
                [md.MediaRef(kind="image", mime_type="image/png", url="https://a/p.png")],
                md.DigestContext(billing=None),
            ))
        assert d.text == "a red bicycle"
    finally:
        md.register_digester("image", original)
    with pytest.raises(ValueError, match="unknown media kind"):
        md.register_digester("hologram", describe)


# ── turn text ────────────────────────────────────────────────────────────────

def test_format_media_digests_fences_text_and_explains_failures():
    ok = md.MediaDigest(ref=_voice_ref(), text="call me back", method="transcription")
    doc = md.MediaDigest(
        ref=md.MediaRef(kind="document", mime_type="application/pdf", filename="q.pdf"),
        text="line 1", method="document", truncated=True,
    )
    bad = md.MediaDigest(ref=_voice_ref(voice=True, duration_s=None), error="audio format audio/webm is not supported")
    block = md.format_media_digests([ok, doc, bad])
    assert block.startswith(md.MEDIA_DIGEST_HEADER)
    assert 'Voice message (0:14) — transcript:\n"""\ncall me back\n"""' in block
    assert 'Document q.pdf — extracted text:\n"""\nline 1\n"""\n(truncated' in block
    assert "Voice message: audio format audio/webm is not supported. Ask the sender to type it out" in block
    assert md.format_media_digests([]) == ""


def test_rehearsal_note_names_audio_only():
    refs = [_voice_ref(), md.MediaRef(kind="image", mime_type="image/png", url="https://a/p.png")]
    note = md.rehearsal_media_note(refs)
    assert "Voice message (0:14): not transcribed in a Test Run" in note
    assert "Image" not in note
    assert md.rehearsal_media_note([refs[1]]) == ""
