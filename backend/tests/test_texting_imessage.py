"""A text to the assistant's iMessage line (coder/coordinator/texting/imessage.py, Sendblue): verified by the webhook
secret, parsed to one-to-one messages on our line only, answered in plain text; the Sendblue client; and the owner's
message over iMessage."""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coder.coordinator.texting import channel, imessage, routes
from coder.coordinator.texting.imessage import InboundMessage, parse_inbound, send_rich, to_imessage_text, verify_secret
from nodes.core.media_resolver import FileInfo
from utils import capabilities
from utils.sendblue import API_BASE, Sendblue, SendblueError

LINE = "+14155550123"
USER_PHONE = "+14155550100"
USER = "11111111-1111-1111-1111-111111111111"
SECRET = "sb-secret"


def _receive(**overrides):
    payload = {
        "accountEmail": "ops@example.com", "content": "what do I have?", "is_outbound": False, "status": "RECEIVED",
        "message_handle": "msg-1", "from_number": USER_PHONE, "number": USER_PHONE, "to_number": LINE,
        "sendblue_number": LINE, "media_url": "", "message_type": "message", "group_id": "", "service": "iMessage",
    }
    return {**payload, **overrides}


def test_the_webhook_secret_must_match_exactly():
    assert verify_secret(SECRET, SECRET)
    assert not verify_secret(SECRET, "sb-secre")
    assert not verify_secret(SECRET, None)
    assert not verify_secret("", "")  # an unset secret verifies nothing


def test_parse_keeps_one_to_one_messages_to_our_line():
    message = parse_inbound(_receive(), line=LINE)
    assert message == InboundMessage(handle="msg-1", sender=USER_PHONE, text="what do I have?", service="iMessage")
    assert message.raw == _receive()
    assert parse_inbound(_receive(is_outbound=True), line=LINE) is None  # our own send, echoed back
    assert parse_inbound(_receive(sendblue_number="+19999999999", to_number="+19999999999"), line=LINE) is None
    assert parse_inbound(_receive(group_id="group-1"), line=LINE) is None
    assert parse_inbound(_receive(message_type="reaction"), line=LINE) is None
    assert parse_inbound(_receive(content="", media_url=""), line=LINE) is None
    sms = parse_inbound(_receive(service="SMS", number="14155550100"), line=LINE)
    assert sms.sender == USER_PHONE and sms.service == "SMS"


def test_parse_names_an_attachment_by_its_file():
    photo = parse_inbound(_receive(content="", media_url="https://cdn.sendblue.co/x/IMG_1.HEIC"), line=LINE)
    assert (photo.kind, photo.text) == ("image", "")
    voice = parse_inbound(_receive(content="", media_url="https://cdn.sendblue.co/x/Audio.caf?sig=1"), line=LINE)
    assert voice.kind == "audio"
    assert parse_inbound(_receive(media_url="https://cdn.sendblue.co/x/notes.pdf"), line=LINE).kind == "document"


def test_replies_are_plain_text():
    assert to_imessage_text("You have **3** workflows. See [the dashboard](https://example.com/d).\n\n# Next\n- one\n* two") == (
        "You have 3 workflows. See the dashboard: https://example.com/d.\n\nNext\n• one\n• two")
    assert to_imessage_text("Run `nc deploy`:\n```bash\nnc deploy\n```") == "Run nc deploy:\nnc deploy"


@pytest.fixture
def files(monkeypatch):
    """What each embedded URL holds, as the stored file's record or its server would say (``describe_url``)."""
    known = {}

    async def describe(url):
        return known.get(url)

    monkeypatch.setattr(channel, "describe_url", describe)
    return known


@pytest.mark.asyncio
async def test_rich_reply_sends_text_then_each_attachment_with_its_caption(files):
    files["https://x/c.png"] = FileInfo("image/png", "c.png", 1000)
    files["https://x/d.png"] = FileInfo("image/png", "d.png", 1000)
    api = MagicMock()
    api.send = AsyncMock(side_effect=["h1", "h2", "h3"])
    assert await send_rich(api, USER_PHONE,
                           "Here they are **now**\n![the chart](https://x/c.png)\n![the table](https://x/d.png)") == "h1"
    assert [call.kwargs for call in api.send.await_args_list] == [
        {"content": "Here they are now"}, {"content": "the chart", "media_url": "https://x/c.png"},
        {"content": "the table", "media_url": "https://x/d.png"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mime, name", [("image/png", "quiet-form.png"), ("video/quicktime", "walkthrough.mov")])
async def test_a_reply_with_one_picture_is_one_send_with_its_text(files, mime, name):
    """A person picking a design got the reply's text, then the picture on its own: one picture or video goes in the
    same send as the text, in place of the embed's own caption."""
    url = f"https://assets.example/u/w/r/{name}"
    files[url] = FileInfo(mime, name, 300_000)
    api = MagicMock(send=AsyncMock(return_value="h1"), upload_file=AsyncMock())
    assert await send_rich(api, USER_PHONE, f"Here's **Quiet Form** on a phone:\n![The homepage]({url})\n"
                                            "Shall I build it?") == "h1"
    api.send.assert_awaited_once_with(USER_PHONE, content="Here's Quiet Form on a phone:\n\nShall I build it?",
                                      media_url=url)


@pytest.mark.asyncio
async def test_a_document_or_text_past_one_message_still_goes_first_on_its_own(files):
    files["https://x/brief.pdf"] = FileInfo("application/pdf", "brief.pdf", 1000)
    files["https://x/c.png"] = FileInfo("image/png", "c.png", 1000)
    api = MagicMock(send=AsyncMock(return_value="h1"))
    await send_rich(api, USER_PHONE, "The brief.\n![Brief](https://x/brief.pdf)")
    long = "x" * (channel.TEXT_LIMIT + 1)
    await send_rich(api, USER_PHONE, f"{long}\n![the chart](https://x/c.png)")
    assert [call.kwargs for call in api.send.await_args_list] == [
        {"content": "The brief."}, {"content": "Brief", "media_url": "https://x/brief.pdf"},
        {"content": long[:channel.TEXT_LIMIT]}, {"content": "x"},
        {"content": "the chart", "media_url": "https://x/c.png"}]


MB = 1024 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize("mime, name", [
    ("application/pdf", "Dummy PDF.pdf"), ("text/html", "game.html"), ("application/zip", "Neon Static.zip"),
    ("audio/x-caf", "Voice.caf"), ("video/quicktime", "clip.mov"),
])
async def test_any_file_whose_url_names_it_is_sent_from_that_url(files, mime, name):
    url = f"https://assets.example/u/w/r/{name.replace(' ', '%20')}"
    files[url] = FileInfo(mime, name, 2 * MB)
    api = MagicMock(send=AsyncMock(return_value="h1"), upload_file=AsyncMock())
    await send_rich(api, USER_PHONE, f"![{name}]({url})")
    # The caption that only repeats the file's name is left off: iMessage shows the file with its name.
    api.send.assert_awaited_once_with(USER_PHONE, content=None, media_url=url)
    api.upload_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_file_whose_url_doesnt_name_its_type_goes_up_to_sendblue_under_its_name(files, monkeypatch):
    stored = "https://assets.example/u/w/r/Dummy%20PDF"  # uploaded before names kept their extension
    signed = "https://files.example/report.pdf?X-Amz-Signature=abc"  # Sendblue takes no signed URL
    files[stored] = FileInfo("application/pdf", "Dummy PDF.pdf", 642)
    files[signed] = FileInfo("application/pdf", "report.pdf", 5000)
    read = AsyncMock(side_effect=[b"%PDF-1.4 dummy", b"%PDF-1.4 report"])
    monkeypatch.setattr(imessage, "read_url", read)
    api = MagicMock(send=AsyncMock(side_effect=["h1", "h2", "h3"]),
                    upload_file=AsyncMock(side_effect=["https://cdn.sendblue.co/up/a.pdf", "https://cdn.sendblue.co/up/b.pdf"]))
    await send_rich(api, USER_PHONE, f"Here they are.\n![The dummy]({stored})\n![report.pdf]({signed})")
    assert read.await_args_list == [((stored,), {"max_bytes": imessage.UPLOAD_LIMIT}),
                                    ((signed,), {"max_bytes": imessage.UPLOAD_LIMIT})]
    assert api.upload_file.await_args_list[0].args == (b"%PDF-1.4 dummy",)
    assert api.upload_file.await_args_list[0].kwargs == {"filename": "Dummy PDF.pdf", "mime_type": "application/pdf"}
    assert [call.kwargs for call in api.send.await_args_list] == [
        {"content": "Here they are."},
        {"content": "The dummy", "media_url": "https://cdn.sendblue.co/up/a.pdf"},
        {"content": None, "media_url": "https://cdn.sendblue.co/up/b.pdf"},
    ]


@pytest.mark.asyncio
async def test_a_file_that_cant_be_read_sends_none_of_the_message(files, monkeypatch):
    url = "https://files.example/report.pdf?X-Amz-Signature=abc"
    files[url] = FileInfo("application/pdf", "report.pdf", 5000)
    monkeypatch.setattr(imessage, "read_url", AsyncMock(side_effect=ValueError("Could not fetch media from URL: 403")))
    api = MagicMock(send=AsyncMock(), upload_file=AsyncMock())
    with pytest.raises(SendblueError, match="couldn't read report.pdf"):
        await send_rich(api, USER_PHONE, f"Here.\n![report.pdf]({url})")
    api.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_file_nothing_can_tell_the_type_of_or_past_sendblues_cap_is_a_link_line(files):
    files["https://f.example/huge.mov"] = FileInfo("video/quicktime", "huge.mov", 150 * MB)
    api = MagicMock(send=AsyncMock(return_value="h1"), upload_file=AsyncMock())
    await send_rich(api, USER_PHONE, "Two files.\n![The video](https://f.example/huge.mov)\n![x](https://f.example/x)")
    api.send.assert_awaited_once_with(
        USER_PHONE, content="Two files.\nThe video: https://f.example/huge.mov\nx: https://f.example/x")


@pytest.mark.asyncio
async def test_a_stored_file_past_sendblues_cap_is_the_link_that_saves_it_and_a_page_is_both(files, monkeypatch):
    owner, workflow = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    video_key = f"{owner}/{workflow}/33333333-3333-3333-3333-333333333333/huge.mov"
    page_key = f"{owner}/{workflow}/44444444-4444-4444-4444-444444444444/game.html"
    monkeypatch.setattr("utils.resource_store.get_public_download_url", lambda key: "https://files.test/" + quote(key))
    monkeypatch.setitem(capabilities._providers, capabilities.FILE_DOWNLOAD_URL,
                        lambda key: "https://dl.test/files/" + quote(key))
    video, page = "https://files.test/" + video_key, "https://files.test/" + page_key
    files[video] = FileInfo("video/quicktime", "huge.mov", 150 * MB)
    files[page] = FileInfo("text/html", "game.html", 2 * MB)
    api = MagicMock(send=AsyncMock(return_value="h1"), upload_file=AsyncMock())
    await send_rich(api, USER_PHONE, f"Both.\n![The video]({video})\n![game.html]({page})")
    assert [call.kwargs for call in api.send.await_args_list] == [
        # A page goes as the file it is and, in the text, the link that saves it.
        {"content": f"Both.\nThe video: https://dl.test/files/{video_key}\n"
                    f"game.html: https://dl.test/files/{page_key}"},
        {"content": None, "media_url": page},
    ]


APPROVE = "https://example.com/h/0f8b3c2a-1d2e-4f5a-9b6c-7d8e9f0a1b2c?k=0123456789abcdef0123456789abcdef"


@pytest.mark.asyncio
async def test_a_link_texted_to_the_owner_is_a_line_of_its_own():
    from coder.coordinator.reach import with_link

    api = MagicMock(send=AsyncMock(return_value="h1"))
    await send_rich(api, USER_PHONE, with_link("The build wants to buy +1 555 010 0199. Approve it?", APPROVE))
    assert api.send.await_args.kwargs["content"].split("\n") == ["The build wants to buy +1 555 010 0199. Approve it?", APPROVE]


@pytest.mark.asyncio
@respx.mock
async def test_the_client_speaks_sendblues_api_and_raises_its_refusals():
    api = Sendblue("key-id", "key-secret", LINE)
    route = respx.post(f"{API_BASE}/send-message").mock(return_value=httpx.Response(200, json={"status": "QUEUED", "message_handle": "h9"}))
    assert await api.send(USER_PHONE, content="hi") == "h9"
    sent = route.calls.last.request
    assert sent.headers["sb-api-key-id"] == "key-id" and sent.headers["sb-api-secret-key"] == "key-secret"
    assert sent.read() == b'{"number":"+14155550100","from_number":"+14155550123","content":"hi"}'
    respx.post(f"{API_BASE}/send-message").mock(return_value=httpx.Response(
        400, json={"status": "ERROR", "error_message": "contact limit reached", "error_key": "pre_reply_limit"}))
    with pytest.raises(SendblueError) as refused:
        await api.send(USER_PHONE, content="hi")
    assert (refused.value.status, refused.value.key, str(refused.value)) == (400, "pre_reply_limit", "contact limit reached")
    share = respx.post(f"{API_BASE}/v2/contact-sharing/share").mock(return_value=httpx.Response(200, json={"status": "OK"}))
    await api.share_profile(USER_PHONE)
    assert share.calls.last.request.read() == b'{"fromNumber":"+14155550123","toNumber":"+14155550100"}'


@pytest.mark.asyncio
@respx.mock
async def test_a_file_goes_up_to_sendblue_as_a_multipart_upload_named_by_its_file():
    api = Sendblue("key-id", "key-secret", LINE)
    route = respx.post(f"{API_BASE}/upload-file").mock(return_value=httpx.Response(
        201, json={"status": "OK", "message": "File uploaded successfully", "media_url": "https://cdn.sendblue.co/a.pdf"}))
    assert await api.upload_file(b"%PDF-1.4", filename="Dummy PDF.pdf", mime_type="application/pdf") == \
        "https://cdn.sendblue.co/a.pdf"
    sent = route.calls.last.request
    assert sent.headers["sb-api-key-id"] == "key-id" and sent.headers["content-type"].startswith("multipart/form-data")
    body = sent.read()
    assert b'name="file"; filename="Dummy PDF.pdf"' in body and b"Content-Type: application/pdf" in body
    assert b"%PDF-1.4" in body
    route.mock(return_value=httpx.Response(400, json={"status": "ERROR", "message": "No file uploaded"}))
    with pytest.raises(SendblueError, match="No file uploaded"):
        await api.upload_file(b"", filename="x.pdf", mime_type="application/pdf")
    route.mock(return_value=httpx.Response(201, json={"status": "OK"}))
    with pytest.raises(SendblueError, match="no media_url"):
        await api.upload_file(b"x", filename="x.pdf", mime_type="application/pdf")


@pytest.mark.asyncio
@respx.mock
async def test_the_keys_are_checked_with_a_read_that_only_a_valid_pair_answers():
    route = respx.get(f"{API_BASE}/v2/messages").mock(return_value=httpx.Response(200, json={"data": []}))
    await Sendblue("key-id", "key-secret", LINE).check_keys()
    assert route.calls.last.request.headers["sb-api-key-id"] == "key-id"
    assert route.calls.last.request.url.params["limit"] == "1"
    route.mock(return_value=httpx.Response(401, json={"status": "ERROR", "message": "Invalid API key"}))
    with pytest.raises(SendblueError, match="Invalid API key") as refused:
        await Sendblue("bad", "bad", LINE).check_keys()
    assert refused.value.status == 401


@pytest.fixture
def client(monkeypatch):
    spawned = []

    def fake_spawn(coro, name=None):
        spawned.append(name)
        coro.close()

    monkeypatch.setattr(routes, "spawn", fake_spawn)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), spawned


def test_the_webhook_needs_configuration_and_the_secret_then_acknowledges(client, monkeypatch):
    http, spawned = client
    for name in ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET", "SENDBLUE_NUMBER", "SENDBLUE_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert http.post("/imessage/sendblue", json=_receive()).status_code == 503
    monkeypatch.setenv("SENDBLUE_API_KEY", "k")
    monkeypatch.setenv("SENDBLUE_API_SECRET", "s")
    monkeypatch.setenv("SENDBLUE_NUMBER", LINE)
    monkeypatch.setenv("SENDBLUE_WEBHOOK_SECRET", SECRET)
    assert http.post("/imessage/sendblue", json=_receive(), headers={"sb-signing-secret": "nope"}).status_code == 403
    ok = http.post("/imessage/sendblue", json=_receive(), headers={"sb-signing-secret": SECRET})
    assert ok.status_code == 200 and ok.json() == {"ok": True, "messages": 1} and spawned == ["imessage-inbound:msg-1"]
    echo = http.post("/imessage/sendblue", json=_receive(is_outbound=True), headers={"sb-signing-secret": SECRET})
    assert echo.json() == {"ok": True, "messages": 0} and len(spawned) == 1


@pytest.mark.asyncio
async def test_a_message_to_the_owner_says_whether_it_went_and_shares_the_profile_when_asked(monkeypatch):
    api = MagicMock(send=AsyncMock(return_value="out-1"), share_profile=AsyncMock())
    phones = MagicMock(get_reach_phone=AsyncMock(return_value={"phone_e164": USER_PHONE}))
    monkeypatch.setattr(imessage.Sendblue, "from_env", classmethod(lambda cls: api))
    monkeypatch.setattr(imessage, "PhoneRepo", lambda pool: phones)
    assert await imessage.send_owner_imessage("pool", USER, "It's live.", share_profile=True) == {
        "success": True, "channel": "imessage", "message_id": "out-1"}
    api.share_profile.assert_awaited_once_with(USER_PHONE)
    # A profile that can't be shared doesn't undo the message.
    api.share_profile.side_effect = SendblueError("not a chat", status=400)
    assert (await imessage.send_owner_imessage("pool", USER, "Again.", share_profile=True))["success"]
    # A message with more to come shows typing again after it; one that can't, still went.
    api.typing = AsyncMock()
    assert (await imessage.send_owner_imessage("pool", USER, "Checking your balance.", typing=True))["success"]
    api.typing.assert_awaited_once_with(USER_PHONE)
    api.typing.side_effect = SendblueError("unsupported", status=422)
    assert (await imessage.send_owner_imessage("pool", USER, "Checking.", typing=True))["success"]
    api.send.side_effect = SendblueError("down", status=503)
    refused = await imessage.send_owner_imessage("pool", USER, "Hi")
    assert refused["success"] is False and "permanent" not in refused  # worth trying again
    phones.get_reach_phone.return_value = None
    assert (await imessage.send_owner_imessage("pool", USER, "Hi"))["permanent"] is True
    monkeypatch.setattr(imessage.Sendblue, "from_env", classmethod(lambda cls: None))
    assert (await imessage.send_owner_imessage("pool", USER, "Hi"))["error"] == "iMessage is not configured on this instance"
