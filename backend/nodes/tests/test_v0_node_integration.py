"""V0 through the platform's unsaved credential and operation dispatch seams."""
import pytest

from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential
from nodes.core.run_op import run_node_operation
from nodes.tests.test_v0_node_mock import AUTH, transport


@pytest.mark.asyncio
async def test_v0_manual_connect_evidence_is_account_chat_data(monkeypatch):
    requests = transport(monkeypatch, {"chats": [{"id": "chat-one", "title": "Owned dashboard"}]})
    evidence = await collect_evidence(node_type="automation-v0", credential_data=AUTH, user_id="synthetic-user")
    assert evidence.reachable is True
    assert "Owned dashboard" in str(evidence)
    assert len(requests) == 1 and requests[0].method == "GET"
    shaped, errors, _ = shape_credential("v0_api_key", {"api_key": AUTH["api_key"]})
    assert not errors and shaped["api_key"] == AUTH["api_key"]


@pytest.mark.asyncio
async def test_v0_operation_dispatch_uses_native_node(monkeypatch):
    requests = transport(monkeypatch, {"messageId": "message-one"})
    result = await run_node_operation(node_type="automation-v0", operation="stop_message",
        arguments={"chat_id": "chat-one", "message_id": "message-one"}, credential_data=AUTH,
        user_id="synthetic-user")
    assert result["data"]["messageId"] == "message-one"
    assert len(requests) == 1
