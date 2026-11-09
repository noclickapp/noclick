"""HTTP boundary tests; responses are synthetic full witnesses of the v2 2.0.0 contract.

Source: https://productlane.com/api/v2/openapi.json. No live API calls or secrets.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import productlane_node as native
from nodes.core.registry import NodeFactory

TOKEN = "pl_v2_synthetic-key-for-tests"
RESPONSES = json.loads((Path(__file__).parent / "fixtures/productlane/responses.json").read_text())
CASES = [
    ("get_me", {}, "GET", "/me", None),
    ("list_threads", {}, "GET", "/threads", None),
    ("get_thread", {"thread_id": "thr_1"}, "GET", "/threads/thr_1", None),
    ("create_thread", {"text": "<p>Feedback</p>", "pain_level": "HIGH", "contact_email": "customer@example.com"}, "POST", "/threads", {"text": "<p>Feedback</p>", "pain_level": "HIGH", "contact_email": "customer@example.com"}),
    ("update_thread", {"thread_id": "thr_1", "status": "done", "closed_loop": True}, "PATCH", "/threads/thr_1", {"status": "done", "closed_loop": True}),
    ("list_messages", {"thread_id": "thr_1"}, "GET", "/threads/thr_1/messages", None),
    ("send_message", {"thread_id": "thr_1", "content": "<p>Thanks</p>"}, "POST", "/threads/thr_1/messages", {"content": "<p>Thanks</p>"}),
    ("list_comments", {"thread_id": "thr_1"}, "GET", "/threads/thr_1/comments", None),
    ("create_comment", {"thread_id": "thr_1", "content": "Internal note"}, "POST", "/threads/thr_1/comments", {"content": "Internal note"}),
    ("list_contacts", {}, "GET", "/contacts", None),
    ("get_contact", {"contact_id": "con_1"}, "GET", "/contacts/con_1", None),
    ("create_contact", {"email": "customer@example.com", "is_subscribed": False}, "POST", "/contacts", {"email": "customer@example.com", "is_subscribed": False}),
    ("update_contact", {"contact_id": "con_1", "name": "Customer"}, "PATCH", "/contacts/con_1", {"name": "Customer"}),
    ("list_companies", {}, "GET", "/companies", None),
    ("get_company", {"company_id": "com_1"}, "GET", "/companies/com_1", None),
    ("create_company", {"name": "Acme", "domains": ["example.com"], "size": 0}, "POST", "/companies", {"name": "Acme", "domains": ["example.com"], "size": 0}),
    ("update_company", {"company_id": "com_1", "revenue": 0}, "PATCH", "/companies/com_1", {"revenue": 0}),
    ("list_tags", {}, "GET", "/tags", None),
    ("list_projects", {}, "GET", "/projects", None),
    ("list_issues", {}, "GET", "/issues", None),
    ("list_changelogs", {}, "GET", "/changelogs", None),
    ("get_changelog", {"changelog_id": "chg_1"}, "GET", "/changelogs/chg_1", None),
    ("create_changelog", {"title": "Release", "content": "## New"}, "POST", "/changelogs", {"title": "Release", "content": "## New"}),
    ("update_changelog", {"changelog_id": "chg_1", "published": False, "tag_ids": []}, "PATCH", "/changelogs/chg_1", {"published": False, "tag_ids": []}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="productlane-test", node_type="automation-productlane", node_data={
        "config": config, "credentials": {"credential_type": "productlane_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_full_contract_witnesses(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=RESPONSES[operation]))
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "data": RESPONSES[operation]}
    assert TOKEN not in str(result)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/api/v2" + path
    assert req.url.host == "productlane.com" and req.url.scheme == "https"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(req.content) if req.content else None) == body
    assert dict(req.url.params) == ({"limit": "50"} if operation.startswith("list_") else {})


@pytest.mark.asyncio
async def test_cursor_filters_and_dates(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=RESPONSES["list_threads"]))
    result = await node({"operation": "list_threads", "cursor": "cursor/+&=", "limit": 20,
        "status": "done", "tag_id": "one,two", "updated_after": "2026-10-01T00:00:00Z"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "20", "cursor": "cursor/+&=", "status": "done", "tag_id": "one,two", "updated_after": "2026-10-01T00:00:00Z"}
    assert result["data"]["page"] == RESPONSES["list_threads"]["page"]


@pytest.mark.asyncio
async def test_explicit_null_and_omitted_fields(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=RESPONSES["update_thread"]))
    await node({"operation": "update_thread", "thread_id": "thr_1", "assignee_id": None, "tag_ids": []}).execute({})
    assert json.loads(requests[0].content) == {"assignee_id": None, "tag_ids": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 400, 401, 403, 410, 429, 500])
async def test_provider_rejections_and_secret_redaction(monkeypatch, code):
    requests = transport(monkeypatch, lambda _: httpx.Response(code, json={"error": {"code": "scope_required", "message": "Rejected " + TOKEN}}))
    result = await node({"operation": "get_me"}).execute({})
    assert result == {"status": "error", "status_code": code, "error": "Rejected [redacted]"}
    assert len(requests) == 1  # Never retry writes or follow redirects.


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"error": {"message": "Rejected"}}, {"workspace_id": None}])
async def test_incomplete_identity_never_proves_account(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_me"}).execute({})


@pytest.mark.asyncio
async def test_non_json_response(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"}))
    with pytest.raises(ValueError, match="bounded JSON"):
        await node({"operation": "get_me"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_thread", "thread_id": "../other"},
    {"operation": "get_thread", "thread_id": ".."},
    {"operation": "get_contact", "contact_id": "https://evil.test"},
    {"operation": "list_threads", "limit": 201},
    {"operation": "create_thread", "text": "Body", "pain_level": "HIGH"},
    {"operation": "create_thread", "pain_level": "HIGH", "contact_email": "test@example.com"},
    {"operation": "update_thread", "thread_id": "thr_1", "status": "snoozed"},
    {"operation": "create_contact", "email": "not-an-email"},
    {"operation": "update_contact", "contact_id": "con_1", "company_id": "one", "company_name": "two"},
    {"operation": "update_company", "company_id": "com_1"},
    {"operation": "create_company", "name": "Acme", "size": -1},
    {"operation": "send_message", "thread_id": "thr_1", "content": ""},
])
def test_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("secret", ["https://example.com/key", "Bearer token", "pl_v1_oldkey", "<token>"])
def test_bad_keys(secret):
    with pytest.raises(ValidationError):
        native.ProductlaneApiKeyCredential(api_key=secret)


def test_credential_default_and_scope_coverage():
    assert native.ProductlaneApiKeyCredential(api_key=TOKEN).credential_type == "productlane_api_key"
    assert set(native.PRODUCTLANE_SCOPES) == set(native.ROUTES)
    assert native.PRODUCTLANE_SCOPES.require("send_message").scopes == ("messages:write",)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,operation", [("thread_id", "list_threads"), ("contact_id", "list_contacts"), ("company_id", "list_companies"), ("changelog_id", "list_changelogs")])
async def test_picker_uses_own_list_and_cursor(monkeypatch, field, operation):
    payload = {"data": [{"id": "id1", "name": "Customer"}], "page": {"cursor": "next/+", "has_more": True, "limit": 50}}
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    choices = await native.ProductlaneNode.load_field_options(field, {"api_key": TOKEN}, page_token="prior/+")
    assert choices == {"options": [{"value": "id1", "label": "Customer"}], "next_page_token": "next/+"}
    assert requests[0].url.path == "/api/v2" + native.ROUTES[operation][1]
    assert requests[0].url.params["cursor"] == "prior/+"


@pytest.mark.asyncio
async def test_connection_evidence_names_workspace(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    # Shorter documented example: https://productlane.com/docs/authentication (Verify a key).
    response = {"workspace_id": "wks_abc123", "api_key_id": "key_def456", "scopes": ["threads:read", "threads:write"]}
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=response))
    result = await collect_evidence(node_type="automation-productlane", user_id="00000000-0000-4000-8000-000000000001", credential_data={"credential_type": "productlane_api_key", "api_key": TOKEN})
    assert result.reachable is True and result.account_label == "wks_abc123"
    assert len(requests) == 1 and requests[0].url.path == "/api/v2/me"


@pytest.mark.asyncio
async def test_rejected_key_blocks_connection(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, lambda _: httpx.Response(401, json={"error": {"code": "unauthenticated", "message": "Key revoked or unknown."}}))
    result = await collect_evidence(node_type="automation-productlane", user_id="00000000-0000-4000-8000-000000000001", credential_data={"credential_type": "productlane_api_key", "api_key": TOKEN})
    assert result.reachable is False and "Key revoked or unknown." in result.error


@pytest.mark.asyncio
async def test_canvas_picker_bookkeeping_stays_off_the_wire(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=RESPONSES["get_thread"]))
    result = await node({"operation": "get_thread", "thread_id": "thr_1", "thread_id__label": "Customer feedback",
        "credentialIds": {"productlane_api_key": "saved-credential"}}).execute({})
    assert result["status"] == "success"
    assert requests[0].url.path == "/api/v2/threads/thr_1" and not requests[0].url.query


def test_timestamp_requires_timezone():
    with pytest.raises(ValueError):
        node({"operation": "list_threads", "updated_after": "2026-10-01T12:00:00"})
