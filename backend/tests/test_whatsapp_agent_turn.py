"""What a WhatsApp agent needs from a message to answer it the way a person does on WhatsApp: the message's own id
(to react to it or quote it), what it quotes, and whether it @mentions the linked account (in a group, the sign a
reply is wanted); and from each send, the id that edits it (a live status message is sent once, then edited)."""

import pytest

from nodes.core.run_op import run_node_operation
from nodes.whatsapp_node import WhatsAppNode, _sent_message_id

GROUP = "120000000000000001@g.us"
ME = {"id": "12025550101@c.us", "lid": "12025550102@lid", "pushName": "Shop"}


def _event(chat_id, *, body="hello", participant="", message=None, reply_to=None, me=ME, message_id=None):
    payload = {
        "id": message_id if message_id is not None else f"false_{chat_id}_3EB0AA",
        "from": chat_id,
        "fromMe": False,
        "body": body,
        "_data": {"key": {"remoteJid": chat_id, "fromMe": False, "participant": participant, "id": "3EB0AA"},
                  **({"message": message} if message is not None else {})},
    }
    if reply_to is not None:
        payload["replyTo"] = reply_to
    return {"event": "message", "me": me, "payload": payload}


def _text(event):
    return WhatsAppNode.resolve_agent_event(event)["text"]


def _mention(*jids):
    return {"extendedTextMessage": {"text": "@Shop can you help?", "contextInfo": {"mentionedJid": list(jids)}}}


# ── The message's id ───────────────────────────────────────────────────────────

def test_the_turn_names_the_message_id_for_reacting_and_quoting():
    text = _text(_event("12025550107@c.us"))
    assert "false_12025550107@c.us_3EB0AA" in text
    assert "message_id" in text and "reply_to_message_id" in text


def test_no_id_note_when_the_delivery_carries_no_id():
    text = _text(_event("12025550107@c.us", message_id=""))
    assert "message_id" not in text


# ── Mentions ───────────────────────────────────────────────────────────────────

def test_a_group_message_mentioning_the_linked_number_says_so():
    event = _event(GROUP, participant="12025550107@c.us", message=_mention("12025550101@s.whatsapp.net"))
    assert ", mentioning you:" in _text(event).split("\n", 1)[0]


def test_a_mention_by_the_accounts_lid_counts():
    event = _event(GROUP, participant="12025550107@c.us", message=_mention("12025550102@lid"))
    assert "mentioning you" in _text(event)


def test_a_mention_inside_a_disappearing_message_wrapper_counts():
    wrapped = {"ephemeralMessage": {"message": _mention("12025550101@s.whatsapp.net")}}
    assert "mentioning you" in _text(_event(GROUP, participant="12025550107@c.us", message=wrapped))


def test_someone_elses_mention_is_not_yours():
    event = _event(GROUP, participant="12025550107@c.us", message=_mention("12025550104@s.whatsapp.net"))
    assert "mentioning you" not in _text(event)


def test_without_the_accounts_own_ids_nothing_is_called_a_mention():
    event = _event(GROUP, participant="12025550107@c.us", message=_mention("12025550101@s.whatsapp.net"), me={})
    assert "mentioning you" not in _text(event)


# ── Quoted replies ─────────────────────────────────────────────────────────────

def test_a_reply_to_the_agents_own_message_quotes_it_as_yours():
    event = _event("12025550107@c.us", body="yes, that one",
                   reply_to={"id": "true_x_1", "participant": "12025550101@c.us", "body": "Option A\nor B?"})
    text = _text(event)
    assert '[Replying to your earlier message: "Option A or B?"]\nyes, that one' in text


def test_a_reply_to_someone_else_names_them():
    event = _event(GROUP, participant="12025550107@c.us", body="+1",
                   reply_to={"id": "false_x_2", "participant": "12025550108@c.us", "body": "Pizza tonight?"})
    assert '[Replying to a message from 12025550108@c.us: "Pizza tonight?"]' in _text(event)


def test_a_quoted_message_without_text_is_still_named():
    event = _event("12025550107@c.us", reply_to={"id": "false_x_3", "participant": "12025550107@c.us"})
    assert "[Replying to a message from 12025550107@c.us]" in _text(event)


def test_a_long_quote_is_cut():
    event = _event("12025550107@c.us", reply_to={"participant": "", "body": "x" * 900})
    line = next(line for line in _text(event).splitlines() if line.startswith("[Replying"))
    assert line.startswith("[Replying to an earlier message:") and len(line) < 560


# ── The id a send answers with ─────────────────────────────────────────────────

def test_a_text_sends_id_is_wahooks_own():
    assert _sent_message_id({"id": "true_12025550101@c.us_ABC", "key": {"id": "ABC"}}) == "true_12025550101@c.us_ABC"


def test_a_media_sends_id_is_built_from_its_key_as_wahooks_builds_it():
    sent = {"key": {"remoteJid": "12025550101@s.whatsapp.net", "fromMe": True, "id": "3EB0FF"}}
    assert _sent_message_id(sent) == "true_12025550101@c.us_3EB0FF"


def test_a_result_without_a_key_has_no_id():
    assert _sent_message_id({"success": True}) is None


class _FakeWAHooks:
    def __init__(self, **_kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def send_message(self, connection_id, *, chat_id, text, reply_to=None):
        return {"key": {"remoteJid": chat_id.replace("@c.us", "@s.whatsapp.net"), "fromMe": True, "id": "3EB0CC"},
                "id": f"true_{chat_id}_3EB0CC"}

    def send_image(self, connection_id, *, chat_id, url, caption=None):
        return {"key": {"remoteJid": chat_id, "fromMe": True, "id": "3EB0DD"}, "status": "PENDING"}


@pytest.fixture
def wahooks(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    monkeypatch.setattr("wahooks.WAHooks", _FakeWAHooks)

    async def nothing(*_a, **_kw):
        return None

    monkeypatch.setattr("nodes.whatsapp_node.record_self_post", nothing)


@pytest.mark.parametrize("operation, arguments, expected", [
    ("send_text_message", {"body": "✻ Looking it up..."}, "true_12025550101@c.us_3EB0CC"),
    ("send_image_message", {"image_url": "https://example.com/a.png"}, "true_12025550101@c.us_3EB0DD"),
])
async def test_every_send_answers_with_the_id_that_edits_it(wahooks, operation, arguments, expected):
    result = await run_node_operation(
        node_type="automation-whatsapp", operation=operation, arguments={"to": "12025550101@c.us", **arguments},
        user_id="00000000-0000-0000-0000-000000000001",
        credential_data={"credential_type": "whatsapp_qr", "connection_id": "conn-a"})
    assert result["status"] == "success"
    assert result["data"]["message_id"] == expected
