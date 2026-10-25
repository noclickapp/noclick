"""A text to the assistant's iMessage line (coder/coordinator/texting/imessage.py, Sendblue): verified by the webhook
secret, parsed to one-to-one messages on our line only, answered in plain text; the Sendblue client; and the owner's
message over iMessage."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coder.coordinator.texting import imessage, routes
from coder.coordinator.texting.imessage import InboundMessage, parse_inbound, send_rich, to_imessage_text, verify_secret
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


@pytest.mark.asyncio
async def test_rich_reply_sends_text_then_each_attachment_with_its_caption():
    api = MagicMock()
    api.send = AsyncMock(side_effect=["h1", "h2"])
    assert await send_rich(api, USER_PHONE, "Here it is **now**\n![the chart](https://x/c.png)") == "h1"
    assert api.send.await_args_list[0].kwargs == {"content": "Here it is now"}
    assert api.send.await_args_list[1].kwargs == {"content": "the chart", "media_url": "https://x/c.png"}


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
