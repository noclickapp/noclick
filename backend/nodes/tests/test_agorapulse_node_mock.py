"""Exercise Agorapulse through the real node factory with isolated HTTP.

Contract-shaped item fixtures cover the polling window, baselining and agent text;
write assertions pin the provider's required bodies and error handling.
"""
import json
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import agorapulse_node as ap
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

AUTH = {"credential_type": "agorapulse_api_key", "api_key": "fixture-agorapulse-key"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.agorapulse.com"
        assert request.headers["X-API-KEY"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload) if payload is not None else httpx.Response(code)

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(send)) as conn:
            yield conn

    monkeypatch.setattr(ap, "guarded_async_client", client)
    return requests, replies


def node(operation, **values):
    return NodeFactory.create_node(node_id="agorapulse-test", node_type="automation-agorapulse",
        node_data={"config": {"operation": operation, **values}, "credentials": AUTH})


@pytest.mark.asyncio
async def test_connection_evidence_returns_account_organizations(transport):
    requests, replies = transport
    expected = {"organizations": [{"organizationId": 12, "organizationName": "Social team", "managerOrganizationRole": "ADMIN"}]}
    replies.append((200, expected))
    assert await node("list_organizations").execute({}) == expected
    assert requests[0].url.path == "/v1.0/core/organizations"
    assert ap.AgorapulseNode.connection_evidence.operation == "list_organizations"


@pytest.mark.asyncio
async def test_connect_evidence_names_the_organization(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {"organizations": [{"organizationId": 12,
        "organizationName": "Social team", "managerOrganizationRole": "ADMIN"}]}))
    evidence = await collect_evidence(node_type="automation-agorapulse", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ["Social team"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method", [("create_calendar_note", "POST"), ("update_calendar_note", "PUT")])
async def test_note_write_body_and_profile_detachment(transport, operation, method):
    requests, replies = transport
    replies.append((200, {"uid": "note123"}))
    body = {"title": "Team Meeting", "body": "Discuss quarterly goals and roadmap", "color": "BLUE",
        "startDate": "2024-01-15", "endDate": "2024-01-15", "profileUids": []}
    await node(operation, organizationId=12, workspaceId=34,
        **({"uid": "note123"} if method == "PUT" else {}), **body).execute({})
    request = requests[0]
    assert request.method == method
    assert request.url.path == "/v1.0/publishing/organizations/12/workspaces/34/notes" + ("/note123" if method == "PUT" else "")
    assert json.loads(request.content) == body


@pytest.mark.asyncio
async def test_reply_body_and_delete_204(transport):
    requests, replies = transport
    replies.extend([(200, {"id": "reply123"}), (204, None)])
    await node("reply_to_item", organizationId=12, workspaceId=34, profileUid="profile123",
        itemId="item123", message="Thank you for your message!", privateReply=True).execute({})
    assert requests[0].url.path.endswith("/profiles/profile123/reply")
    assert json.loads(requests[0].content) == {"itemId": "item123", "message": "Thank you for your message!", "privateReply": True}
    assert await node("delete_calendar_note", organizationId=12, workspaceId=34, uid="note123").execute({}) == {"success": True}
    assert requests[1].method == "DELETE"


@pytest.mark.asyncio
async def test_array_query_serialization(transport):
    requests, replies = transport
    replies.append((200, {"items": [], "offset": ""}))
    await node("list_inbox_items", organizationId=12, workspaceId=34,
        profileUids=["profile1", "profile2"], limit=25, order="DESC").execute({})
    assert requests[0].url.params.get_list("profileUids") == ["profile1", "profile2"]
    assert requests[0].url.params["order"] == "DESC"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_inbox_item", "on_new_listening_item"])
async def test_poll_contract_items_window_baseline_dedup_and_agent_event(transport, operation):
    requests, replies = transport
    fixture = json.loads((Path(__file__).parent / 'fixtures/agorapulse/items.json').read_text())
    config = {"organizationId": 12, "workspaceId": 34, "since": "2026-08-01T09:00:00.000Z"}
    if "listening" in operation:
        config["searchId"] = "search123"
    instance = node(operation, **config)
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    instance._update_node_state = update
    replies.append((200, fixture))
    assert (await instance.execute({}))["items"] == []
    new_item = {**fixture["items"][0], "id": "new-item"}
    replies.append((200, {"items": [new_item], "offset": "page2"}))
    result = await instance.execute({})
    assert result["items"] == [new_item]
    assert "offset" not in requests[-1].url.params
    assert requests[-1].url.params["limit"] == "25"
    event = ap.AgorapulseNode.resolve_agent_event(result)
    assert "new-item" in event["text"] and new_item["text"] in event["text"]
    replies.append((200, {"items": [new_item], "offset": ""}))
    assert (await instance.execute({}))["items"] == []
    assert instance.trigger_produced_no_event({}) is True
    assert requests[0].url.params["since"] == config["since"]
    if "listening" in operation:
        assert requests[0].url.params["orderBy"] == "DATE"
    assert poll_scope(ap.AgorapulseNode, {"operation": operation, **config}) == poll_scope(ap.AgorapulseNode, {"operation": operation, **config, "label": "Renamed"})
    assert poll_scope(ap.AgorapulseNode, {"operation": operation, **config}) != poll_scope(ap.AgorapulseNode, {"operation": operation, **config, "workspaceId": 35})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_errors_propagate(transport, status):
    _, replies = transport
    replies.append((status, {"code": 2, "message": "Rejected"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node("list_organizations").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "a/b", "a%2Fb", "https://foreign.test"])
async def test_path_injection_refused_before_transport(transport, identifier):
    with pytest.raises(ValueError, match="resource ID"):
        await node("get_inbox_item", organizationId=12, workspaceId=34, profileUid=identifier, itemId="item123").execute({})
    assert transport[0] == []


def test_manual_credential_default_and_invalid_secret():
    assert ap.AgorapulseAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "agorapulse_api_key"
    for bad in ["https://example.test/key", "invalid\nkey", "<token>"]:
        with pytest.raises((ValidationError, ValueError)):
            ap.AgorapulseAPIKeyCredential(api_key=bad)
