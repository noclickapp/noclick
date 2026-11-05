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


# --- a send to NoClick's own line ----------------------------------------------------


NOCLICK_LINE = "+12025550108"


@pytest.fixture
def noclick_line(monkeypatch):
    monkeypatch.setenv("WHATSAPP_DISPLAY_NUMBER", NOCLICK_LINE)
    monkeypatch.delenv("SENDBLUE_NUMBER", raising=False)


@pytest.mark.parametrize("recipient", [NOCLICK_LINE, "12025550108", "12025550108@c.us", "12025550108:3@s.whatsapp.net",
                                       "+1 202-555-0108"])
async def test_a_send_to_noclicks_own_line_is_refused_and_says_why(noclick_line, monkeypatch, recipient):
    """The owner's phone holds a chat with NoClick, so an agent going through their chats takes it for a contact."""
    monkeypatch.setattr("wahooks.WAHooks", _RecordingClient, raising=False)
    monkeypatch.setenv("WAHOOKS_API_KEY", "key")
    _RecordingClient.calls = []
    with pytest.raises(ValueError) as refused:
        await _qr_node(WhatsAppSendTextConfig(to=recipient, body="Hello")).execute({})
    assert _RecordingClient.calls == []
    # In words it can act on: what the number is, and where to send instead.
    assert "NoClick's own line" in str(refused.value) and "the sender's id from the event" in str(refused.value)


async def test_a_send_to_anyone_else_goes_through(noclick_line, monkeypatch):
    monkeypatch.setattr("wahooks.WAHooks", _RecordingClient, raising=False)
    monkeypatch.setenv("WAHOOKS_API_KEY", "key")
    _RecordingClient.calls = []
    result = await _qr_node(WhatsAppSendTextConfig(to="+12025550101", body="Hello")).execute({})
    assert result["status"] == "success" and _RecordingClient.calls[0][1]["chat_id"] == "12025550101@s.whatsapp.net"


async def test_with_no_line_of_noclicks_nothing_is_refused(monkeypatch):
    """A self-hosted instance with no WhatsApp or iMessage line of its own."""
    monkeypatch.delenv("WHATSAPP_DISPLAY_NUMBER", raising=False)
    monkeypatch.delenv("SENDBLUE_NUMBER", raising=False)
    monkeypatch.setattr("wahooks.WAHooks", _RecordingClient, raising=False)
    monkeypatch.setenv("WAHOOKS_API_KEY", "key")
    _RecordingClient.calls = []
    result = await _qr_node(WhatsAppSendTextConfig(to=NOCLICK_LINE, body="Hello")).execute({})
    assert result["status"] == "success"


async def test_its_lid_is_refused_once_a_delivery_said_whose_it_is(noclick_line, monkeypatch):
    """WhatsApp names more and more chats by a @lid, which holds no number: a message of NoClick's says whose it is, and
    never reaches the trigger, so it's kept before the filter drops it."""
    import fakeredis.aioredis

    redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    monkeypatch.setattr("wahooks.WAHooks", _RecordingClient, raising=False)
    monkeypatch.setenv("WAHOOKS_API_KEY", "key")
    _RecordingClient.calls = []
    lid = "12025550103@lid"
    node = _qr_node(WhatsAppSendTextConfig(to=lid, body="Hello"))
    assert (await node.execute({}))["status"] == "success"

    delivery = {"event": "message", "session": "s", "connectionId": "conn-1",
                "payload": {"from": lid, "fromMe": False, "senderPhone": "12025550108", "_data": {"key": {}}}}
    config = {"credentialIds": {"whatsapp_qr": "cred-1"}}

    async def own_account(*args, **kwargs):
        return None

    monkeypatch.setattr(WhatsAppNode, "_foreign_account_delivery", own_account)
    assert await WhatsAppNode.handle_control_event(delivery, config, pool=None, workflow_id="wf-1", node_id="n") is None
    with pytest.raises(ValueError, match="NoClick's own line"):
        await node.execute({})
    assert len(_RecordingClient.calls) == 1


async def test_an_agent_reads_the_refusal_as_its_tools_error(noclick_line, monkeypatch):
    """The one way a node's refusal reaches a model: ``execute_tool``'s catch-all."""
    from types import SimpleNamespace

    from nodes.agent import tool_execution

    async def run_node_operation(**kwargs):
        await _qr_node(WhatsAppSendTextConfig(to=kwargs["arguments"]["to"], body="Hello")).execute({})

    monkeypatch.setattr("nodes.core.run_op.run_node_operation", run_node_operation)
    agent = SimpleNamespace(conversation_id="ck:wf:agent:c1", user_id="user", workflow_id="wf", node_id="agent",
                            execution_id=None, organization_id=None)
    tools = {"whatsapp__send_text_message": {"node_id": "wa-1", "tool_type": "node_op",
                                             "node_type": "automation-whatsapp", "operation": "send_text_message",
                                             "credential_id": "cred-1"}}
    result = await tool_execution.execute_tool(agent, "whatsapp__send_text_message",
                                               {"to": NOCLICK_LINE, "body": "Hello"}, tools)
    assert result["success"] is False and "NoClick's own line" in result["error"]
