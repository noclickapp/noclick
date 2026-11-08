"""Exercise Bluefox Email through the native node factory without provider calls.

These tests pin each supported route and its payload, connection evidence,
pagination and failure behavior against representative provider envelopes.
"""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import bluefox_email_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

TOKEN = "bluefox-test-secret-42"
CREDENTIAL = {"credential_type": "bluefox_email_api_key", "api_key": TOKEN, "project_id": "project-42"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="bluefox-test", node_type="automation-bluefox-email", node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# One representative native config and the exact method/path/body per operation.
CASES = [
    ({"operation": "get_project"}, "GET", "", None),
    ({"operation": "list_contacts"}, "GET", "/contacts", None),
    ({"operation": "get_contact", "email": "alice+news@example.com"}, "GET", "/contacts/alice+news@example.com", None),
    ({"operation": "create_contact", "email": "a@example.com", "name": "Alice", "tags": ["customer"], "custom_fields": {"plan": "pro"}}, "POST", "/contacts", {"email": "a@example.com", "name": "Alice", "tags": ["customer"], "plan": "pro"}),
    ({"operation": "update_contact", "email": "a@example.com", "tags": []}, "PATCH", "/contacts/a@example.com", {"tags": []}),
    ({"operation": "delete_contact", "email": "a@example.com"}, "DELETE", "/contacts/a@example.com", None),
    ({"operation": "list_subscriber_lists"}, "GET", "/subscriber-lists", None),
    ({"operation": "get_subscriber_list", "list_id": "audience"}, "GET", "/subscriber-lists/audience", None),
    ({"operation": "create_subscriber_list", "name": "News", "description": "Product news"}, "POST", "/subscriber-lists", {"name": "News", "description": "Product news", "private": False}),
    ({"operation": "update_subscriber_list", "list_id": "audience", "private": False}, "PATCH", "/subscriber-lists/audience", {"private": False}),
    ({"operation": "delete_subscriber_list", "list_id": "audience"}, "DELETE", "/subscriber-lists/audience", None),
    ({"operation": "list_subscribers", "list_id": "audience"}, "GET", "/subscriber-lists/audience/subscribers", None),
    ({"operation": "subscribe_contact", "list_id": "audience", "email": "a@example.com", "status": "active"}, "POST", "/subscriber-lists/audience/subscribers", {"email": "a@example.com", "status": "active"}),
    ({"operation": "get_subscriber", "list_id": "audience", "email": "a@example.com"}, "GET", "/subscriber-lists/audience/subscribers/a@example.com", None),
    ({"operation": "update_subscriber", "list_id": "audience", "email": "a@example.com", "status": "paused", "paused_until": "2099-01-01T00:00:00Z"}, "PATCH", "/subscriber-lists/audience/subscribers/a@example.com", {"status": "paused", "pausedUntil": "2099-01-01T00:00:00Z"}),
    ({"operation": "list_campaigns"}, "GET", "/campaigns", None),
    ({"operation": "get_campaign", "campaign_id": "campaign"}, "GET", "/campaigns/campaign", None),
    ({"operation": "get_campaign_stats", "campaign_id": "campaign"}, "GET", "/campaigns/campaign/stats", None),
    ({"operation": "list_transactional_emails"}, "GET", "/transactional-emails", None),
    ({"operation": "get_transactional_email", "transactional_id": "receipt"}, "GET", "/transactional-emails/receipt", None),
    ({"operation": "send_transactional_email", "transactional_id": "receipt", "email": "a@example.com", "data": {"orderId": 123}}, "POST", "/send-transactional", {"email": "a@example.com", "transactionalId": "receipt", "data": {"orderId": 123}}),
    ({"operation": "list_triggered_emails"}, "GET", "/triggered-emails", None),
    ({"operation": "get_triggered_email", "triggered_id": "welcome"}, "GET", "/triggered-emails/welcome", None),
    ({"operation": "send_triggered_email", "triggered_id": "welcome", "emails": ["a@example.com"]}, "POST", "/send-triggered", {"triggeredId": "welcome", "emails": ["a@example.com"]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_bluefox_email_each_operation_one_request(monkeypatch, config, method, path, body):
    result = {"items": [], "count": 0, "next": None} if config["operation"].startswith("list_") else {"_id": "resource", "name": "Owned project"}
    requests = transport(monkeypatch, {"status": 200, "result": result})
    output = await node(config).execute({})
    assert output["data"] == result and output["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.bluefox.email"
    assert request.url.path == "/v1/projectId/project-42" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert dict(request.url.params) == ({"limit": "10", "skip": "0"} if config["operation"].startswith("list_") else {})
    assert TOKEN not in str(output)


def test_bluefox_email_registration_and_manual_credentials():
    assert NODE_REGISTRY["automation-bluefox-email"] is native.BluefoxEmailNode
    assert native.BluefoxEmailAPIKeyCredential(api_key=TOKEN, project_id=" project-42 ").model_dump() == CREDENTIAL
    assert native.BluefoxEmailNode.connection_evidence.identity_operation == "get_project"
    assert {c[0]["operation"] for c in CASES} == set(native.ROUTES)


@pytest.mark.parametrize("changes", [{"api_key": "https://example.com/key"}, {"api_key": "Bearer token"}, {"project_id": ".."}, {"project_id": "\n"}])
def test_bluefox_email_invalid_credentials(changes):
    with pytest.raises(ValidationError):
        native.BluefoxEmailAPIKeyCredential.model_validate({**CREDENTIAL, **changes})


@pytest.mark.asyncio
async def test_bluefox_email_skip_pagination_does_not_follow_urls(monkeypatch):
    requests = transport(monkeypatch, {"status": 200, "result": {"items": [{"_id": "a", "name": "Audience"}], "count": 40, "next": "https://foreign.example/collect"}})
    output = await node({"operation": "list_subscriber_lists", "limit": 1, "skip": 8}).execute({})
    assert output["next_skip"] == 9 and output["has_more"] is True
    choices = await native.BluefoxEmailNode.load_field_options("list_id", CREDENTIAL, page_token="9")
    assert choices == {"options": [{"value": "a", "label": "Audience"}], "next_page_token": "10"}
    assert len(requests) == 2 and all(r.url.host == "api.bluefox.email" for r in requests)
    assert requests[-1].url.params["skip"] == "9"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,message", [
    (403, {"status": 403, "error": {"name": "AUTH_ERROR", "message": "Invalid API key"}}, "Invalid API key"),
    (200, {"status": 405, "error": {"message": "Insufficient credits available"}}, "Insufficient credits available"),
    (200, {"status": 200}, "missing its result"),
    (302, {"result": {}}, "rejected"),
])
async def test_bluefox_email_failed_envelopes_are_not_success(monkeypatch, status, body, message):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(ValueError, match=message):
        await node({"operation": "get_project"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_bluefox_email_double_opt_in_response_is_preserved(monkeypatch):
    result = {"success": True, "info": "Verification email sent"}
    transport(monkeypatch, {"status": 200, "result": result}, 201)
    output = await node({"operation": "subscribe_contact", "list_id": "a", "email": "a@example.com", "status": "active"}).execute({})
    assert output["data"] == result and "active" not in output["data"]


@pytest.mark.asyncio
async def test_bluefox_email_response_secrets_are_redacted(monkeypatch):
    transport(monkeypatch, {"status": 200, "result": {"name": TOKEN}})
    output = await node({"operation": "get_project"}).execute({})
    assert TOKEN not in str(output)


@pytest.mark.parametrize("config", [
    {"operation": "update_contact", "email": "a@example.com"},
    {"operation": "update_subscriber_list", "list_id": "a"},
    {"operation": "update_subscriber", "list_id": "a", "email": "a@example.com", "status": "paused"},
    {"operation": "update_subscriber", "list_id": "a", "email": "a@example.com", "status": "paused", "paused_until": "2000-01-01T00:00:00Z"},
    {"operation": "create_contact", "email": "a@example.com", "custom_fields": {"email": "other@example.com"}},
])
def test_bluefox_email_invalid_configs(config):
    with pytest.raises(ValidationError):
        native.BluefoxEmailFullConfig.model_validate({"config": config, "credentials": CREDENTIAL})
