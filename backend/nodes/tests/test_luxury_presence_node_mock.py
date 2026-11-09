"""Exercise native Luxury Presence execution using documented response fixtures.

These tests pin wire methods, body names, pagination, manual credentials and error handling without a live account.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import luxury_presence_node as lp
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "luxury_presence_api_key", "api_key": "fixture-not-a-live-key"}
ID = "21293a39-185c-4b5d-8171-994881cd5150"
AGENT = "f534988e-4671-4709-bb82-c06bc8b02d87"
RESPONSES = json.loads((Path(__file__).parent / "fixtures/luxury-presence/responses.json").read_text())


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        calls.append(request)
        assert request.url.host == "api.luxurypresence.com"
        assert request.headers["x-api-key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload) if payload is not None else httpx.Response(code)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(lp, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, **arguments):
    node = NodeFactory.create_node(node_id="luxury-presence-test", node_type="automation-luxury-presence",
        node_data={"config": {"operation": operation, **arguments}, "credentials": AUTH})
    return await node.execute({})


CASES = []
for noun in ["agent", "office", "team"]:
    plural = noun + "s"
    CASES.extend([
        ("list_" + plural, {}, "GET", f"/cms/v1/{plural}", {"offset": "0", "limit": "100"}, None),
        ("get_" + noun, {"resource_id": ID}, "GET", f"/cms/v1/{plural}/{{id}}", {}, None),
        ("create_" + noun, {"email": "email@example.com", **({"first_name": "John", "last_name": "Doe"} if noun == "agent" else {"name": "Beach Office"})}, "POST", f"/cms/v1/{plural}", {} if noun == "office" else {"doNotAllowDuplicates": "true"}, {"email": "email@example.com", **({"firstName": "John", "lastName": "Doe"} if noun == "agent" else {"name": "Beach Office"})}),
        ("update_" + noun, {"resource_id": ID, "phone_number": "123-435-5321"}, "PATCH", f"/cms/v1/{plural}/{{id}}", {} if noun == "office" else {"doNotAllowDuplicates": "true"}, {"phoneNumber": "123-435-5321"}),
        ("delete_" + noun, {"resource_id": ID}, "DELETE", f"/cms/v1/{plural}/{{id}}", {}, None),
    ])
for noun in ["office", "team"]:
    path = f"/cms/v1/{noun}s/{{id}}/agents"
    CASES.extend([
        ("list_" + noun + "_agents", {"resource_id": ID}, "GET", path, {"offset": "0", "limit": "100"}, None),
        ("add_" + noun + "_agents", {"resource_id": ID, "agent_ids": [AGENT]}, "POST", path, {}, {"agentIds": [AGENT]}),
        ("remove_" + noun + "_agents", {"resource_id": ID, "agent_ids": [AGENT]}, "DELETE", path, {}, {"agentIds": [AGENT]}),
    ])
CASES.extend([
    ("get_media", {"resource_id": ID}, "GET", "/cms/v1/media/{mediaId}", {}, None),
    ("list_webhooks", {}, "GET", "/crm/v1/webhooks", {}, None),
    ("create_webhook", {"name": "My Webhook", "url": "https://example.com/webhook", "secret": "my-webhook-secret"}, "POST", "/crm/v1/webhooks", {}, {"name": "My Webhook", "url": "https://example.com/webhook", "secret": "my-webhook-secret", "events": ["leads"], "isActive": True}),
    ("delete_webhook", {"resource_id": ID}, "DELETE", "/crm/v1/webhooks/{id}", {}, None),
])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,params,body", CASES, ids=[c[0] for c in CASES])
async def test_luxury_presence_wire_contract(transport, operation, arguments, method, path, params, body):
    calls, replies = transport
    payload = RESPONSES.get(method + " " + path, [] if operation.startswith("list_") else {})
    code = 204 if operation == "delete_webhook" else 201 if operation.startswith("create_") else 200
    replies.append((code, None if code == 204 else payload))
    result = await run(operation, **arguments)
    assert result["status"] == "success"
    expected = None if code == 204 else lp._redact_secrets(payload) if "webhook" in operation else payload
    assert result["data"] == expected
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.path == path.replace("{id}", ID).replace("{mediaId}", ID)
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    assert not replies


def test_luxury_presence_all_operations_covered():
    assert {case[0] for case in CASES} == set(lp.ROUTES)
    assert len(CASES) == 25
    assert lp.LuxuryPresenceApiKeyCredential(api_key="fixture-key").credential_type == "luxury_presence_api_key"
    assert lp.LuxuryPresenceNode.connection_evidence.operation == "list_agents"


@pytest.mark.asyncio
async def test_luxury_presence_filters_and_pagination(transport):
    calls, replies = transport
    replies.append((200, {"items": [{"agentId": ID}], "count": 2}))
    result = await run("list_agents", limit=1, offset=1, external_source="crm", external_ids=["one", "two"], tags=["premium", "agent"], tags_mode="ALL", emails=["email@example.com"])
    assert result["next_offset"] == 2
    assert calls[0].url.params.get_list("tags") == ["premium", "agent"]
    assert calls[0].url.params.get_list("externalIds") == ["one", "two"]
    assert calls[0].url.params["tagsMode"] == "ALL"


@pytest.mark.asyncio
async def test_luxury_presence_rejected_key_is_an_error(transport):
    _, replies = transport
    replies.append((401, {"message": "Invalid API key"}))
    with pytest.raises(ValueError, match="Invalid API key"):
        await run("list_agents")


@pytest.mark.asyncio
async def test_luxury_presence_redacts_webhook_signing_secrets(transport):
    _, replies = transport
    replies.append((200, [{"id": ID, "secret": "private-signing-secret", "headers": {"Authorization": "private"}}]))
    result = await run("list_webhooks")
    assert result["items"] == [{"id": ID}]
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_luxury_presence_empty_page_and_delete_action(transport):
    calls, replies = transport
    replies.extend([(200, {"items": [], "count": 0}), (200, None)])
    assert (await run("list_agents"))["next_offset"] is None
    await run("delete_agent", resource_id=ID, action="archive")
    assert calls[-1].url.params["action"] == "archive"


@pytest.mark.parametrize("operation,arguments", [
    ("get_agent", {"resource_id": "../offices"}),
    ("create_agent", {"email": "email@example.com"}),
    ("add_team_agents", {"resource_id": ID, "agent_ids": ["not-a-uuid"]}),
    ("create_webhook", {"name": "My Webhook", "url": "http://example.com/webhook"}),
])
def test_luxury_presence_invalid_input_is_refused(operation, arguments):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="luxury-presence-invalid", node_type="automation-luxury-presence",
            node_data={"config": {"operation": operation, **arguments}, "credentials": AUTH})


@pytest.mark.asyncio
async def test_luxury_presence_manual_connect_evidence(transport):
    from nodes.core.connection_evidence import collect_evidence

    _, replies = transport
    replies.extend([(200, RESPONSES["GET /cms/v1/agents"]), (401, {"message": "Invalid API key"})])
    accepted = await collect_evidence(node_type="automation-luxury-presence", user_id=ID, credential_data=AUTH)
    assert accepted.reachable is True
    assert accepted.samples[0].label == "Desiree"
    rejected = await collect_evidence(node_type="automation-luxury-presence", user_id=ID, credential_data=AUTH)
    assert rejected.reachable is False
    assert "Invalid API key" in rejected.error


@pytest.mark.asyncio
async def test_luxury_presence_provider_error_does_not_echo_key(transport):
    _, replies = transport
    replies.append((401, {"message": "Invalid API key " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as error:
        await run("list_agents")
    assert AUTH["api_key"] not in str(error.value)
