"""A text to the assistant's WhatsApp number (coder/coordinator/texting/whatsapp.py): verified, parsed, answered in
WhatsApp's own markup; the Cloud API client against a scripted Graph API; and the owner's message, which WhatsApp only
delivers inside the 24-hour window."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coder.coordinator.texting import channel, routes, whatsapp
from coder.coordinator.texting.channel import Embed, chunk
from coder.coordinator.texting.whatsapp import InboundMessage, parse_failed, parse_inbound, to_whatsapp_text, verify_signature
from nodes.core.media_resolver import FileInfo
from utils import capabilities
from utils.whatsapp_cloud_api import GRAPH_BASE, CloudApi, WhatsAppSendError, template_param

OUR_NUMBER = "100000000000001"
SECRET = "app-secret"
SENDER = "+14155550100"
MESSAGES_URL = f"{GRAPH_BASE}/123/messages"


def _delivery(*messages, phone_number_id=OUR_NUMBER, field="messages", statuses=()):
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [{"field": field, "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550100000", "phone_number_id": phone_number_id},
        "contacts": [{"profile": {"name": "Ada"}, "wa_id": "14155550100"}],
        "messages": list(messages), "statuses": list(statuses),
    }}]}]}


def _text(body, wamid="wamid.1", sender="14155550100"):
    return {"from": sender, "id": wamid, "timestamp": "1", "type": "text", "text": {"body": body}}


def _signed(body: bytes) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()}


def test_signature_is_the_app_secret_over_the_raw_body():
    body = b'{"a": 1}'
    assert verify_signature(SECRET, body, _signed(body)["X-Hub-Signature-256"])
    assert not verify_signature(SECRET, body + b" ", _signed(body)["X-Hub-Signature-256"])
    assert not verify_signature(SECRET, body, None)
    assert not verify_signature(SECRET, body, "md5=abc")
    assert not verify_signature("", body, _signed(body)["X-Hub-Signature-256"])


def test_parse_keeps_our_messages_and_names_the_rest():
    payload = _delivery(
        _text("hi"),
        {"from": "14155550100", "id": "wamid.2", "type": "sticker", "sticker": {"id": "x"}},
        {"from": "14155550100", "id": "wamid.3", "type": "button", "button": {"text": "Yes"}},
        {"from": "14155550100", "id": "wamid.4", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "b", "title": "Approve"}}},
        {"from": "14155550100", "type": "text", "text": {"body": "no id"}},
    )
    got = parse_inbound(payload, phone_number_id=OUR_NUMBER)
    assert [(m.wamid, m.kind, m.text, m.type) for m in got] == [
        ("wamid.1", "text", "hi", "text"), ("wamid.2", "sticker", "", "sticker"),
        ("wamid.3", "text", "Yes", "button"), ("wamid.4", "text", "Approve", "interactive"),
    ]
    assert got[0].sender == SENDER and got[0].sender_name == "Ada"
    # Meta's own message object rides along for a platform's rule (an ad's referral, say).
    assert got[0].raw == _text("hi")
    assert parse_inbound(_delivery(_text("hi"), phone_number_id="other"), phone_number_id=OUR_NUMBER) == []
    assert parse_inbound(_delivery(_text("hi"), field="message_template_status_update"), phone_number_id=OUR_NUMBER) == []
    assert parse_inbound(_delivery(statuses=[{"id": "wamid.9", "status": "read"}]), phone_number_id=OUR_NUMBER) == []


def test_parse_carries_media_with_its_caption():
    payload = _delivery(
        {"from": "14155550100", "id": "wamid.a", "type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg; codecs=opus", "voice": True}},
        {"from": "14155550100", "id": "wamid.d", "type": "document", "document": {"id": "m2", "mime_type": "application/pdf", "filename": "plan.pdf", "caption": "see p2"}},
        {"from": "14155550100", "id": "wamid.i", "type": "image", "image": {"id": "m3", "mime_type": "image/jpeg", "caption": "what is this"}},
        {"from": "14155550100", "id": "wamid.v", "type": "video", "video": {"id": "m4", "mime_type": "video/mp4"}},
        {"from": "14155550100", "id": "wamid.x", "type": "audio", "audio": {}},
    )
    got = {m.wamid: m for m in parse_inbound(payload, phone_number_id=OUR_NUMBER)}
    assert (got["wamid.a"].kind, got["wamid.a"].media_id, got["wamid.a"].voice, got["wamid.a"].text) == ("audio", "m1", True, "")
    assert (got["wamid.d"].kind, got["wamid.d"].filename, got["wamid.d"].text) == ("document", "plan.pdf", "see p2")
    assert (got["wamid.i"].kind, got["wamid.i"].text) == ("image", "what is this")
    assert (got["wamid.v"].kind, got["wamid.v"].text) == ("video", "")
    assert got["wamid.x"].kind == "unsupported"  # media without an id cannot be fetched


def test_a_shared_contact_or_location_is_its_data_framed_by_the_prompt_pack():
    contact = {"name": {"formatted_name": "Alex"}, "phones": [{"phone": "+14155550999", "type": "WORK"}]}
    message, = parse_inbound(_delivery({"from": "14155550100", "id": "c", "type": "contacts", "contacts": [contact]}),
                             phone_number_id=OUR_NUMBER)
    assert message.kind == "contacts"
    assert message.text == whatsapp.PROMPTS.shared_item("contacts", json.dumps([contact]))
    assert json.loads(message.text.split("\n", 1)[1]) == [contact]
    huge = {"latitude": 0, "longitude": 0, "name": "x" * 20000}
    cut, = parse_inbound(_delivery({"from": "14155550100", "id": "l", "type": "location", "location": huge}),
                         phone_number_id=OUR_NUMBER)
    assert cut.text.endswith(whatsapp.PROMPTS.SHARED_ITEM_CUT)
    assert len(cut.text) == whatsapp.SHARED_ITEM_LIMIT + len(whatsapp.PROMPTS.SHARED_ITEM_CUT)


def test_only_failed_statuses_from_our_number_are_failures():
    def status(state, wamid, **extra):
        return {"id": wamid, "status": state, "recipient_id": "14155550100", **extra}

    payload = _delivery(statuses=[status("sent", "a"), status("delivered", "b"),
                                  status("failed", "wamid.gone", errors=[{"code": 131026, "title": "Message undeliverable"}])])
    assert parse_failed(payload, phone_number_id=OUR_NUMBER) == [
        ("wamid.gone", "WhatsApp failed it after sending: (131026) Message undeliverable")]
    assert parse_failed(payload, phone_number_id="another") == []


def test_whatsapp_markup_and_chunking():
    md = "## Your workflows\n\n- **Support bot** — running\n* Lead alerts\n\nSee [the dashboard](https://example.com/dashboard).\n\n\n\n```python\nx = 1\n```"
    assert to_whatsapp_text(md) == "Your workflows\n\n• *Support bot* — running\n• Lead alerts\n\nSee the dashboard: https://example.com/dashboard.\n\n```\nx = 1\n```"
    assert to_whatsapp_text("2 * 3 = 6 and a_b_c") == "2 * 3 = 6 and a_b_c"
    parts = chunk("line one\n" * 5 + "x" * 30, limit=40)
    assert all(len(p) <= 40 for p in parts) and "".join(p.replace("\n", "") for p in parts).replace(" ", "") == ("lineone" * 5 + "x" * 30)
    assert chunk("short") == ["short"] and chunk("") == []


@pytest.fixture
def files(monkeypatch):
    """What each embedded URL holds, as the stored file's record or its server would say (``describe_url``)."""
    known = {}

    async def describe(url):
        return known.get(url)

    monkeypatch.setattr(channel, "describe_url", describe)
    return known


@pytest.mark.asyncio
async def test_rich_reply_sends_every_chunk_and_attachment(files):
    files["https://assets.example/x.png"] = FileInfo("image/png", "x.png", 2_000)
    api = MagicMock(send_text=AsyncMock(return_value="first"), send_media=AsyncMock(return_value="media"))
    result = await whatsapp.send_rich(api, SENDER, "x" * 4100 + "\n![photo](https://assets.example/x.png)")
    assert result == "first" and api.send_text.await_count == 2
    api.send_media.assert_awaited_once_with(SENDER, "image", link="https://assets.example/x.png", caption="photo",
                                            filename="x.png")


MB = 1024 * 1024


@pytest.mark.parametrize("mime, size, sent_as", [
    ("image/jpeg", 2 * MB, "image"), ("image/png", 5 * MB, "image"), ("image/jpg", 1 * MB, "image"),
    ("video/mp4", 10 * MB, "video"), ("video/3gpp", 1 * MB, "video"),
    ("audio/mpeg", 3 * MB, "audio"), ("audio/ogg", 1 * MB, "audio"), ("audio/x-m4a", 1 * MB, "audio"),
    ("image/png", None, "image"),  # a size nothing reported is no bar
    # Meta's documents: PDF, plain text and Office files, by link up to 100 MB.
    ("application/pdf", 1 * MB, "document"), ("text/plain", 40_000, "document"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", 1 * MB, "document"),
    ("application/vnd.ms-excel", 1 * MB, "document"), ("application/pdf", 100 * MB, "document"),
    # Another text file goes up as plain text under its own name: Meta refuses an HTML page's own type.
    ("text/html", 40_000, whatsapp.TEXT), ("text/csv", 1 * MB, whatsapp.TEXT), ("text/markdown", 2000, whatsapp.TEXT),
    ("application/json", 2000, whatsapp.TEXT),
    # Meta takes no file of these types or sizes: a link.
    ("application/zip", 30 * MB, None), ("image/webp", 1 * MB, None), ("image/gif", 1 * MB, None),
    ("image/heic", 1 * MB, None), ("video/quicktime", 1 * MB, None), ("audio/wav", 1 * MB, None),
    ("image/jpeg", 6 * MB, None), ("video/mp4", 20 * MB, None), ("audio/mpeg", 17 * MB, None),
    ("application/pdf", 101 * MB, None), ("text/html", 101 * MB, None),
])
def test_each_file_goes_in_the_form_whatsapp_takes_for_its_type_and_size(mime, size, sent_as):
    assert whatsapp.sent_as(Embed("https://f.example/x", "x", FileInfo(mime, "x", size))) == sent_as


def test_a_file_nothing_can_tell_the_type_of_is_a_link():
    assert whatsapp.sent_as(Embed("https://f.example/x", "the file", None)) is None


@pytest.mark.parametrize("mime, sent_as, page", [
    # A page NoClick stores goes as its file (its source in plain text) and, in the text, the link that saves it.
    ("text/html", whatsapp.TEXT, True), ("image/svg+xml", whatsapp.TEXT, True),
    ("application/xhtml+xml", whatsapp.TEXT, True),
    # Any other file is one or the other, as before.
    ("text/csv", whatsapp.TEXT, False), ("application/json", whatsapp.TEXT, False),
    ("application/pdf", "document", False), ("image/png", "image", False), ("application/zip", None, False),
])
def test_a_page_noclick_stores_goes_as_its_file_and_the_link_that_saves_it(mime, sent_as, page):
    embed = Embed("https://f.example/x", "x", FileInfo(mime, "x", 40_000), download="https://dl.example/x")
    assert (whatsapp.sent_as(embed), embed.page) == (sent_as, page)
    # A page nothing makes a download link for (not NoClick's, or no platform) is its file alone.
    assert not Embed("https://f.example/x", "x", FileInfo(mime, "x", 40_000)).page


OWNER, WORKFLOW = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
PAGE_KEY = f"{OWNER}/{WORKFLOW}/33333333-3333-3333-3333-333333333333/City map.html"
CSV_KEY = f"{OWNER}/{WORKFLOW}/44444444-4444-4444-4444-444444444444/scores.csv"
ZIP_KEY = f"{OWNER}/account/55555555-5555-5555-5555-555555555555/site.zip"


@pytest.fixture
def downloads(monkeypatch):
    """This instance serves its files at files.test, and its platform makes the links that save them, at dl.test."""
    monkeypatch.setattr("utils.resource_store.get_public_download_url", lambda key: "https://files.test/" + quote(key))
    monkeypatch.setitem(capabilities._providers, capabilities.FILE_DOWNLOAD_URL,
                        lambda key: "https://dl.test/files/" + quote(key))
    return lambda key: ("https://files.test/" + quote(key), "https://dl.test/files/" + quote(key))


@pytest.mark.asyncio
async def test_a_stored_page_arrives_as_its_file_and_the_link_that_saves_it(files, downloads, monkeypatch):
    """Asked for a game as an HTML file, a person couldn't open or save it as a document of plain text, then wanted
    the file itself rather than a link: a page goes as both, whichever their phone handles. A text file is a file and
    a ZIP the link that saves it, as before."""
    (page, save_page), (sheet, _), (archive, save_archive) = downloads(PAGE_KEY), downloads(CSV_KEY), downloads(ZIP_KEY)
    files[page] = FileInfo("text/html", "City map.html", 8 * MB)
    files[sheet] = FileInfo("text/csv", "scores.csv", 2_000)
    files[archive] = FileInfo("application/zip", "site.zip", 3 * MB)
    bodies = {page: b"<!doctype html><title>City</title>", sheet: b"name,score\nAda,9\n"}
    read = AsyncMock(side_effect=lambda url, max_bytes: bodies[url])
    monkeypatch.setattr(whatsapp, "read_url", read)
    api = MagicMock(send_text=AsyncMock(return_value="t"), send_media=AsyncMock(return_value="m"),
                    upload_media=AsyncMock(side_effect=["media.page", "media.sheet"]))
    await whatsapp.send_rich(api, SENDER, f"Here's the map.\n![City map]({page})\n![scores.csv]({sheet})\n"
                                          f"![The site]({archive})")
    api.send_text.assert_awaited_once_with(
        SENDER, f"Here's the map.\nCity map: {save_page}\nThe site: {save_archive}")
    # The page and the text file go up as plain text under their own names, and each is sent as a document.
    assert [call.args for call in read.await_args_list] == [(page,), (sheet,)]
    assert [(call.args, call.kwargs) for call in api.upload_media.await_args_list] == [
        ((bodies[page],), {"filename": "City map.html", "mime_type": "text/plain"}),
        ((bodies[sheet],), {"filename": "scores.csv", "mime_type": "text/plain"}),
    ]
    assert [call.kwargs for call in api.send_media.await_args_list] == [
        {"caption": "", "filename": "City map.html", "media_id": "media.page"},
        {"caption": "", "filename": "scores.csv", "media_id": "media.sheet"},
    ]


@pytest.mark.asyncio
@respx.mock
async def test_a_pdf_goes_as_a_document_by_link_and_an_html_file_as_plain_text_under_its_name(files, monkeypatch):
    pdf, page = "https://assets.example/u/w/r/Dummy%20PDF", "https://assets.example/u/w/r/game.html"
    files[pdf] = FileInfo("application/pdf", "Dummy PDF.pdf", 642)
    files[page] = FileInfo("text/html", "game.html", 30_000)
    read = AsyncMock(return_value=b"<!doctype html><title>Neon Static</title>")
    monkeypatch.setattr(whatsapp, "read_url", read)
    upload = respx.post(f"{GRAPH_BASE}/123/media").mock(return_value=httpx.Response(200, json={"id": "media.1"}))
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.d"}]}))
    await whatsapp.send_rich(_api(), SENDER, f"Here you go.\n![Dummy PDF]({pdf})\n![Neon Static, to play offline]({page})")
    read.assert_awaited_once_with(page, max_bytes=whatsapp.DOCUMENT_LIMIT)
    uploaded = upload.calls.last.request.read()
    assert b'name="file"; filename="game.html"' in uploaded and b"Content-Type: text/plain" in uploaded
    assert b"<!doctype html><title>Neon Static</title>" in uploaded and b'name="type"\r\n\r\ntext/plain' in uploaded
    text, first, second = (json.loads(call.request.read()) for call in route.calls)
    assert text["text"] == {"body": "Here you go."}
    # The caption that only repeats the file's name is left off; the file shows its name.
    assert first == {"messaging_product": "whatsapp", "to": "14155550100", "type": "document",
                     "document": {"link": pdf, "filename": "Dummy PDF.pdf"}}
    assert second["document"] == {"id": "media.1", "caption": "Neon Static, to play offline", "filename": "game.html"}


@pytest.mark.asyncio
@respx.mock
async def test_meta_refusing_a_file_or_an_unreadable_one_sends_none_of_the_message(files, monkeypatch):
    page = "https://f.example/game.html"
    files[page] = FileInfo("text/html", "game.html", 300)
    monkeypatch.setattr(whatsapp, "read_url", AsyncMock(return_value=b"<html></html>"))
    respx.post(f"{GRAPH_BASE}/123/media").mock(return_value=httpx.Response(400, json={"error": {
        "message": "(#100) Param file must be a file with one of the following types", "code": 100}}))
    sent = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "w"}]}))
    with pytest.raises(WhatsAppSendError, match="refused the file") as refused:
        await whatsapp.send_rich(_api(), SENDER, f"Here.\n![]({page})")
    assert refused.value.code == 100 and not sent.called
    monkeypatch.setattr(whatsapp, "read_url", AsyncMock(side_effect=ValueError("Could not fetch media from URL: 404")))
    with pytest.raises(WhatsAppSendError, match="couldn't read game.html"):
        await whatsapp.send_rich(_api(), SENDER, f"Here.\n![]({page})")
    assert not sent.called


@pytest.mark.asyncio
async def test_a_file_that_cant_go_as_one_is_a_link_line_with_the_text(files):
    files["https://f.example/site.zip"] = FileInfo("application/zip", "site.zip", 3 * MB)
    api = MagicMock(send_text=AsyncMock(return_value="t"), send_media=AsyncMock())
    await whatsapp.send_rich(api, SENDER, "Both are here.\n![The site's source](https://f.example/site.zip)\n"
                                          "![](https://f.example/mystery)")
    api.send_text.assert_awaited_once_with(
        SENDER, "Both are here.\nThe site's source: https://f.example/site.zip\nhttps://f.example/mystery")
    api.send_media.assert_not_awaited()


APPROVE = "https://example.com/h/0f8b3c2a-1d2e-4f5a-9b6c-7d8e9f0a1b2c?k=0123456789abcdef0123456789abcdef"


@pytest.mark.asyncio
async def test_a_link_texted_to_the_owner_is_a_line_of_its_own():
    """A message with its one-tap link (``with_link``) puts the link on a line of its own: on a phone it is the one
    thing to tap."""
    from coder.coordinator.reach import with_link

    api = MagicMock(send_text=AsyncMock(return_value="wamid.1"))
    await whatsapp.send_rich(api, SENDER, with_link("The build wants to buy +1 555 010 0199. Approve it?", APPROVE))
    assert api.send_text.await_args.args[1].split("\n") == ["The build wants to buy +1 555 010 0199. Approve it?", APPROVE]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WHATSAPP_CLOUD_API_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", OUR_NUMBER)
    spawned = []

    def fake_spawn(coro, **kw):
        if "message" in coro.cr_frame.f_locals:
            spawned.append(coro.cr_frame.f_locals["message"])
        coro.close()

    monkeypatch.setattr(routes, "spawn", fake_spawn)
    # Statuses are ignored here unless a test gives the platform's handling.
    monkeypatch.delitem(capabilities._providers, capabilities.WHATSAPP_STATUSES, raising=False)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as c:
        c.spawned = spawned
        yield c


def test_subscription_handshake_echoes_the_challenge_only_for_our_token(client):
    ok = client.get("/whatsapp/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    assert client.get("/whatsapp/meta", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"}).status_code == 403
    assert client.get("/whatsapp/meta", params={"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"}).status_code == 403


def test_delivery_is_verified_then_acknowledged_before_any_turn(client):
    body = json.dumps(_delivery(_text("hi"), _text("there", wamid="wamid.2"))).encode()
    assert client.post("/whatsapp/meta", content=body).status_code == 403
    assert client.post("/whatsapp/meta", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"}).status_code == 403
    ok = client.post("/whatsapp/meta", content=body, headers=_signed(body))
    assert ok.status_code == 200 and ok.json() == {"ok": True, "messages": 2}
    assert [m.wamid for m in client.spawned] == ["wamid.1", "wamid.2"]
    bad = b"not json"
    assert client.post("/whatsapp/meta", content=bad, headers=_signed(bad)).status_code == 400


def test_unconfigured_instance_refuses_rather_than_accepting_anything(client, monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET")
    body = json.dumps(_delivery(_text("hi"))).encode()
    assert client.post("/whatsapp/meta", content=body, headers=_signed(body)).status_code == 503


def test_a_platforms_status_handling_runs_before_the_acknowledgement(client, monkeypatch):
    handled = AsyncMock()
    monkeypatch.setitem(capabilities._providers, capabilities.WHATSAPP_STATUSES, handled)
    monkeypatch.setattr(routes, "get_native_pool", lambda: "pool")
    body = json.dumps(_delivery(statuses=[{"id": "wamid.s", "status": "delivered"}])).encode()
    assert client.post("/whatsapp/meta", content=body, headers=_signed(body)).status_code == 200
    handled.assert_awaited_once_with("pool", json.loads(body), phone_number_id=OUR_NUMBER)
    # A write that didn't land isn't acknowledged, so Meta delivers it again.
    handled.side_effect = ConnectionError("db down")
    with pytest.raises(ConnectionError):
        client.post("/whatsapp/meta", content=body, headers=_signed(body))


# ── the Cloud API client ─────────────────────────────────────────────────────

def _api() -> CloudApi:
    return CloudApi("tok", "123")


@pytest.mark.asyncio
@respx.mock
async def test_template_send_carries_body_and_url_button():
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.1"}]}))
    message_id = await _api().send_template(
        "+14155550100", "an_approved_template", body=["Support\nbot", "Affinity connection"], button_url_param="abc123",
    )
    assert message_id == "wamid.1"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    payload = json.loads(request.read())
    assert payload["messaging_product"] == "whatsapp" and payload["to"] == "14155550100"
    template = payload["template"]
    assert template["name"] == "an_approved_template" and template["language"] == {"code": "en"}
    body, button = template["components"]
    assert [p["text"] for p in body["parameters"]] == ["Support bot", "Affinity connection"]
    assert button == {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": "abc123"}]}


@pytest.mark.asyncio
@respx.mock
async def test_text_send_is_free_form():
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.2"}]}))
    assert await _api().send_text("+14155550100", "hi") == "wamid.2"
    payload = json.loads(route.calls.last.request.read())
    assert payload["type"] == "text" and payload["text"] == {"body": "hi"}


@pytest.mark.asyncio
@respx.mock
async def test_text_with_a_link_asks_for_its_preview():
    route = respx.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.3"}]}))
    await whatsapp.send_rich(_api(), "+14155550100", "Your site is live: [Bakery](https://bakery.example.com)")
    assert json.loads(route.calls.last.request.read())["text"] == {
        "body": "Your site is live: Bakery: https://bakery.example.com", "preview_url": True}
    # No link, no preview asked for (and "example.com" without a scheme isn't one WhatsApp previews).
    await _api().send_text("+14155550100", "See example.com for more")
    assert json.loads(route.calls.last.request.read())["text"] == {"body": "See example.com for more"}


@pytest.mark.asyncio
@respx.mock
async def test_meta_rejection_raises_with_its_code():
    respx.post(MESSAGES_URL).mock(return_value=httpx.Response(
        400, json={"error": {"message": "(#132001) Template name does not exist", "code": 132001}},
    ))
    with pytest.raises(WhatsAppSendError) as exc:
        await _api().send_text("+14155550100", "hi")
    assert exc.value.code == 132001 and exc.value.status == 400
    assert "Template name does not exist" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_transport_failure_raises_not_hangs():
    respx.post(MESSAGES_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(WhatsAppSendError, match="unreachable"):
        await _api().send_text("+14155550100", "hi")


@pytest.mark.asyncio
@respx.mock
async def test_the_number_is_read_back_from_graph_and_a_bad_token_says_why():
    route = respx.get(f"{GRAPH_BASE}/123").mock(return_value=httpx.Response(
        200, json={"display_phone_number": "+1 555-010-0000", "verified_name": "Test", "id": "123"}))
    assert (await _api().phone_number())["display_phone_number"] == "+1 555-010-0000"
    assert route.calls.last.request.url.params["fields"] == "display_phone_number,verified_name"
    route.mock(return_value=httpx.Response(401, json={"error": {"message": "Invalid OAuth access token.", "code": 190}}))
    with pytest.raises(WhatsAppSendError, match="Invalid OAuth access token") as exc:
        await _api().phone_number()
    assert exc.value.code == 190


def test_from_env_requires_both_vars(monkeypatch):
    monkeypatch.delenv("WHATSAPP_CLOUD_API_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    assert CloudApi.from_env() is None
    monkeypatch.setenv("WHATSAPP_CLOUD_API_TOKEN", " tok ")
    assert CloudApi.from_env() is not None


def test_template_params_are_single_line_and_bounded():
    assert template_param("a\n\tb   c") == "a b c"
    assert template_param("") == "-"
    # Past the limit, cut at a word with an ellipsis that fits inside it.
    assert template_param("one two three four", 12) == "one two…"
    assert template_param("one two three", 13) == "one two three"
    assert template_param("x" * 30, 12) == "x" * 11 + "…"
    assert len(template_param("x" * 2000)) == 1024


@pytest.mark.asyncio
@respx.mock
async def test_media_download_is_authenticated_origin_pinned_and_size_bounded():
    url = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=123"
    response = respx.get(url).mock(return_value=httpx.Response(200, content=b"photo"))
    assert await _api().download(url, max_bytes=10) == b"photo"
    assert response.calls.last.request.headers["Authorization"] == "Bearer tok"
    with pytest.raises(WhatsAppSendError, match="larger"):
        await _api().download(url, max_bytes=2)
    for unsafe in ["https://evil.example/x", "http://lookaside.fbsbx.com/x", "https://lookaside.fbsbx.com.evil.example/x"]:
        with pytest.raises(ValueError):
            await _api().download(unsafe, max_bytes=10)
    response.mock(return_value=httpx.Response(302, headers={"location": "https://evil.example/x"}))
    with pytest.raises(WhatsAppSendError, match="302"):
        await _api().download(url, max_bytes=10)


# ── the owner's message ──────────────────────────────────────────────────────

USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def owner(monkeypatch):
    """The owner texted the WhatsApp number an hour ago: the window is open."""
    api = MagicMock(send_text=AsyncMock(return_value="wamid.out"), send_media=AsyncMock(return_value="wamid.media"))
    phones = MagicMock()
    phones.get_reach_phone = AsyncMock(return_value={"phone_e164": SENDER,
                                                     "last_seen_at": datetime.now(timezone.utc) - timedelta(hours=1)})
    phones.last_seen_app = AsyncMock(return_value="whatsapp")
    monkeypatch.setattr(whatsapp.CloudApi, "from_env", classmethod(lambda cls: api))
    monkeypatch.setattr(whatsapp, "PhoneRepo", lambda pool: phones)
    return api, phones


@pytest.mark.asyncio
async def test_inside_the_window_the_owner_gets_whatsapp_markup_with_the_link_on_its_own_line(owner):
    api, _ = owner
    out = await whatsapp.send_owner_whatsapp("pool", USER, "Here is the **link** you asked for", link=APPROVE)
    assert out == {"success": True, "channel": "whatsapp", "message_id": "wamid.out"}
    api.send_text.assert_awaited_once_with(SENDER, f"Here is the *link* you asked for\n{APPROVE}")


@pytest.mark.asyncio
async def test_past_the_window_nothing_is_sent_and_it_says_why(owner):
    api, phones = owner
    phones.get_reach_phone.return_value["last_seen_at"] = datetime.now(timezone.utc) - timedelta(hours=30)
    out = await whatsapp.send_owner_whatsapp("pool", USER, "Your reminder")
    assert out == {"success": False, "error": whatsapp.PAST_WINDOW, "permanent": True}
    api.send_text.assert_not_awaited()
    # The window's last minutes count as shut, and an owner who last texted over iMessage opened no WhatsApp window.
    phones.get_reach_phone.return_value["last_seen_at"] = datetime.now(timezone.utc) - timedelta(hours=23, minutes=58)
    assert (await whatsapp.send_owner_whatsapp("pool", USER, "x"))["success"] is False
    phones.get_reach_phone.return_value["last_seen_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    phones.last_seen_app.return_value = "imessage"
    assert (await whatsapp.send_owner_whatsapp("pool", USER, "x"))["error"] == whatsapp.PAST_WINDOW
    api.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_meta_closing_the_window_is_the_same_refusal_and_any_other_is_reported(owner):
    api, _ = owner
    api.send_text.side_effect = WhatsAppSendError("Re-engagement message", code=whatsapp.RE_ENGAGEMENT_ERROR)
    assert (await whatsapp.send_owner_whatsapp("pool", USER, "x"))["error"] == whatsapp.PAST_WINDOW
    past = AsyncMock(return_value={"success": True, "channel": "whatsapp", "message_id": "tpl"})
    assert (await whatsapp.send_owner_whatsapp("pool", USER, "x", link=APPROVE, past_window=past))["message_id"] == "tpl"
    assert past.await_args.args[1:] == (api, USER, SENDER, f"x\n{APPROVE}", APPROVE)
    api.send_text.side_effect = WhatsAppSendError("Rate limit", code=130429)
    refused = await whatsapp.send_owner_whatsapp("pool", USER, "x")
    assert refused["success"] is False and "Rate limit" in refused["error"] and "permanent" not in refused


@pytest.mark.asyncio
async def test_no_phone_or_no_configuration_is_reported(owner, monkeypatch):
    _, phones = owner
    phones.get_reach_phone.return_value = None
    assert (await whatsapp.send_owner_whatsapp("pool", USER, "x"))["permanent"] is True
    monkeypatch.setattr(whatsapp.CloudApi, "from_env", classmethod(lambda cls: None))
    out = await whatsapp.send_owner_whatsapp("pool", USER, "x")
    assert out == {"success": False, "error": "WhatsApp is not configured on this instance", "permanent": True}


def test_a_message_parsed_off_the_wire_compares_by_its_contents():
    assert InboundMessage(wamid="w", sender=SENDER, sender_name="", kind="text", raw={"a": 1}) == \
        InboundMessage(wamid="w", sender=SENDER, sender_name="", kind="text")
