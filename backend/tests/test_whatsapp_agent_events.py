"""A linked WhatsApp number makes nothing on its own: the scan's status poll mints the credential and hands the
platform nothing. The number's agent is the platform's (``WHATSAPP_AGENT``), asked for by the app: ``whatsapp:agent:
status`` (may it offer one, and which agent answers the number already) and ``whatsapp:agent:create`` (made on the
owner's yes), each only for a WhatsApp number of the signed-in user's own."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import wss.handlers.oauth.whatsapp_qr_handler as handler_module
from utils import capabilities
from wss.receiver.client_events import WhatsAppAgentCreateRequest, WhatsAppAgentStatusRequest, WhatsAppQRStatusRequest

pytestmark = pytest.mark.asyncio

CONNECTED = {"success": True, "status": "connected", "credential_id": "cred-1", "credential_name": "WhatsApp",
             "phone_number": "+12025550123", "created": True}
AGENT = {"agent_id": "a-1", "name": "WhatsApp", "channel_id": "ch-1", "channel_name": "whatsapp"}


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(handler_module, "get_encryption", MagicMock())
    sent = AsyncMock()
    monkeypatch.setattr(handler_module, "send_event", sent)
    sio = MagicMock()
    sio.get_session = AsyncMock(return_value={"user_id": "user-1"})
    made = handler_module.WhatsAppQRHandler(sio)
    made.get_pool = AsyncMock(return_value="pool")
    made.sent = sent
    return made


@pytest.fixture
def platform(monkeypatch):
    agents = MagicMock()
    agents.status = AsyncMock(return_value={"available": True, "agent": None})
    agents.create = AsyncMock(return_value={"agent": AGENT, "created": True})
    monkeypatch.setitem(capabilities._providers, capabilities.WHATSAPP_AGENT, agents)
    return agents


@pytest.fixture
def owned(monkeypatch):
    """The credential each request names, as the user's own: a WhatsApp number unless a test says otherwise."""
    header = AsyncMock(return_value={"id": "cred-1", "name": "WhatsApp", "credential_type": "whatsapp_qr",
                                     "phone_number": "+12025550123"})
    monkeypatch.setattr(handler_module.CredentialsRepo, "get_owned_header", header)
    return header


def _answers(handler):
    return [call.args[2].data for call in handler.sent.await_args_list]


async def test_the_scan_makes_the_credential_alone(monkeypatch, handler, platform):
    monkeypatch.setattr(handler_module, "finalize_qr_connection", AsyncMock(return_value=CONNECTED))
    await handler.check_status("sid-1", WhatsAppQRStatusRequest(request_id="r1", connection_id="conn-1"))
    [reply] = _answers(handler)
    assert reply["status"] == "connected" and reply["credential_id"] == "cred-1"
    platform.create.assert_not_awaited()
    platform.status.assert_not_awaited()
    assert "ready_agent" not in WhatsAppQRStatusRequest.model_fields


async def test_status_says_whether_to_offer_and_who_answers(handler, platform, owned):
    await handler.agent_status("sid-1", WhatsAppAgentStatusRequest(request_id="r1", credential_id="cred-1"))
    platform.status.assert_awaited_once_with("pool", "user-1", "cred-1")
    platform.status.return_value = {"available": True, "agent": AGENT}
    await handler.agent_status("sid-1", WhatsAppAgentStatusRequest(request_id="r2", credential_id="cred-1"))
    offer, answered = _answers(handler)
    assert offer == {"success": True, "available": True, "agent": None, "message": None}
    assert answered["agent"] == AGENT and answered["available"] is True


async def test_create_makes_it_for_the_owners_number(handler, platform, owned):
    await handler.create_agent("sid-1", WhatsAppAgentCreateRequest(request_id="r1", credential_id="cred-1"))
    platform.create.assert_awaited_once_with("pool", "user-1", "cred-1", "+12025550123")
    owned.assert_awaited_once_with("cred-1", "user-1")
    [made] = _answers(handler)
    assert made == {"success": True, "created": True, "agent": AGENT, "message": None}


async def test_a_number_with_an_agent_answers_with_that_one(handler, platform, owned):
    platform.create.return_value = {"agent": AGENT, "created": False}
    await handler.create_agent("sid-1", WhatsAppAgentCreateRequest(request_id="r1", credential_id="cred-1"))
    [kept] = _answers(handler)
    assert kept["success"] is True and kept["created"] is False and kept["agent"] == AGENT


async def test_only_the_users_own_whatsapp_number(handler, platform, owned):
    owned.return_value = None
    await handler.create_agent("sid-1", WhatsAppAgentCreateRequest(request_id="r1", credential_id="cred-x"))
    owned.return_value = {"id": "cred-2", "name": "Gmail", "credential_type": "gmail_oauth", "phone_number": None}
    await handler.agent_status("sid-1", WhatsAppAgentStatusRequest(request_id="r2", credential_id="cred-2"))
    refused, unread = _answers(handler)
    assert refused["success"] is False and refused["agent"] is None
    assert unread["success"] is False and unread["available"] is False
    platform.create.assert_not_awaited()
    platform.status.assert_not_awaited()


async def test_a_failure_making_it_is_a_failed_answer(handler, platform, owned, caplog):
    platform.create.side_effect = RuntimeError("no channel")
    await handler.create_agent("sid-1", WhatsAppAgentCreateRequest(request_id="r1", credential_id="cred-1"))
    [failed] = _answers(handler)
    assert failed == {"success": False, "created": False, "agent": None, "message": "Couldn't create the agent"}
    assert "create_agent error" in caplog.text


async def test_without_a_platform_nothing_is_offered(monkeypatch, handler, owned):
    monkeypatch.delitem(capabilities._providers, capabilities.WHATSAPP_AGENT, raising=False)
    await handler.agent_status("sid-1", WhatsAppAgentStatusRequest(request_id="r1", credential_id="cred-1"))
    [status] = _answers(handler)
    assert status["success"] is True and status["available"] is False
