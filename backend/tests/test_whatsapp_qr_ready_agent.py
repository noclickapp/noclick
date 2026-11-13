"""A WhatsApp linked for the account itself (``ready_agent``: its connections, not a workflow's or an agent's) hands
the new link to the platform's ``WHATSAPP_LINKED`` once the scan lands, after the scan's own answer, so the number's
agent is ready at once; any other link, or a scan still waiting, hands nothing, and a failure there never turns the
scan's answer into an error."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import wss.handlers.oauth.whatsapp_qr_handler as handler_module
from utils import capabilities
from wss.receiver.client_events import WhatsAppQRStatusRequest

pytestmark = pytest.mark.asyncio

CONNECTED = {"success": True, "status": "connected", "credential_id": "cred-1", "credential_name": "WhatsApp",
             "phone_number": "+12025550123", "created": True}


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
def ready(monkeypatch):
    linked = AsyncMock(return_value={"agent": {"id": "a-1"}})
    monkeypatch.setitem(capabilities._providers, capabilities.WHATSAPP_LINKED, linked)
    return linked


def _finalize(monkeypatch, result):
    monkeypatch.setattr(handler_module, "finalize_qr_connection", AsyncMock(return_value=result))


async def _poll(handler, **fields):
    await handler.check_status("sid-1", WhatsAppQRStatusRequest(request_id="r1", connection_id="conn-1", **fields))
    return [call.args[2].data for call in handler.sent.await_args_list]


async def test_a_number_linked_for_the_account_gets_its_agent_after_the_scans_answer(monkeypatch, handler, ready):
    _finalize(monkeypatch, CONNECTED)
    [reply] = await _poll(handler, ready_agent=True)
    assert reply["status"] == "connected" and reply["credential_id"] == "cred-1"
    ready.assert_awaited_once_with("pool", "user-1", "cred-1", "+12025550123")


async def test_a_link_for_a_workflow_or_an_agent_hands_nothing(monkeypatch, handler, ready):
    _finalize(monkeypatch, CONNECTED)
    await _poll(handler)
    ready.assert_not_awaited()


async def test_a_scan_still_waiting_hands_nothing(monkeypatch, handler, ready):
    _finalize(monkeypatch, {"success": True, "status": "pending", "qr_code": "QR"})
    await _poll(handler, ready_agent=True)
    ready.assert_not_awaited()


async def test_a_failure_readying_the_agent_never_fails_the_scan(monkeypatch, handler, ready, caplog):
    _finalize(monkeypatch, CONNECTED)
    ready.side_effect = RuntimeError("no channel")
    [reply] = await _poll(handler, ready_agent=True)
    assert reply["status"] == "connected"
    assert "readying the agent of credential cred-1 failed" in caplog.text


async def test_without_a_platform_linking_makes_the_credential_alone(monkeypatch, handler):
    monkeypatch.delitem(capabilities._providers, capabilities.WHATSAPP_LINKED, raising=False)
    _finalize(monkeypatch, CONNECTED)
    [reply] = await _poll(handler, ready_agent=True)
    assert reply["status"] == "connected"
