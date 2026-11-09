"""Exercise the production factory and transport against Cliengo's published routes."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import cliengo_node as cliengo
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = "sk_live_synthetic_cliengo_contract_token"
AUTH = {"credential_type": "cliengo_api_token", "api_token": TOKEN}
ROUTES = json.loads((Path(__file__).parent / "fixtures/cliengo/operations.json").read_text())
CONTACT = "60a1b2c3d4e5f6a7b8c9d0e1"
CONVERSATION = "626e9cc66ac98128162b2bbc"
CHANNEL = "5f08e255c9a881002afc06ec"
CASES = {
    "get_account": {}, "search_contacts": {"email": "juan@example.com", "page": 2, "limit": 20},
    "create_contact": {"website_id": CHANNEL, "name": "Juan Pérez", "email": "juan@example.com", "custom_fields": {"interest": "demo"}},
    "get_contact": {"contact_id": CONTACT},
    "update_contact": {"contact_id": CONTACT, "name": "Juan Pérez", "assigned_to": "agent1"},
    "delete_contact": {"contact_id": CONTACT}, "list_contact_notes": {"contact_id": CONTACT},
    "create_contact_note": {"contact_id": CONTACT, "message": "Follow up tomorrow"},
    "add_contact_tag": {"contact_id": CONTACT, "tag": "qualified"},
    "get_contact_history": {"contact_id": CONTACT},
    "list_conversations": {"page": 2, "limit": 20, "status": "opened"},
    "get_conversation": {"conversation_id": CONVERSATION},
    "list_conversation_messages": {"conversation_id": CONVERSATION, "include_commands": False},
    "send_conversation_message": {"conversation_id": CONVERSATION, "sender_id": "agent1", "from_type": "user", "message_type": "text/plain", "body": "Hola, necesito ayuda"},
    "assign_conversation": {"conversation_id": CONVERSATION, "assigned_to": "agent1"},
    "close_conversation": {"conversation_id": CONVERSATION, "is_lead": False},
    "open_conversation": {"conversation_id": CONVERSATION}, "list_tags": {},
    "create_tag": {"name": "qualified", "color": "#00FF00"}, "list_phases": {},
    "assign_conversation_phase": {"conversation_id": CONVERSATION, "phase_id": "phase1"},
    "list_channels": {}, "list_users": {"offset": 20, "limit": 20}, "list_teams": {},
    "list_whatsapp_templates": {"channel_id": CHANNEL},
}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(cliengo, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=AUTH):
    return await run_node_operation(node_type="automation-cliengo", operation=operation,
        arguments=arguments or {}, credential_data=credential,
        user_id="00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_all_published_routes(transport, operation):
    requests, replies = transport
    replies.append((200, {"id": "fixture", "name": "Fixture account"}))
    result = await run(operation, CASES[operation])
    request = requests[0]
    route = ROUTES[operation]
    expected_path = route["path"].replace("{contactId}", CONTACT).replace("{conversationId}", CONVERSATION).replace("{channelId}", CHANNEL).replace("{phaseId}", "phase1")
    assert request.method == route["method"] and request.url.path == expected_path
    assert request.url.host == "connect.cliengo.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url)
    assert result["id"] == "fixture" and replies == [] and len(requests) == 1


@pytest.mark.asyncio
async def test_wire_names_required_fields_and_false_are_preserved(transport):
    requests, replies = transport
    for operation in ["create_contact", "send_conversation_message", "close_conversation", "assign_conversation"]:
        replies.append((200, {"id": "fixture"}))
        await run(operation, CASES[operation])
    assert json.loads(requests[0].content) == {"websiteId": CHANNEL, "name": "Juan Pérez", "email": "juan@example.com", "customFields": {"interest": "demo"}}
    assert json.loads(requests[1].content) == {"from": "agent1", "fromType": "user", "type": "text/plain", "body": "Hola, necesito ayuda"}
    assert json.loads(requests[2].content) == {"isLead": False}
    assert json.loads(requests[3].content) == {"assignedTo": "agent1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"data": {CONVERSATION: {"id": CONVERSATION}}, "pagination": {"hasNext": True, "page": 2}}, {"data": [], "pagination": {"total": 0}}, {"name": "My account", "id": "account1"}])
async def test_documented_envelopes_are_not_flattened(transport, payload):
    transport[1].append((200, payload))
    assert await run("get_account") == (payload if isinstance(payload, dict) else {"data": payload})


@pytest.mark.asyncio
async def test_sandbox_token_selects_only_documented_sandbox(transport):
    transport[1].append((200, {"name": "Sandbox"}))
    await run("get_account", credential={**AUTH, "api_token": "sk_test_synthetic_cliengo_token"})
    assert transport[0][0].url.host == "connect.stagecliengo.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"message": "token " + TOKEN}), (403, {"message": "clients_write required"}), (429, {"message": "rate limit"}), (500, {"message": "failed"}), (302, b""), (200, b"<html>Sign in</html>"), (200, {"error": "Forbidden"})])
async def test_errors_are_not_successful_or_retried(transport, status, payload):
    transport[1].append((status, payload))
    with pytest.raises(ValueError) as exc:
        await run("create_contact", CASES["create_contact"])
    assert TOKEN not in str(exc.value) and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["..", "a/b", "a%2Fb", "https://example.com", "x\n"])
async def test_invalid_path_id_never_reaches_transport(transport, bad):
    with pytest.raises(ValueError):
        await run("get_contact", {"contact_id": bad})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_missing_required_body_never_reaches_transport(transport):
    with pytest.raises(ValueError):
        await run("close_conversation", {"conversation_id": CONVERSATION})
    assert transport[0] == []


def test_credential_can_be_shaped_by_hand():
    credential = cliengo.CliengoAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == "cliengo_api_token"


@pytest.mark.asyncio
async def test_search_dates_and_multi_channel_filter_keep_their_wire_types(transport):
    transport[1].append((200, {"data": [], "pagination": {"hasNext": False}}))
    await run("search_contacts", {"date_from": "2026-10-01T00:00:00Z", "website_id": "channel1,channel2"})
    assert transport[0][0].url.params["dateFrom"] == "2026-10-01T00:00:00Z"
    assert transport[0][0].url.params["websiteId"] == "channel1,channel2"
    with pytest.raises(ValueError):
        await run("list_conversations", {"from_date": "2026-10-01T00:00:00"})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_conversation_pagination_sends_only_the_selected_strategy(transport):
    for arguments in ({"page": 2}, {"offset": 40, "limit": 20}):
        transport[1].append((200, {"data": {}, "pagination": {"hasNext": False}}))
        await run("list_conversations", arguments)
    first, second = transport[0]
    assert first.url.params["page"] == "2" and "offset" not in first.url.params
    assert second.url.params["offset"] == "40" and "page" not in second.url.params
