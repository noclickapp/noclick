"""Inbound Telegram media rehosting + the media the agent event carries.

A Telegram attachment arrives as a bare ``file_id``; the Bot API's download
URL embeds the bot token, so it is useless (and unsafe) to hand to a run.
``transform_trigger_payload`` fetches it at delivery with the node's own
credential and rehosts it to workflow resources through the shared
``utils.inbound_media`` seam — the SAME ``media`` slot WhatsApp fills, so the
agent digest, the run popup and the chat frame read one shape — and
``resolve_agent_event`` hands the agent the capability URL plus a digestible
media entry (a voice note transcribes into the turn).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.telegram_node import TelegramNode, message_attachment, update_message

TG_CFG = {"operation": "receive_message", "credentialIds": {"telegram_bot_token": "cred-1"}}
TOKEN = "123456:ABC-secret"


def _voice_update(**msg_extra):
    return {
        "update_id": 7,
        "message": {
            "message_id": 11,
            "chat": {"id": 100000001, "type": "private"},
            "from": {"username": "alex_example", "first_name": "Alex"},
            "voice": {
                "file_id": "AwACAgIAAxkBAAIC",
                "file_unique_id": "AgAD",
                "duration": 14,
                "mime_type": "audio/ogg",
                "file_size": 21000,
            },
            **msg_extra,
        },
    }


class _FakeStreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.headers = {"content-type": "audio/ogg"}

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.requests = []

    def __call__(self, timeout=None, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        self.requests.append((method, url, headers))
        return _FakeStreamResponse(self._chunks)


def _pool(owner="0b129266-59d2-4ab8-9e19-6e6342d67270"):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"owner_id": owner, "organization_id": None})
    return pool


def test_message_attachment_picks_the_largest_photo_and_the_voice_default_mime():
    msg = {"photo": [{"file_id": "s", "width": 90}, {"file_id": "l", "width": 800}]}
    assert message_attachment(msg) == ("photo", {"file_id": "l", "width": 800}, "image/jpeg")
    assert message_attachment(_voice_update()["message"])[0] == "voice"
    assert message_attachment({"text": "hi"}) is None
    assert update_message({"edited_message": {"text": "x"}}) == {"text": "x"}
    assert update_message({"my_chat_member": {}}) is None


@pytest.mark.asyncio
async def test_voice_note_rehosted_with_the_bot_token_that_never_rides_the_payload():
    payload = _voice_update()
    client = _FakeClient(chunks=[b"ogg-bytes"])
    store = AsyncMock(return_value={
        "resource_id": "res-1", "name": "voice-AgAD.oga", "mime_type": "audio/ogg",
        "size_bytes": 9, "storage_ref": "o/w/res-1/voice-AgAD.oga",
        "download_url": "https://assets.example.test/o/w/res-1/voice-AgAD.oga",
    })
    get_file = AsyncMock(return_value={"file_path": "voice/file_3.oga", "file_size": 21000})
    with patch("nodes.telegram_node.TelegramNode._delivery_bot_token", AsyncMock(return_value=TOKEN)), \
         patch("nodes.telegram_node.get_telegram_file_info", get_file), \
         patch("utils.inbound_media.guarded_async_client", client), \
         patch("utils.resource_store.create_resource_from_bytes", store):
        out = await TelegramNode.transform_trigger_payload(
            payload, TG_CFG, pool=_pool(), workflow_id="wf-1", node_id="tg-1",
        )

    assert out is payload
    media = out["message"]["media"]
    assert media["url"] == "https://assets.example.test/o/w/res-1/voice-AgAD.oga"
    assert media["rehosted"] is True and media["resource_id"] == "res-1"
    assert media["kind"] == "voice" and media["duration"] == 14
    get_file.assert_awaited_once_with(TOKEN, "AwACAgIAAxkBAAIC")
    # The token authenticated the fetch but never leaks into the payload.
    _, url, _ = client.requests[0]
    assert url == f"https://api.telegram.org/file/bot{TOKEN}/voice/file_3.oga"
    assert TOKEN not in str(out)
    store.assert_awaited_once_with(
        user_id="0b129266-59d2-4ab8-9e19-6e6342d67270", workflow_id="wf-1",
        node_id="tg-1", organization_id=None, body=b"ogg-bytes",
        content_type="audio/ogg", filename="voice-AgAD.oga",
        metadata={"source": "telegram_inbound_media"},
    )


@pytest.mark.asyncio
async def test_no_credential_or_no_attachment_leaves_the_delivery_untouched():
    get_file = AsyncMock()
    with patch("nodes.telegram_node.get_telegram_file_info", get_file):
        assert await TelegramNode.transform_trigger_payload(
            _voice_update(), {"operation": "receive_message"}, pool=_pool(), workflow_id="wf-1", node_id="n",
        ) is None
        text_only = {"update_id": 1, "message": {"text": "hi", "chat": {"id": 1}}}
        assert await TelegramNode.transform_trigger_payload(
            text_only, TG_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
        ) is None
    get_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_token_resolves_the_node_credential_as_the_owner():
    resolve = AsyncMock(return_value={"credential_type": "telegram_bot_token", "token": TOKEN})
    pool = _pool()
    with patch("utils.credentials.resolve_credential_with_owner_fallback", resolve):
        token = await TelegramNode._delivery_bot_token(TG_CFG, pool, "wf-1")
    assert token == TOKEN
    resolve.assert_awaited_once_with(
        "cred-1", "0b129266-59d2-4ab8-9e19-6e6342d67270", pool, org_id=None, workflow_id="wf-1",
    )


# ── agent-facing rendering ──────────────────────────────────────────────────

def test_agent_event_voice_note_reads_as_voice_message_with_a_digestible_entry():
    update = _voice_update()
    update["message"]["media"] = {
        "url": "https://assets.example.test/o/w/r/voice-AgAD.oga", "mimetype": "audio/ogg",
        "filename": "voice-AgAD.oga", "size": 21000, "rehosted": True, "resource_id": "res-1",
        "kind": "voice", "duration": 14,
    }
    event = TelegramNode.resolve_agent_event(update)
    assert event["conversation_key"] == "100000001"
    assert "Telegram message from alex_example" in event["text"]
    assert "[voice message]" in event["text"]
    assert "https://assets.example.test/o/w/r/voice-AgAD.oga" in event["text"]
    (entry,) = event["media"]
    assert entry["voice"] is True and entry["duration_s"] == 14
    assert entry["resource_id"] == "res-1"
    assert entry["record"] is update["message"]["media"]


def test_agent_event_captioned_photo_keeps_the_caption():
    update = {"message": {
        "caption": "look at this", "chat": {"id": 42}, "from": {"first_name": "A"},
        "photo": [{"file_id": "s"}, {"file_id": "l"}],
        "media": {"url": "https://assets.example.test/o/w/r/photo-l.jpg", "mimetype": "image/jpeg",
                  "rehosted": True, "resource_id": "res-2", "kind": "photo"},
    }}
    event = TelegramNode.resolve_agent_event(update)
    assert "look at this" in event["text"] and "[image]" not in event["text"]
    assert "Attached photo (image/jpeg): https://assets.example.test/o/w/r/photo-l.jpg" in event["text"]
    assert event["media"][0]["mime_type"] == "image/jpeg"


def test_agent_event_honest_when_media_not_rehosted():
    event = TelegramNode.resolve_agent_event(_voice_update())
    assert "[voice message]" in event["text"]
    assert "could not be retrieved" in event["text"]
    assert event["media"] == []
    assert event["conversation_key"] == "100000001"  # still a message turn, not raw JSON
