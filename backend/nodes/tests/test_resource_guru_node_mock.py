"""Exercise Resource Guru's actual node factory against an in-memory HTTP transport.

The webhook fixture is copied from the provider's published webhook documentation.
"""
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import resource_guru_node as rg
from nodes.core.run_op import run_node_operation
from nodes.oauth.resource_guru_oauth import OAUTH_PROVIDER

AUTH = {"credential_type": "resource_guru_oauth", "access_token": "fixture-resource-guru-token"}
ACCOUNT = {"account": "example-corp"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/resource-guru/client-created.json").read_text())

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    original = httpx.AsyncClient
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.resourceguruapp.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload) if payload is not None else httpx.Response(code)
    monkeypatch.setattr(rg.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(op, args=None):
    return await run_node_operation(node_type="automation-resource-guru", operation=op,
        arguments=args or {}, credential_data=dict(AUTH), user_id="00000000-0000-4000-8000-000000000001")

CASES = [
    ("get_me", {}, "GET", "/v1/me"),
    ("list_accounts", {}, "GET", "/v1/accounts"),
    ("list_bookings", ACCOUNT, "GET", "/v1/example-corp/bookings"),
    ("get_booking", {**ACCOUNT, "id": 1}, "GET", "/v1/example-corp/bookings/1"),
    ("create_booking", {**ACCOUNT, "resource_id": 1, "start_date": "2020-12-31", "end_date": "2020-12-31", "duration": 60}, "POST", "/v1/example-corp/bookings"),
    ("update_booking", {**ACCOUNT, "id": 1, "details": "Changed"}, "PUT", "/v1/example-corp/bookings/1"),
    ("delete_booking", {**ACCOUNT, "id": 1}, "DELETE", "/v1/example-corp/bookings/1"),
    ("list_clients", ACCOUNT, "GET", "/v1/example-corp/clients"),
    ("get_client", {**ACCOUNT, "id": 1}, "GET", "/v1/example-corp/clients/1"),
    ("create_client", {**ACCOUNT, "name": "A client"}, "POST", "/v1/example-corp/clients"),
    ("update_client", {**ACCOUNT, "id": 1, "archived": False}, "PUT", "/v1/example-corp/clients/1"),
    ("delete_client", {**ACCOUNT, "id": 1}, "DELETE", "/v1/example-corp/clients/1"),
    ("list_projects", ACCOUNT, "GET", "/v1/example-corp/projects"),
    ("get_project", {**ACCOUNT, "id": 1}, "GET", "/v1/example-corp/projects/1"),
    ("create_project", {**ACCOUNT, "name": "A project"}, "POST", "/v1/example-corp/projects"),
    ("update_project", {**ACCOUNT, "id": 1, "client_id": 2}, "PUT", "/v1/example-corp/projects/1"),
    ("delete_project", {**ACCOUNT, "id": 1}, "DELETE", "/v1/example-corp/projects/1"),
    ("list_resources", ACCOUNT, "GET", "/v1/example-corp/resources"),
    ("get_resource", {**ACCOUNT, "id": 1}, "GET", "/v1/example-corp/resources/1"),
    ("create_resource", {**ACCOUNT, "resource_type_id": 1, "first_name": "Joe", "last_name": "Bloggs"}, "POST", "/v1/example-corp/resources"),
    ("update_resource", {**ACCOUNT, "id": 1, "notes": "Changed"}, "PUT", "/v1/example-corp/resources/1"),
    ("list_downtimes", {**ACCOUNT, "from_date": "2020-01-01", "to_date": "2020-12-31"}, "GET", "/v1/example-corp/downtimes"),
    ("create_downtime", {**ACCOUNT, "resource_id": 1, "from_date": "2020-12-31", "to_date": "2020-12-31", "start_time": 540, "end_time": 1020}, "POST", "/v1/example-corp/downtimes"),
    ("delete_downtime", {**ACCOUNT, "id": 1}, "DELETE", "/v1/example-corp/downtimes/1"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path", CASES)
async def test_actions_through_native_factory(transport, operation, args, method, path):
    requests, replies = transport
    expected = [{"id": 1}] if operation.startswith("list_") else {"id": 1}
    replies.append((200, expected))
    result = await run(operation, args)
    assert result["data"] == expected
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    if operation.startswith("list_") and "account" in args:
        assert request.url.params["limit"] == "50"
        assert request.url.params["offset"] == "0"
    if operation == "create_downtime":
        assert json.loads(request.content) == {"resource_ids": [1], "from": "2020-12-31", "to": "2020-12-31", "start_time": 540, "end_time": 1020}
    if operation == "list_downtimes":
        assert request.url.params["from"] == "2020-01-01"
        assert request.url.params["to"] == "2020-12-31"
    if operation == "update_client":
        assert json.loads(request.content) == {"archived": False}

@pytest.mark.asyncio
async def test_empty_delete_and_provider_rejection(transport):
    requests, replies = transport
    replies.extend([(204, None), (401, {"errors": [{"message": "Invalid token"}]})])
    assert (await run("delete_client", {**ACCOUNT, "id": 1}))["data"] == {"ok": True}
    with pytest.raises(ValueError, match="Invalid token"):
        await run("get_me")

@pytest.mark.parametrize("account", ["../other", "a/b", "https://foreign.test", "a?x=1"])
def test_path_segments_refuse_traversal(account):
    with pytest.raises(ValidationError):
        rg.ResourceGuruNodeConfig.model_validate({"config": {"operation": "list_clients", "account": account}, "credentials": AUTH})

@pytest.mark.asyncio
async def test_signed_registration_delivery_and_cleanup(transport):
    requests, replies = transport
    replies.extend([(201, {"id": 9}), (204, None)])
    config = {**ACCOUNT, "operation": "on_client_changed"}
    state = await rg.ResourceGuruNode._register_external_webhook(
        webhook_url="https://hooks.hooks.example.test/fixture", credential=AUTH, config=config, node_id="fixture")
    sent = json.loads(requests[0].content)
    assert sent == {"name": "NoClick fixture", "payload_url": "https://hooks.hooks.example.test/fixture", "events": ["clients"],
        "secret": state["signing_secret"], "send_secret_header": False, "paused": False}
    config.update(state)
    body = json.dumps(FIXTURE).encode()
    sig = hmac.new(state["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-ResourceGuru-Signature": sig}
    assert rg.ResourceGuruNode.verify_webhook_signature(body, headers, config)
    assert not rg.ResourceGuruNode.verify_webhook_signature(body + b" ", headers, config)
    assert not rg.ResourceGuruNode.verify_webhook_signature(body, {}, config)
    assert not rg.ResourceGuruNode.verify_webhook_signature(body, headers, {})
    assert not rg.ResourceGuruNode.verify_webhook_signature(body, {"X-ResourceGuru-Signature": "é" * 64}, config)
    assert rg.ResourceGuruNode.filter_trigger_payload(FIXTURE, config)
    output = rg.ResourceGuruNode.resolve_trigger_payload(FIXTURE, config)
    turn = rg.ResourceGuruNode.resolve_agent_event(output)
    assert "A client" in turn["text"] and "Some notes" in turn["text"]
    assert "id=1234" in turn["text"] and "example-corp" in turn["text"]
    assert turn["conversation_key"] == "example-corp:client:1234"
    await rg.ResourceGuruNode._unregister_external_webhook(credential=AUTH, config=config, node_id="fixture")
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/v1/example-corp/webhooks/9"

@pytest.mark.parametrize("payload", [{}, {"payload": {"id": 1, "type": "booking", "action": "create"}}, {"payload": {"id": 1, "type": "client", "action": "other"}}])
def test_unrelated_delivery_does_not_fire(payload):
    assert not rg.ResourceGuruNode.filter_trigger_payload(payload, ACCOUNT)

def test_oauth_and_manual_connect_contract():
    assert rg.ResourceGuruOAuthCredential(access_token="fixture-token").credential_type == "resource_guru_oauth"
    assert OAUTH_PROVIDER.identity_url == "https://api.resourceguruapp.com/v1/me"
    assert OAUTH_PROVIDER.rotates_refresh_tokens
    assert set(rg.CONFIG_MODELS) | {"on_client_changed"} == rg.RESOURCE_GURU_SCOPES.keys_declared
