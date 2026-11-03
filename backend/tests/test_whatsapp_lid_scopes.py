"""A recipient scope written as numbers knows the chat an allowed person writes from as a @lid.

WhatsApp names a moved chat by a privacy id (``…@lid``); a message from it still names the
writer's number (WAHooks' ``senderPhone``). Before, a scope picked as numbers refused the
agent's reply to that very chat.
"""

import pytest
from fakeredis import aioredis

from nodes.agent.node_op_tools import build_node_op_tools, build_provider_output
from nodes.core import run_op
from nodes.core.run_op import field_scope_refusal, run_node_op_tool
from nodes.whatsapp_node import WhatsAppNode, chat_number

ALLOWED = "12025550101@c.us"
LID = "12025550102@lid"


@pytest.fixture
def redis(monkeypatch):
    client = aioredis.FakeRedis()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: client)
    return client


@pytest.fixture
def ran(monkeypatch):
    """The provider's credential is a QR link on conn-1; runs are recorded, never sent."""
    calls = []

    async def credential(credential_id, user_id, pool=None, organization_id=None, workflow_id=None):
        return {"credential_type": "whatsapp_qr", "connection_id": "conn-1"}

    async def run(**kwargs):
        calls.append(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(run_op, "resolve_operation_credential", credential)
    monkeypatch.setattr(run_op, "run_node_operation", run)
    return calls


def _send_tool(to=ALLOWED):
    output = build_provider_output("automation-whatsapp", {
        "agent_tool_operations": [{"operation": "send_text_message", "field_scopes": {"to": [to]}}],
        "credentialIds": {"whatsapp_qr": "cred-1"},
    })
    _, configs = build_node_op_tools(
        "automation-whatsapp", output["allowed_operations"], node_id="wa", credential_id="cred-1",
    )
    return next(cfg for name, cfg in configs.items() if name.endswith("__send_text_message"))


def _delivery(sender=LID, phone="12025550101", connection="conn-1", **extra):
    return {
        "event": "message", "connectionId": connection,
        "payload": {"id": "m1", "from": sender, "fromMe": False, "body": "hi", "senderPhone": phone, **extra},
    }


async def _deliver(payload):
    await WhatsAppNode.transform_trigger_payload(payload, {}, pool=None, workflow_id="wf1", node_id="trigger")


@pytest.mark.asyncio
async def test_the_agent_replies_to_an_allowed_person_writing_from_a_lid(redis, ran):
    await _deliver(_delivery())

    result = await run_node_op_tool(_send_tool(), {"to": LID, "body": "hello"}, user_id="u1", workflow_id="wf1")

    assert result == {"status": "success"}
    assert ran[0]["arguments"]["to"] == LID  # sent to the chat that wrote, as given


@pytest.mark.asyncio
async def test_a_lid_whose_number_is_not_allowed_is_still_refused(redis, ran):
    await _deliver(_delivery(phone="15559990000"))

    result = await run_node_op_tool(_send_tool(), {"to": LID, "body": "hello"}, user_id="u1", workflow_id="wf1")

    assert result["success"] is False and "restricted" in result["error"]
    assert ran == []


@pytest.mark.asyncio
async def test_a_lid_no_message_has_named_is_refused(redis, ran):
    await _deliver(_delivery(phone=None))  # WhatsApp hid the number

    result = await run_node_op_tool(_send_tool(), {"to": LID, "body": "hello"}, user_id="u1", workflow_id="wf1")

    assert result["success"] is False and ran == []


@pytest.mark.asyncio
async def test_a_number_learned_on_one_link_says_nothing_on_another(redis, ran):
    await _deliver(_delivery(connection="conn-2"))

    result = await run_node_op_tool(_send_tool(), {"to": LID, "body": "hello"}, user_id="u1", workflow_id="wf1")

    assert result["success"] is False and ran == []


@pytest.mark.asyncio
async def test_messages_the_account_sent_teach_nothing(redis, ran):
    await _deliver(_delivery(fromMe=True))

    assert await redis.hgetall("wa:lids:conn-1") == {}


@pytest.mark.asyncio
async def test_a_group_writer_is_known_by_their_own_lid(redis, ran):
    await _deliver(_delivery(sender="120000000000000001@g.us", participant=LID))

    assert await redis.hgetall("wa:lids:conn-1") == {LID.encode(): b"12025550101"}
    result = await run_node_op_tool(_send_tool(), {"to": LID, "body": "hello"}, user_id="u1", workflow_id="wf1")
    assert result == {"status": "success"}


@pytest.mark.asyncio
async def test_an_allowed_lid_takes_its_number_and_a_number_its_spellings(redis, ran):
    await _deliver(_delivery())
    tool = _send_tool(to=LID)

    assert await field_scope_refusal({"to": "+1 202 555 0101"}, tool, user_id="u1") is None
    assert await field_scope_refusal({"to": "12025550101@s.whatsapp.net"}, _send_tool(), user_id="u1") is None
    assert "restricted" in await field_scope_refusal({"to": "120000000000000001@g.us"}, tool, user_id="u1")


@pytest.mark.asyncio
async def test_without_redis_a_lid_is_judged_by_its_id_alone(monkeypatch, ran):
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: None)
    await _deliver(_delivery())

    assert "restricted" in await field_scope_refusal({"to": LID}, _send_tool(), user_id="u1")
    assert await field_scope_refusal({"to": ALLOWED}, _send_tool(), user_id="u1") is None


@pytest.mark.asyncio
async def test_a_node_that_knows_no_other_ids_never_reads_its_credential(monkeypatch):
    async def credential(*args, **kwargs):
        raise AssertionError("read a credential to compare plain ids")

    monkeypatch.setattr(run_op, "resolve_operation_credential", credential)
    tool = {"node_type": "automation-google-docs", "credential_id": "cred-1",
            "field_scopes": {"document_id": ["doc_abc"]}}

    assert "restricted" in await field_scope_refusal({"document_id": "doc_x"}, tool, user_id="u1")


def test_a_chat_number_reads_every_spelling_and_no_lid():
    assert chat_number("+1 (202) 555-0101") == "12025550101"
    assert chat_number("12025550101:3@s.whatsapp.net") == "12025550101"
    assert chat_number("12025550101@c.us") == "12025550101"
    assert chat_number(LID) is None
    assert chat_number("120000000000000001@g.us") is None
    assert chat_number("") is None
