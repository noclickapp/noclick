"""Direct REST request, response and credential regressions (no live account)."""
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import brilliant_directories_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "brilliant_directories_api_key", "site_url": "https://directory.example.com", "api_key": "synthetic-brilliant-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="brilliant-fixture", node_type="automation-brilliant-directories",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_member_page_cursor_filter_and_secret_projection(monkeypatch):
    requests = transport(monkeypatch, {"status": "success", "message": [{"user_id": 42, "company": "Example", "password": "hash", "token": "session", "nested": {"cookie": "secret"}}], "total": 2, "next_page": "opaque+/="})
    result = await node({"operation": "list_members", "limit": 10, "page": "cursor+/=", "property": "email", "property_value": "jane@example.com"}).execute({})
    assert result["items"] == [{"user_id": 42, "company": "Example", "nested": {}}]
    assert result["next_page"] == "opaque+/=" and result["total"] == 2
    req = requests[0]
    assert req.url.path == "/api/v2/user/get" and req.headers["X-Api-Key"] == CREDENTIAL["api_key"]
    assert dict(req.url.params) == {"limit": "10", "page": "cursor+/=", "property": "email", "property_value": "jane@example.com"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,fields", [
    ({"operation": "create_member", "email": "new@example.com", "password": "secret123", "subscription_id": 1, "first_name": "Jane", "last_name": "Doe"}, "POST", "/api/v2/user/create", {"email": ["new@example.com"], "password": ["secret123"], "subscription_id": ["1"], "first_name": ["Jane"], "last_name": ["Doe"]}),
    ({"operation": "update_member", "user_id": 42, "company": "New Company Name"}, "PUT", "/api/v2/user/update", {"user_id": ["42"], "company": ["New Company Name"]}),
    ({"operation": "create_lead", "lead_name": "Jane", "lead_email": "jane@example.com", "lead_phone": "5551234567", "lead_message": "Need a quote", "lead_location": "Los Angeles", "top_id": 1, "auto_match": 0, "send_lead_email_notification": 0}, "POST", "/api/v2/leads/create", {"lead_name": ["Jane"], "lead_email": ["jane@example.com"], "lead_phone": ["5551234567"], "lead_message": ["Need a quote"], "lead_location": ["Los Angeles"], "top_id": ["1"], "auto_match": ["0"], "send_lead_email_notification": ["0"]}),
    ({"operation": "update_review", "review_id": 3, "review_status": 2}, "PUT", "/api/v2/users_reviews/update", {"review_id": ["3"], "review_status": ["2"]}),
    ({"operation": "create_post", "user_id": 42, "data_id": 7, "data_type": 20, "post_title": "News", "post_content": "<p>Hello & welcome</p>", "post_status": 0}, "POST", "/api/v2/data_posts/create", {"user_id": ["42"], "data_id": ["7"], "data_type": ["20"], "post_title": ["News"], "post_content": ["<p>Hello & welcome</p>"], "post_status": ["0"]}),
])
async def test_writes_are_single_form_encoded_contract_operations(monkeypatch, config, method, path, fields):
    requests = transport(monkeypatch, {"status": "success", "message": {"id": 42}})
    result = await node(config).execute({})
    assert result["data"] == {"id": 42} and result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == fields


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,id_field,path", [
    ("get_member", "user_id", "user"), ("get_lead", "lead_id", "leads"),
    ("get_review", "review_id", "users_reviews"), ("get_post", "post_id", "data_posts"),
    ("get_membership_plan", "subscription_id", "subscription_types"),
])
async def test_detail_accepts_documented_array_message(monkeypatch, operation, id_field, path):
    requests = transport(monkeypatch, {"status": "success", "message": [{id_field: "42"}]})
    result = await node({"operation": operation, id_field: 42}).execute({})
    assert result["data"] == [{id_field: "42"}]
    assert requests[0].url.path == f"/api/v2/{path}/get/42"
    assert requests[0].method == "GET" and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(403, {"status": "error", "message": "API Key does not have permission to access this endpoint"}), (200, {"status": "error", "message": "Invalid API Key"})])
async def test_provider_rejection_does_not_report_success(monkeypatch, status, body):
    transport(monkeypatch, body, status)
    result = await node({"operation": "list_members"}).execute({})
    assert result["status"] == "error" and body["message"] in result["error"]


@pytest.mark.asyncio
async def test_empty_page_and_malformed_success(monkeypatch):
    transport(monkeypatch, {"status": "success", "message": [], "next_page": None})
    assert (await node({"operation": "list_members"}).execute({}))["items"] == []
    transport(monkeypatch, {"status": "success", "message": "not records"})
    with pytest.raises(ValueError, match="record data"):
        await node({"operation": "list_members"}).execute({})


@pytest.mark.parametrize("changes", [{"site_url": "http://example.com"}, {"site_url": "https://example.com:8080"}, {"site_url": "https://user:pass@example.com"}, {"api_key": "https://example.com"}])
def test_bad_credential_shape(changes):
    with pytest.raises(ValidationError):
        native.BrilliantDirectoriesApiKeyCredential.model_validate({**CREDENTIAL, **changes})


@pytest.mark.parametrize("config", [{"operation": "get_member", "user_id": "../42"}, {"operation": "get_member", "user_id": 0}, {"operation": "list_members", "limit": 101}, {"operation": "list_members", "property": "email"}, {"operation": "create_member", "email": "new@example.com", "subscription_id": 1}, {"operation": "update_review", "review_id": 3, "review_status": 1}])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)
