"""An agent is offered only the operations its provider's credential can run.

A WhatsApp QR link (a linked phone) has no Cloud API, so its agents called
``get_media_url`` and the like only to read "requires Meta Cloud API credentials";
the Cloud API reads no chats either way round.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from nodes.agent.node_op_tools import describe_provider_credential
from nodes.whatsapp_node import QR_ONLY_OPERATIONS, QR_OPERATIONS, WhatsAppNode
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

SEND = {"operation": "send_text_message", "field_scopes": {"to": ["12025550101@c.us"]}}
ALLOWED = [SEND, "get_media_url", "mark_message_read", "get_chat_messages"]


class _Pool:
    def __init__(self, row):
        self.row = row

    @asynccontextmanager
    async def acquire(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = self.row
        yield conn


def _provider(allowed=ALLOWED):
    return {
        "id": "wa-1",
        "type": "automation-whatsapp",
        "config": {
            "label": "WhatsApp",
            "agent_tool_operations": allowed,
            "credentialIds": {"whatsapp": "11111111-1111-1111-1111-111111111111"},
        },
    }


AGENT = {"id": "agent-1", "type": "agent", "config": {"model": "openai/gpt-4o", "message": "hi"}}
WIRE = {"id": "w", "source": "wa-1", "target": "agent-1", "sourceHandle": "top", "targetHandle": "bottom"}


async def _published(row):
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler.get_pool = AsyncMock(return_value=_Pool(row))
    _, error, outputs = await handler._execute_nodes_concurrent(
        [_provider()], [], "sid", "user", "wf", workflow_graph=([_provider(), AGENT], [WIRE]),
    )
    assert error is None, error
    return outputs["wa-1"]


@pytest.mark.asyncio
async def test_a_qr_link_is_offered_none_of_the_cloud_apis_operations():
    out = await _published({"name": "Shop phone", "credential_type": "whatsapp_qr"})

    assert out["allowed_operations"] == [SEND, "get_chat_messages"]  # an entry keeps its scopes
    assert out["credential_label"] == "Shop phone"


@pytest.mark.asyncio
async def test_the_cloud_api_is_offered_none_of_a_linked_phones_chat_reads():
    out = await _published({"name": "Business", "credential_type": "whatsapp_access_token"})

    assert out["allowed_operations"] == [SEND, "get_media_url", "mark_message_read"]


@pytest.mark.asyncio
async def test_a_credential_that_cannot_be_read_takes_nothing_away():
    out = await _published(None)

    assert out["allowed_operations"] == ALLOWED
    assert "credential_label" not in out


@pytest.mark.asyncio
async def test_a_node_whose_credentials_all_run_everything_keeps_its_allowlist():
    output = {"node_type": "automation-linear", "credential_id": "22222222-2222-2222-2222-222222222222",
              "allowed_operations": ["create_issue"]}
    await describe_provider_credential(_Pool({"name": "Work", "credential_type": "linear_api_key"}), output)

    assert output["allowed_operations"] == ["create_issue"]
    assert output["credential_label"] == "Work"


def test_whatsapp_runs_each_operation_on_the_connection_that_has_it():
    for operation in QR_OPERATIONS - QR_ONLY_OPERATIONS:
        assert WhatsAppNode.operation_credential_types(operation) is None
    for operation in QR_ONLY_OPERATIONS:
        assert WhatsAppNode.operation_credential_types(operation) == {"whatsapp_qr"}
    for operation in ("get_media_url", "send_template_message", "get_business_profile"):
        assert WhatsAppNode.operation_credential_types(operation) == {"whatsapp_access_token"}
    assert WhatsAppNode.operation_credential_types("receive_message") is None
