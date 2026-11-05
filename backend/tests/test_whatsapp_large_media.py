"""Inbound WhatsApp media past what a delivery can carry.

A phone's HD video runs well past the old 25MB cap, and an agent told nothing but
a link it couldn't open reported that the video "didn't come through". Media up
to the cap is copied; past it, or when the copy fails, the message still runs, the
private provider URL is gone, and the agent is told why.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.whatsapp_node import WhatsAppNode
from tests.test_resource_store_stream import _Store
from tests.test_whatsapp_media_rehost import WA_CFG, _FakeClient, _FakeStreamResponse, _media_payload, _pool
from utils.inbound_media import rehost_inbound_media

MB = 1024 * 1024
CAP = WhatsAppNode.MEDIA_REHOST_MAX_BYTES


class _Response(_FakeStreamResponse):
    def __init__(self, chunks, headers=None, status=200):
        super().__init__(chunks)
        self.headers = {**self.headers, **(headers or {})}
        self.status = status
        self.read_any = False

    def raise_for_status(self):
        if self.status >= 400:
            request = httpx.Request("GET", "https://api.wahooks.com/secret-path")
            raise httpx.HTTPStatusError(
                f"Client error for url '{request.url}'", request=request,
                response=httpx.Response(self.status, request=request),
            )

    async def aiter_bytes(self):
        self.read_any = True
        async for chunk in super().aiter_bytes():
            yield chunk


class _Client(_FakeClient):
    """Answers with ``response``, by default a ``_Response`` of ``chunks``."""

    def __init__(self, chunks=(), response=None, **response_args):
        super().__init__(chunks)
        self.response = response or _Response(chunks, **response_args)

    def stream(self, method, url, headers=None):
        self.requests.append((method, url, headers))
        return self.response


def _chunks_of(size: int, chunk: bytes = bytes(MB)):
    whole, rest = divmod(size, len(chunk))
    return [chunk] * whole + ([chunk[:rest]] if rest else [])


def _video_payload(**video_message):
    payload = _media_payload(url="https://api.wahooks.com/api/connections/c1/media/clip.mp4",
                             mimetype="video/mp4", filename="clip.mp4")
    payload["payload"]["_data"] = {"message": {"videoMessage": {"seconds": 18, **video_message}}}
    return payload


@pytest.fixture(autouse=True)
def wahooks_key(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "platform-key")


async def _deliver(client, payload, pool=None):
    with patch("utils.inbound_media.guarded_async_client", client):
        return await WhatsAppNode.transform_trigger_payload(
            payload, WA_CFG, pool=pool or _pool(), workflow_id="wf-1", node_id="wa-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [26 * MB, 43 * MB + 7, CAP])
async def test_media_up_to_the_cap_is_copied(monkeypatch, size):
    store = _Store(monkeypatch)

    out = await _deliver(_Client(chunks=_chunks_of(size)), _video_payload(fileLength=str(size)))

    media = out["payload"]["media"]
    assert media["rehosted"] is True and media["size"] == size
    assert media["url"].startswith("https://assets.test/") and media["url"].endswith("/clip.mp4")
    assert store.acked == size
    assert len(store.completed) == 1 and not store.aborted
    assert store.row.await_args.args[9] == size  # the row records what was written
    # The run's turn hands the agent the copy, and the digest its record.
    event = WhatsAppNode.resolve_agent_event(out)
    assert media["url"] in event["text"] and event["media"][0]["size_bytes"] == size


@pytest.mark.asyncio
async def test_a_declared_size_over_the_cap_downloads_nothing():
    client = _Client(chunks=[b"x"])
    pool = _pool()
    size = 150 * MB

    out = await _deliver(client, _video_payload(fileLength=str(size)), pool)

    assert client.requests == []  # no GET at all
    pool.fetchrow.assert_not_awaited()
    assert out["payload"]["media"] == {"mimetype": "video/mp4", "filename": "clip.mp4", "too_large": True,
                                       "size": size, "max_bytes": CAP}


@pytest.mark.asyncio
async def test_a_response_length_over_the_cap_stops_before_the_body(monkeypatch):
    store = _Store(monkeypatch)
    client = _Client(chunks=[b"x"], headers={"content-length": str(CAP + 1)})

    out = await _deliver(client, _video_payload())

    assert client.response.read_any is False and store.parts == []
    assert out["payload"]["media"]["too_large"] is True and out["payload"]["media"]["size"] == CAP + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [{}, {"fileLength": str(10 * MB)}], ids=["absent", "wrong"])
async def test_a_body_over_the_cap_is_stopped_midstream_whatever_was_declared(monkeypatch, declared):
    store = _Store(monkeypatch)
    pulled = []

    class _Endless(_Response):
        async def aiter_bytes(self):
            while True:
                pulled.append(MB)
                yield bytes(MB)

    out = await _deliver(_Client(response=_Endless([])), _video_payload(**declared))

    assert sum(pulled) == CAP + MB  # one chunk past the cap, then no further
    media = out["payload"]["media"]
    assert media["too_large"] is True and media["size"] is None and "url" not in media
    assert await store.dropped() and not store.completed
    store.row.assert_not_awaited()


@pytest.mark.parametrize(
    "message, expected",
    [
        ({"videoMessage": {"fileLength": "45000000"}}, 45000000),
        ({"documentMessage": {"fileLength": 900}}, 900),
        ({"documentWithCaptionMessage": {"message": {"documentMessage": {"fileLength": "7"}}}}, 7),
        ({"ephemeralMessage": {"message": {"imageMessage": {"fileLength": {"low": 5, "high": 1}}}}}, 2**32 + 5),
        ({"videoMessage": {"fileLength": {"low": -1, "high": 0, "unsigned": True}}}, 2**32 - 1),
        ({"messageContextInfo": {}, "conversation": "hi"}, None),
        ({"videoMessage": {"fileLength": "soon"}}, None),
        # A small photo quoting a huge video: the quoted size is not this message's.
        ({"imageMessage": {"contextInfo": {"quotedMessage": {"videoMessage": {"fileLength": "999999999"}}}}}, None),
    ],
)
def test_declared_size_shapes(message, expected):
    assert WhatsAppNode._declared_media_size(message) == expected


@pytest.mark.asyncio
async def test_a_dead_link_is_explicit_and_never_logged(caplog):
    with caplog.at_level(logging.WARNING):
        out = await _deliver(_Client(status=404), _video_payload())

    media = out["payload"]["media"]
    assert media["unavailable"] is True and "url" not in media
    assert "wahooks" not in caplog.text and "secret-path" not in caplog.text
    assert "HTTP 404" in caplog.text
    event = WhatsAppNode.resolve_agent_event(out)
    assert "could not be retrieved" in event["text"] and "wahooks" not in event["text"]
    assert event["media"] == []


@pytest.mark.asyncio
async def test_a_copy_past_its_deadline_lets_the_message_run(monkeypatch):
    store = _Store(monkeypatch)
    monkeypatch.setattr(WhatsAppNode, "MEDIA_REHOST_TIMEOUT_S", 0.05)

    class _Trickle(_Response):
        async def aiter_bytes(self):
            yield bytes(9 * MB)  # past one part, so an upload is open when it stalls
            await asyncio.sleep(60)

    out = await asyncio.wait_for(_deliver(_Client(response=_Trickle([])), _video_payload()), timeout=5)

    media = out["payload"]["media"]
    assert media["unavailable"] is True and "url" not in media
    assert await store.dropped() and not store.completed
    assert "look at this" in WhatsAppNode.resolve_agent_event(out)["text"]


def test_the_copy_fits_inside_the_providers_delivery_timeout():
    # WAHooks aborts a delivery at 15s and retries it: past that, one message runs twice.
    assert WhatsAppNode.MEDIA_REHOST_TIMEOUT_S < 15


@pytest.mark.asyncio
async def test_other_channels_still_get_none_over_their_cap():
    store = AsyncMock()
    with patch("utils.inbound_media.guarded_async_client", _Client(chunks=[b"x" * 11])), \
         patch("utils.resource_store.create_resource_from_bytes", store):
        out = await rehost_inbound_media(
            _pool(), workflow_id="wf-1", node_id="n", url="https://files.example/f", source="other", max_bytes=10,
        )
    assert out is None
    store.assert_not_awaited()


def test_agent_event_says_too_large_with_the_size_and_the_limit():
    payload = _video_payload()
    payload["payload"]["body"] = None
    payload["payload"]["media"] = {"mimetype": "video/mp4", "filename": "clip.mp4", "too_large": True,
                                   "size": 143 * MB, "max_bytes": 100 * MB}
    event = WhatsAppNode.resolve_agent_event(payload)
    assert "[video]" in event["text"]  # the message still reads, caption or not
    assert "too large" in event["text"] and "143 MB" in event["text"] and "100 MB" in event["text"]
    assert "smaller version" in event["text"] and "clip.mp4" in event["text"]
    assert "could not be retrieved" not in event["text"]
    assert event["media"] == [] and event["conversation_key"] == "123@c.us"


def test_agent_event_too_large_without_a_known_size_gives_the_limit():
    payload = _video_payload()
    payload["payload"]["media"] = {"mimetype": "video/mp4", "too_large": True, "size": None, "max_bytes": 100 * MB}
    text = WhatsAppNode.resolve_agent_event(payload)["text"]
    assert "too large to use (the limit is 100 MB)" in text
    assert "look at this" in text  # the caption survives
