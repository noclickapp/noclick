"""Media digest layer (nodes/core/media_digest.py).

Contracts under test:
- kind classification + the container each audio is named as to Scribe
  (a WhatsApp/Telegram voice note is ``audio/ogg; codecs=opus`` → ogg);
- transcription is ElevenLabs Scribe v2 on OpenRouter's speech-to-text API,
  faked at its HTTP boundary: the request carries the audio exactly as it
  came (an iPhone's Core Audio voice message, AMR, 3GP and a browser's WebM
  included) on the instance's OpenRouter key, credit-gated BEFORE the call —
  a gate raise means zero spend and no usage row;
- one transcription records ONE ``extraction/ai_transcription`` usage event
  whose ``cost_usd`` is what OpenRouter billed for the audio's seconds
  (Scribe's price), × the old plans' platform markup, through the Owner Pays
  choke point; silence is recorded at its $0;
- byte/duration caps, an unsupported container, no speech, a refused or
  unreachable API and an instance without an OpenRouter key refuse with an
  agent-facing DigestError;
- a video's description is charged the cost OpenRouter reported, else its
  record of the call, and one priced nowhere is logged, never charged;
- digest_media NEVER raises: a ref's failure is a note on its digest,
  AI kinds are refused without billing or with allow_ai=False, the per-turn
  AI and document caps hold, and a broken seam logs at ERROR instead of blaming media;
- documents digest through the free extraction path and never bill;
- with ``readings``, a stored file is read once: a kept reading is reused
  (a document's within the turn's budget) without a fetch, a charge or a
  slot of the AI cap, a read is kept for the next reader, a failed one
  keeps nothing, and a reader waits out another's lease;
- refs_from_entries drops entries with nothing to fetch; a digest annotates
  the provider's record (``transcript``) for the chat surface;
- format_media_digests fences what was read and says what to do about
  what wasn't.
"""

import asyncio
import base64
import json
import logging
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from billing.exceptions import InsufficientBalanceError
from billing.markup import apply_platform_markup
from nodes.core import media_digest as md
from nodes.core.agent_events import media_entry
from nodes.core.media_resolver import ResolvedMedia
from tests.mocks.pdf_fixtures import text_pdf
from utils import scribe
from utils.content_extraction import BillingContext

TEST_USER = "00000000-0000-4000-8000-000000000001"
SCRIBE_URL = "https://openrouter.ai/api/v1/audio/transcriptions"


def _billing() -> BillingContext:
    return BillingContext(user_id=TEST_USER, organization_id=None, workflow_id="w1", node_id="n1")


def _scribe_usd(seconds: float) -> float:
    """What OpenRouter bills for ``seconds`` of audio on Scribe v2: $0.22 an hour."""
    return float(scribe.USD_PER_HOUR * Decimal(str(seconds)) / 3600)


class _Scribe:
    """OpenRouter's speech-to-text with Scribe v2 behind it, as the live API answers a voice note asked for
    plain JSON: ``text`` and the seconds of audio billed at Scribe's price, or for silence no text, no
    seconds and $0; with ``status``, a refusal. Each request is kept, its audio decoded."""

    def __init__(self):
        self.text, self.seconds, self.status = "hello from the voice note", 14.0, 200
        self.asked = []
        self.calls = None  # a list to record "scribe" in, beside the gate's "gate"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.asked.append({**body, "input_audio": {**body["input_audio"],
                                                   "data": base64.b64decode(body["input_audio"]["data"])},
                           "auth": request.headers["authorization"]})
        if self.calls is not None:
            self.calls.append("scribe")
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": self.status, "message": "Malformed audio"}})
        usage = {"seconds": self.seconds, "cost": _scribe_usd(self.seconds)} if self.text else {"cost": 0}
        return httpx.Response(200, json={"text": self.text, "usage": usage})


@pytest.fixture
def scribe_api(monkeypatch):
    """Scribe on OpenRouter faked at its HTTP boundary, behind the real request; the instance's key is set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    fake = _Scribe()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SCRIBE_URL).mock(side_effect=fake)
        yield fake


def _response(text="At 0:02, the sign reads Main Street.", cost=0.0012, tokens=80):
    """A video model's chat-completions answer, as litellm returns it."""
    usage = SimpleNamespace(cost=cost, total_tokens=tokens) if cost is not None else SimpleNamespace(total_tokens=tokens)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=usage,
        _hidden_params={},
    )


def _tracker():
    tracker = MagicMock()
    tracker.enforce_credit_gate = AsyncMock()
    # None: the charge was priced for its payer and submitted, as the tracker answers.
    tracker.track_usage_event = AsyncMock(return_value=None)
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
        ("audio/webm; codecs=opus", "clip.webm", "webm"),
        ("audio/x-caf", None, "caf"),
        ("application/octet-stream", "Audio Message.caf", "caf"),
        ("audio/amr", None, "amr"),
        ("audio/3gpp", "rec.3gp", "3gp"),
        ("audio/x-ms-wma", "clip.wma", None),
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


# ── transcription: the request, gate, billing, caps ──────────────────────────

def test_transcription_gates_before_the_call_and_charges_what_scribe_billed(scribe_api):
    calls = []
    tracker = _tracker()
    tracker.enforce_credit_gate.side_effect = lambda *a, **k: calls.append("gate")
    scribe_api.calls = calls

    with patch("billing.usage_tracker.usage_tracker", tracker):
        text, cost = asyncio.run(md.transcribe_audio(
            b"ogg-bytes", mime_type="audio/ogg; codecs=opus", filename="v.oga",
            billing=_billing(), duration_s=14,
        ))

    assert calls == ["gate", "scribe"]
    assert text == "hello from the voice note"
    # One request to Scribe v2 on the instance's key: the audio as it came, plain JSON back, no audio events.
    assert scribe_api.asked == [{
        "model": "elevenlabs/scribe-v2", "input_audio": {"data": b"ogg-bytes", "format": "ogg"},
        "provider": {"options": {"elevenlabs": {"tag_audio_events": False}}}, "auth": "Bearer or-test"}]
    tracker.enforce_credit_gate.assert_awaited_once()
    assert tracker.enforce_credit_gate.await_args.kwargs["surface"] == "media_transcription"
    tracker.track_usage_event.assert_awaited_once()
    event = tracker.track_usage_event.await_args.args[0]
    vendor = Decimal(str(_scribe_usd(14.0)))   # Scribe's price for the 14 seconds OpenRouter billed
    assert event.user_id == TEST_USER          # raw runner — Owner Pays resolves the pool
    assert event.usage_type == "api_usage"
    assert event.usage_subtype == "extraction/ai_transcription"
    assert event.cost_usd == vendor
    assert event.total_cost == cost == apply_platform_markup(vendor, user_resource=False, model=scribe.MODEL)
    assert event.unit_type == "requests" and event.quantity == 1
    assert {k: event.metadata[k] for k in ("model", "format", "audio_s", "duration_s", "size_bytes")} == {
        "model": "elevenlabs/scribe-v2", "format": "ogg", "audio_s": 14.0, "duration_s": 14, "size_bytes": 9}


def test_the_cost_charged_is_what_the_tracker_charged_the_payer(scribe_api):
    """A payer billed at cost (cloud/billing/plans.price) pays Scribe's price, not the old plans' markup."""
    tracker = _tracker()

    async def at_cost(event, **_):
        event.total_cost = event.cost_usd

    tracker.track_usage_event.side_effect = at_cost
    with patch("billing.usage_tracker.usage_tracker", tracker):
        _, cost = asyncio.run(md.transcribe_audio(b"x", mime_type="audio/mpeg", filename="a.mp3", billing=_billing()))
    assert cost == Decimal(str(_scribe_usd(14.0)))


def test_gate_raise_means_zero_spend(scribe_api):
    tracker = _tracker()
    tracker.enforce_credit_gate.side_effect = InsufficientBalanceError("Insufficient credits: 0 < 1 required")
    with patch("billing.usage_tracker.usage_tracker", tracker):
        with pytest.raises(InsufficientBalanceError):
            asyncio.run(md.transcribe_audio(
                b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()
            ))
    assert scribe_api.asked == []
    tracker.track_usage_event.assert_not_awaited()


@pytest.mark.parametrize(
    "mime, filename, fmt",
    [
        ("audio/ogg; codecs=opus", "voice.ogg", "ogg"),            # WhatsApp, Telegram, Discord
        ("audio/webm;codecs=opus", "Voice clip.webm", "webm"),     # a browser's recording
        ("audio/x-caf", "Audio Message.caf", "caf"),               # an iPhone's voice message over iMessage
        ("application/octet-stream", "45NLhReg_Audio_Message.caf", "caf"),
        ("audio/amr", "rec.amr", "amr"),
        ("audio/3gpp", "rec.3gp", "3gp"),
        ("audio/mp4", "memo.m4a", "m4a"),
        ("audio/mpeg", "Voice clip.mp3", "mp3"),                    # a channel's clip as stored
    ],
)
def test_every_container_the_channels_deliver_is_sent_as_it_came(scribe_api, mime, filename, fmt):
    """Scribe reads the container from the audio itself, so nothing is converted first."""
    audio = f"{fmt} audio bytes".encode()
    with patch("billing.usage_tracker.usage_tracker", _tracker()):
        text, _ = asyncio.run(md.transcribe_audio(audio, mime_type=mime, filename=filename, billing=_billing()))
    assert text == "hello from the voice note"
    assert [a["input_audio"] for a in scribe_api.asked] == [{"data": audio, "format": fmt}]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (dict(data=b"x", mime_type="audio/x-ms-wma", filename="clip.wma"), "not supported"),
        (dict(data=b"x" * (md.MAX_TRANSCRIBE_BYTES + 1), mime_type="audio/ogg", filename="v.oga"), "capped"),
        (dict(data=b"x", mime_type="audio/ogg", filename="v.oga", duration_s=md.MAX_TRANSCRIBE_SECONDS + 1), "minutes"),
    ],
)
def test_caps_refuse_before_any_spend(scribe_api, kwargs, match):
    tracker = _tracker()
    with patch("billing.usage_tracker.usage_tracker", tracker):
        with pytest.raises(md.DigestError, match=match):
            asyncio.run(md.transcribe_audio(billing=_billing(), **kwargs))
    tracker.enforce_credit_gate.assert_not_awaited()
    assert scribe_api.asked == []


def test_no_speech_is_a_refusal_not_a_transcript(scribe_api):
    tracker = _tracker()
    scribe_api.text = ""
    with patch("billing.usage_tracker.usage_tracker", tracker):
        with pytest.raises(md.DigestError, match="no speech"):
            asyncio.run(md.transcribe_audio(b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()))
    tracker.track_usage_event.assert_awaited_once()  # the call happened and is recorded, at the $0 it cost
    assert tracker.track_usage_event.await_args.args[0].cost_usd == 0


@pytest.mark.parametrize("status", [400, 402, 502])
def test_a_refused_call_is_a_note_never_a_charge_and_never_sent_twice(scribe_api, status):
    tracker = _tracker()
    scribe_api.status = status
    with patch("billing.usage_tracker.usage_tracker", tracker):
        with pytest.raises(md.DigestError, match=f"^transcription failed: HTTP {status}$"):
            asyncio.run(md.transcribe_audio(b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()))
    assert len(scribe_api.asked) == 1
    tracker.track_usage_event.assert_not_awaited()


def test_an_unreachable_api_is_a_note(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    tracker = _tracker()
    with respx.mock() as mock, patch("billing.usage_tracker.usage_tracker", tracker):
        mock.post(SCRIBE_URL).mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(md.DigestError, match=r"^transcription failed: no answer from OpenRouter \(ConnectError\)$"):
            asyncio.run(md.transcribe_audio(b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()))
    tracker.track_usage_event.assert_not_awaited()


def test_an_instance_without_an_openrouter_key_says_so_before_the_gate(scribe_api, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    tracker = _tracker()
    with patch("billing.usage_tracker.usage_tracker", tracker):
        with pytest.raises(md.DigestError, match="no OpenRouter key"):
            asyncio.run(md.transcribe_audio(b"x", mime_type="audio/ogg", filename="v.oga", billing=_billing()))
    tracker.enforce_credit_gate.assert_not_awaited()
    assert scribe_api.asked == []


# ── video: bounded, and charged the model's reported cost ───────────────────

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
        event = tracker.track_usage_event.await_args.args[0]
        assert event.usage_subtype == "extraction/ai_video_digest"
        assert event.total_cost == apply_platform_markup(Decimal("0.0012"), user_resource=False, model="x")
        assert event.metadata["cost_reported"] is True and event.metadata["tokens"] == 80
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


def _describe_video(response, tracker):
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("litellm.acompletion", new=AsyncMock(return_value=response)), \
         patch("utils.video_probe.video_duration", new=AsyncMock(return_value=10.0)):
        return asyncio.run(md.digester_for("video")(
            md.MediaRef(kind="video", mime_type="video/mp4"), b"video", md.DigestContext(billing=_billing())))


def test_an_unreported_cost_is_charged_from_openrouters_record():
    tracker = _tracker()
    response = _response(cost=None)
    response.id = "gen-clip"
    lookup = AsyncMock(return_value=Decimal("0.0031"))
    with patch("utils.openrouter_cost.generation_cost", new=lookup):
        digest = _describe_video(response, tracker)
    lookup.assert_awaited_once_with("gen-clip")
    event = tracker.track_usage_event.await_args.args[0]
    assert event.cost_usd == Decimal("0.0031") and event.metadata["cost_reported"] is False
    assert digest.text and digest.cost_charged == event.total_cost == apply_platform_markup(
        Decimal("0.0031"), False, event.metadata["model"])


def test_a_cost_priced_nowhere_is_logged_never_charged_as_zero(caplog):
    from utils.openrouter_cost import CostUnknown

    tracker = _tracker()
    with patch("utils.openrouter_cost.generation_cost", new=AsyncMock(side_effect=CostUnknown("none"))), \
         caplog.at_level(logging.CRITICAL):
        digest = _describe_video(_response(cost=None), tracker)
    assert digest.text and digest.cost_charged is None
    tracker.track_usage_event.assert_not_awaited()
    assert "not billed" in caplog.text


# ── digest_media: never raises, gates AI, annotates ─────────────────────────

def _resolver(data=b"ogg-bytes", mime="audio/ogg"):
    return AsyncMock(return_value=ResolvedMedia(data=data, mime_type=mime, filename="f"))


def test_digest_media_transcribes_and_annotates_the_record(scribe_api):
    tracker = _tracker()
    scribe_api.text = "call me back"
    record = {"url": "https://assets.example/v.oga", "rehosted": True}
    ref = _voice_ref(record=record)
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()) as resolver:
        (digest,) = asyncio.run(md.digest_media([ref], md.DigestContext(billing=_billing(), workflow_id="w1")))
    assert digest.method == "transcription" and digest.text == "call me back"
    assert digest.cost_charged == tracker.track_usage_event.await_args.args[0].total_cost
    assert record["transcript"] == "call me back"
    resolver.assert_awaited_once()
    assert resolver.await_args.args[0] == ref.url
    assert [a["input_audio"] for a in scribe_api.asked] == [{"data": b"ogg-bytes", "format": "ogg"}]


def test_digest_media_prefers_the_resource_id_over_the_public_url(scribe_api):
    tracker = _tracker()
    ref = _voice_ref(resource_id="00000000-0000-4000-8000-0000000000aa")
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()) as resolver:
        asyncio.run(md.digest_media([ref], md.DigestContext(billing=_billing(), workflow_id="w1")))
    assert resolver.await_args.args[0] == ref.resource_id
    assert resolver.await_args.kwargs["workflow_id"] == "w1"


def test_digest_media_refuses_ai_without_billing_or_when_disabled(scribe_api):
    with patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        (off,) = asyncio.run(md.digest_media([_voice_ref()], md.DigestContext(billing=_billing(), allow_ai=False)))
        (unpaid,) = asyncio.run(md.digest_media([_voice_ref()], md.DigestContext(billing=None)))
    assert off.text is None and "turned off" in off.error
    assert unpaid.text is None and "billing" in unpaid.error
    assert scribe_api.asked == []


def test_digest_media_caps_ai_digests_per_turn(scribe_api):
    tracker = _tracker()
    refs = [_voice_ref(url=f"https://a/{i}.oga") for i in range(md.MAX_AI_DIGESTS_PER_TURN + 2)]
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        digests = asyncio.run(md.digest_media(refs, md.DigestContext(billing=_billing())))
    assert sum(1 for d in digests if d.text) == md.MAX_AI_DIGESTS_PER_TURN
    assert all("at most" in d.error for d in digests if not d.text)
    assert len(scribe_api.asked) == tracker.track_usage_event.await_count == md.MAX_AI_DIGESTS_PER_TURN


def test_digest_media_turns_failures_into_notes_never_raises(scribe_api, caplog):
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


def test_digest_media_reads_a_bounded_number_of_documents_per_turn():
    """A message may carry many files; a turn reads only so many documents' text into itself, and says so of the
    rest, as it does past the audio and video cap."""
    docs = [md.MediaRef(kind="document", mime_type="application/pdf", url=f"https://a/{i}.pdf", filename=f"{i}.pdf",
                        record={}) for i in range(md.MAX_DOCUMENT_DIGESTS_PER_TURN + 2)]
    resolver = _resolver(text_pdf(), "application/pdf")
    with patch("nodes.core.media_resolver.resolve_media_input", resolver):
        digests = asyncio.run(md.digest_media(docs, md.DigestContext(billing=None)))
    assert sum(1 for d in digests if d.text) == md.MAX_DOCUMENT_DIGESTS_PER_TURN
    assert [d.error for d in digests[md.MAX_DOCUMENT_DIGESTS_PER_TURN:]] == [
        f"at most {md.MAX_DOCUMENT_DIGESTS_PER_TURN} documents are read per message"] * 2
    assert resolver.await_count == md.MAX_DOCUMENT_DIGESTS_PER_TURN  # the rest are never fetched


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


class _Readings:
    """``readings`` in memory: what ``take`` answers, and what was kept."""

    def __init__(self, *states):
        self.states = list(states)
        self.kept = []

    async def take(self, resource_id, *, lease_s):
        return self.states.pop(0)

    async def keep(self, resource_id, reading):
        self.kept.append((resource_id, reading))


RID = "00000000-0000-4000-8000-0000000000aa"


def test_a_kept_reading_is_reused_without_a_fetch_a_charge_or_the_ai_cap():
    tracker = _tracker()
    kept = {"extracted_text": "call me back", "extraction_method": "transcription"}
    readings = _Readings(*[("read", kept)] * (md.MAX_AI_DIGESTS_PER_TURN + 1))
    refs = [_voice_ref(resource_id=RID) for _ in range(md.MAX_AI_DIGESTS_PER_TURN + 1)]
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()) as resolver:
        digests = asyncio.run(md.digest_media(refs, md.DigestContext(billing=_billing(), readings=readings)))
    assert [d.text for d in digests] == ["call me back"] * len(refs) and all(d.kept for d in digests)
    resolver.assert_not_awaited()
    tracker.enforce_credit_gate.assert_not_awaited()
    tracker.track_usage_event.assert_not_awaited()
    assert readings.kept == []


def test_a_kept_document_is_clipped_to_the_turns_budget():
    readings = _Readings(("read", {"extracted_text": "x" * 50, "extraction_method": "pdf"}))
    ref = md.MediaRef(kind="document", mime_type="application/pdf", filename="q.pdf", resource_id=RID)
    (digest,) = asyncio.run(md.digest_media([ref], md.DigestContext(billing=_billing(), readings=readings, char_budget=20)))
    assert (digest.text, digest.method, digest.truncated) == ("x" * 20, "pdf", True)


def test_a_first_read_is_kept_and_a_failed_one_keeps_nothing(scribe_api):
    tracker = _tracker()
    scribe_api.text = "call me back"
    readings = _Readings(("claimed", None), ("claimed", None))
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        (read,) = asyncio.run(md.digest_media([_voice_ref(resource_id=RID)], md.DigestContext(billing=_billing(), readings=readings)))
        tracker.enforce_credit_gate.side_effect = InsufficientBalanceError("Insufficient credits: 0 < 1 required")
        (refused,) = asyncio.run(md.digest_media([_voice_ref(resource_id=RID)], md.DigestContext(billing=_billing(), readings=readings)))
    assert read.text == "call me back" and not read.kept and refused.error
    assert readings.kept == [
        (RID, {"extracted_text": "call me back", "extraction_method": "transcription", "extraction_truncated": False}),
        (RID, None),  # nothing to keep: the lease ends, and the next reader tries for itself
    ]


def test_a_reader_waits_out_another_readers_lease(monkeypatch):
    monkeypatch.setattr(md, "READING_POLL_S", 0)
    kept = {"extracted_text": "call me back", "extraction_method": "transcription"}
    readings = _Readings(("busy", None), ("busy", None), ("read", kept))
    with patch("nodes.core.media_resolver.resolve_media_input", _resolver()) as resolver:
        (digest,) = asyncio.run(md.digest_media([_voice_ref(resource_id=RID)], md.DigestContext(billing=_billing(), readings=readings)))
    assert digest.kept and digest.text == "call me back"
    resolver.assert_not_awaited()


def test_a_file_it_cant_keep_a_reading_on_is_read_as_before(scribe_api):
    tracker = _tracker()
    scribe_api.text = "call me back"
    readings = _Readings(("absent", None))
    with patch("billing.usage_tracker.usage_tracker", tracker), \
         patch("nodes.core.media_resolver.resolve_media_input", _resolver()):
        (digest,) = asyncio.run(md.digest_media([_voice_ref(resource_id=RID)], md.DigestContext(billing=_billing(), readings=readings)))
    assert digest.text == "call me back" and readings.kept == []
    tracker.track_usage_event.assert_awaited_once()


def test_rehearsal_note_names_audio_only():
    refs = [_voice_ref(), md.MediaRef(kind="image", mime_type="image/png", url="https://a/p.png")]
    note = md.rehearsal_media_note(refs)
    assert "Voice message (0:14): not transcribed in a Test Run" in note
    assert "Image" not in note
    assert md.rehearsal_media_note([refs[1]]) == ""
