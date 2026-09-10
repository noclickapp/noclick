"""An empty WhatsApp recipient must fail the node, never report success.

A template that resolves to nothing — a reference to a key the trigger never
emits, e.g. ``{{ $('trigger').chat_id }}`` — used to become "@s.whatsapp.net".
WAHooks accepts that id, answers PENDING and never delivers, so four
"successful" agent replies went nowhere (2026-09-10).
"""

import pytest

from nodes.whatsapp_node import (
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppQRCredential,
    WhatsAppSendTextConfig,
    wahooks_chat_id,
)


def _qr_node(op_config):
    node_config = WhatsAppNodeConfig(
        config=op_config, credentials=WhatsAppQRCredential(connection_id="conn-1")
    )
    return WhatsAppNode(
        node_id="wa-1", node_type="automation-whatsapp", node_data={},
        config=node_config, sio=None, sid=None, workflow_id="wf-1",
    )


class _RecordingClient:
    """Stands in for wahooks.WAHooks; records every send."""

    calls: list = []

    def __init__(self, **_kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def send_message(self, conn_id, **kw):
        self.calls.append((conn_id, kw))
        return {"key": {"remoteJid": kw["chat_id"], "fromMe": True, "id": "3EB0"}}


@pytest.mark.parametrize("recipient", ["", "   ", None, "@s.whatsapp.net", "@lid", "+", " - "])
def test_empty_recipient_is_rejected(recipient):
    with pytest.raises(ValueError, match="recipient is empty"):
        wahooks_chat_id(recipient)


@pytest.mark.parametrize(
    "recipient,expected",
    [
        ("+1 202-555-0100", "12025550100@s.whatsapp.net"),
        ("12025550100", "12025550100@s.whatsapp.net"),
        ("12025550102@lid", "12025550102@lid"),
        ("12025550107@c.us", "12025550107@c.us"),
        ("120000000000000001@g.us", "120000000000000001@g.us"),
    ],
)
def test_recipients_normalize(recipient, expected):
    assert wahooks_chat_id(recipient) == expected


async def test_send_with_empty_recipient_fails_loudly_before_calling_wahooks(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    _RecordingClient.calls = []
    monkeypatch.setattr("wahooks.WAHooks", _RecordingClient)
    cfg = WhatsAppSendTextConfig(to="", body="Habari")
    node = _qr_node(cfg)

    with pytest.raises(ValueError, match=r"payload\.from"):
        await node._execute_wahooks(cfg, WhatsAppQRCredential(connection_id="conn-1"))

    assert _RecordingClient.calls == []


async def test_send_with_trigger_chat_id_reaches_wahooks_verbatim(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    _RecordingClient.calls = []
    monkeypatch.setattr("wahooks.WAHooks", _RecordingClient)
    cfg = WhatsAppSendTextConfig(to="12025550102@lid", body="Habari")
    node = _qr_node(cfg)

    result = await node._execute_wahooks(cfg, WhatsAppQRCredential(connection_id="conn-1"))

    assert result["status"] == "success"
    assert _RecordingClient.calls == [
        ("conn-1", {"chat_id": "12025550102@lid", "text": "Habari", "reply_to": None})
    ]
