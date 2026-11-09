"""Pylon contract mapping, paging, region, evidence and mutation regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from nodes import pylon_1_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-pylon-api-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {"credential_type": "pylon_1_api_token", "api_token": TOKEN, **changes}


def node(config, **changes):
    return NodeFactory.create_node(node_id="pylon-fixture", node_type="automation-pylon-1",
        node_data={"config": config, "credentials": credential(**changes)})


def transport(monkeypatch, body, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_me"}, "GET", "/me", {}, None),
    ({"operation": "list_issues", "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-02T00:00:00Z"}, "GET", "/issues", {"limit": "100", "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-02T00:00:00Z"}, None),
    ({"operation": "get_issue", "issue_id": "issue-1"}, "GET", "/issues/issue-1", {}, None),
    ({"operation": "create_issue", "account_id": "acc-1", "title": "Incident", "body_html": "<p>Check activity</p>"}, "POST", "/issues", {}, {"account_id": "acc-1", "title": "Incident", "body_html": "<p>Check activity</p>"}),
    ({"operation": "update_issue", "issue_id": "issue-1", "state": "closed", "tags": []}, "PATCH", "/issues/issue-1", {}, {"state": "closed", "tags": []}),
    ({"operation": "list_issue_messages", "issue_id": "issue-1", "cursor": "next+cursor"}, "GET", "/issues/issue-1/messages", {"limit": "100", "cursor": "next+cursor"}, None),
    ({"operation": "create_issue_note", "issue_id": "issue-1", "body_html": "<p>Note</p>", "thread_id": "thread-1"}, "POST", "/issues/issue-1/note", {}, {"body_html": "<p>Note</p>", "thread_id": "thread-1"}),
    ({"operation": "reply_issue", "issue_id": "issue-1", "message_id": "msg-1", "body_html": "<p>Reply</p>", "to_emails": ["a@example.com"]}, "POST", "/issues/issue-1/reply", {}, {"message_id": "msg-1", "body_html": "<p>Reply</p>", "email_info": {"to_emails": ["a@example.com"]}}),
    ({"operation": "create_tag", "value": "VIP", "object_type": "account", "hex_color": "#123abc"}, "POST", "/tags", {}, {"value": "VIP", "object_type": "account", "hex_color": "#123abc"}),
    ({"operation": "get_tag", "tag_id": "tag-1"}, "GET", "/tags/tag-1", {}, None),
    ({"operation": "list_tags"}, "GET", "/tags", {}, None),
    ({"operation": "list_users", "include_deactivated": True}, "GET", "/users", {"include_deactivated": "true"}, None),
    ({"operation": "get_user", "user_id": "user-1"}, "GET", "/users/user-1", {}, None),
    ({"operation": "list_teams"}, "GET", "/teams", {}, None),
    ({"operation": "list_issue_statuses"}, "GET", "/issue-statuses", {}, None),
]
for singular, plural in [("account", "accounts"), ("contact", "contacts")]:
    CASES.extend([
        ({"operation": "list_" + plural}, "GET", "/" + plural, {"limit": "100"}, None),
        ({"operation": "get_" + singular, singular + "_id": "item-1"}, "GET", "/" + plural + "/item-1", {}, None),
        ({"operation": "create_" + singular, "name": "Acme", **({"email": "a@example.com"} if singular == "contact" else {})}, "POST", "/" + plural, {}, {"name": "Acme", **({"email": "a@example.com"} if singular == "contact" else {})}),
        ({"operation": "update_" + singular, singular + "_id": "item-1", "name": "Renamed"}, "PATCH", "/" + plural + "/item-1", {}, {"name": "Renamed"}),
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES)
async def test_each_operation_one_exact_contract_request(monkeypatch, config, method, path, params, body):
    data = [] if config["operation"].startswith("list_") else {"id": "org-1", "name": "Acme"}
    requests = transport(monkeypatch, {"data": data, "request_id": "request-1"})
    result = await node(config).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.usepylon.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    assert result["data"] == data


@pytest.mark.asyncio
async def test_eu_evidence_and_opaque_paging(monkeypatch):
    requests = transport(monkeypatch, {"data": {"id": "org-eu", "name": "Acme EU", "user": {}}, "request_id": "r"})
    result = await node({"operation": "get_me"}, region="EU").execute({})
    assert result["name"] == "Acme EU" and requests[0].url.host == "api.eu.usepylon.com"
    transport(monkeypatch, {"data": [], "request_id": "r", "pagination": {"has_next_page": True, "cursor": "opaque+/="}})
    result = await node({"operation": "list_accounts"}).execute({})
    assert result["has_more"] and not result["complete"] and result["next_page_cursor"] == "opaque+/="
    transport(monkeypatch, {"data": [], "request_id": "r"})
    result = await node({"operation": "list_accounts"}).execute({})
    assert result["complete"] and result["next_page_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 401, 403, 404, 429, 500])
async def test_errors_no_retry_no_false_success(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "create_account", "name": "Acme"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": {}}, {"data": [], "error": "failure"}, {"data": [], "pagination": {"has_next_page": True, "cursor": ""}}, {"data": [], "pagination": {"has_next_page": True, "cursor": "previous"}}])
async def test_bad_list_envelopes_and_stalled_pagination(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "list_accounts", "cursor": "previous"}).execute({})
    assert result["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "get_issue", "issue_id": "../evil"},
    {"operation": "get_issue", "issue_id": "x?expand=secrets"},
    {"operation": "reply_issue", "issue_id": "issue-1", "body_html": "reply"},
    {"operation": "reply_issue", "issue_id": "issue-1", "message_id": "msg-1", "body_html": "reply", "to_emails": []},
    {"operation": "list_accounts", "limit": 1000},
    {"operation": "list_issues", "start_time": "2026-01-01", "end_time": "2026-01-02"},
    {"operation": "list_issues", "start_time": "2024-01-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
    {"operation": "create_issue", "title": "x", "body_html": "y"},
    {"operation": "delete_account", "account_id": "acc-1"},
])
def test_invalid_config_refused(config):
    with pytest.raises(ValidationError):
        TypeAdapter(native.PylonConfig).validate_python(config)


def test_schema_credential_and_catalog_contract():
    cred = native.PylonAPITokenCredential(api_token="  " + TOKEN + "  ")
    assert cred.api_token == TOKEN and cred.credential_type == "pylon_1_api_token"
    assert len(native.ROUTES) == 23 and set(native.ROUTES) == {case[0]["operation"] for case in CASES}
    for bad in ["https://example.com/token", "Bearer " + TOKEN, "<token>"]:
        with pytest.raises(ValidationError):
            native.PylonAPITokenCredential(api_token=bad)


@pytest.mark.asyncio
async def test_provider_published_issue_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/pylon-1/issue.json").read_text())
    transport(monkeypatch, fixture["body"])
    result = await node({"operation": "get_issue", "issue_id": "issue_123"}).execute({})
    assert result["data"]["id"] == "issue_123" and result["data"]["number"] == 123


@pytest.mark.asyncio
async def test_documented_provider_error_preserved(monkeypatch):
    transport(monkeypatch, {"errors": ["Invalid API token"], "code": "invalid_api_token", "request_id": "r"}, 401)
    result = await node({"operation": "get_me"}).execute({})
    assert result["error"] == "Invalid API token" and result["http_status"] == 401
