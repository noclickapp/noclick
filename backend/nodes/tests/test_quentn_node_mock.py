"""Exercise actual Quentn nodes with published response examples; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import quentn_node as q
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/quentn/responses.json").read_text())
CREDS = {"credential_type": "quentn_api_key", "api_base_url": "https://example.s1.quentn.com/public/api/v1", "api_key": "synthetic-quentn-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="quentn-test", node_type="automation-quentn",
        node_data={"config": config, "credentials": CREDS})


def wire(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(q, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_contact", "contact_id": 123, "fields": ["mail", "first_name"]}, "GET", "/contact/123", {"fields": "mail,first_name"}, None),
    ({"operation": "get_contact_by_email", "email": "john+test@example.com"}, "GET", "/contact/john+test@example.com", {}, None),
    ({"operation": "create_contact", "contact": {"mail": "johndoe@example.com", "first_name": "John", "field_customer_id": "A1"}}, "POST", "/contact", {}, {"contact": {"mail": "johndoe@example.com", "first_name": "John", "field_customer_id": "A1"}, "duplicate_check_method": "auto", "duplicate_merge_method": "update_add"}),
    ({"operation": "update_contact", "contact_id": 123, "contact": {"first_name": "John"}, "return_fields": ["mail"]}, "PUT", "/contact/123", {}, {"first_name": "John", "return_fields": ["mail"]}),
    ({"operation": "delete_contact", "contact_id": 123}, "DELETE", "/contact/123", {}, None),
    ({"operation": "get_contact_tags", "contact_id": 123}, "GET", "/contact/123/terms", {}, None),
    ({"operation": "add_contact_tags", "contact_id": 123, "tag_ids": [123, 555]}, "PUT", "/contact/123/terms", {}, [123, 555]),
    ({"operation": "remove_contact_tags", "contact_id": 123, "tag_ids": [555]}, "DELETE", "/contact/123/terms", {}, [555]),
    ({"operation": "list_contact_comments", "contact_id": 123, "range": 1, "limit": 10, "sort": "desc"}, "GET", "/contact/123/comments", {"range": "1", "limit": "10", "sort": "desc"}, None),
    ({"operation": "add_contact_comment", "contact_id": 123, "comment": "this is a comment"}, "POST", "/contact/123/comments", {}, {"comment": "this is a comment"}),
    ({"operation": "update_contact_comment", "contact_id": 123, "comment_id": 5, "comment": "this is an updated comment"}, "PUT", "/contact/123/comments", {}, {"id": 5, "comment": "this is an updated comment"}),
    ({"operation": "delete_contact_comments", "contact_id": 123, "comment_ids": [5]}, "DELETE", "/contact/123/comments", {}, [5]),
    ({"operation": "list_tags", "offset": 15, "limit": 2}, "GET", "/terms", {"offset": "15", "limit": "2"}, None),
    ({"operation": "create_tag", "name": "Tag A", "description": "Sample description"}, "POST", "/terms", {}, {"name": "Tag A", "description": "Sample description"}),
    ({"operation": "get_tag", "term_id": 123}, "GET", "/terms/123", {}, None),
    ({"operation": "update_tag", "term_id": 123, "description": "New description"}, "PUT", "/terms/123", {}, {"description": "New description"}),
    ({"operation": "delete_tag", "term_id": 123}, "DELETE", "/terms/123", {}, None),
    ({"operation": "list_users", "range": 1, "limit": 10, "sort": "desc"}, "GET", "/users", {"range": "1", "limit": "10", "sort": "desc"}, None),
    ({"operation": "get_user", "user_id": 2}, "GET", "/user/2", {}, None),
    ({"operation": "list_custom_fields"}, "GET", "/custom-fields", {}, None),
    ({"operation": "get_custom_field", "field_id": 123}, "GET", "/custom-fields/123", {}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES, ids=[row[0]["operation"] for row in CASES])
async def test_every_operation_sends_exact_provider_request(monkeypatch, config, method, path, params, body):
    operation = config["operation"]
    reply = {"success": True}
    if operation == "list_tags": reply = EXAMPLES["tags"]
    elif operation == "list_users": reply = EXAMPLES["users"]
    elif operation == "list_contact_comments": reply = {"range": 1, "number_ranges": 2, "comments": []}
    elif operation == "list_custom_fields": reply = EXAMPLES["custom_fields"]
    elif operation in {"get_contact", "get_contact_by_email"}: reply = EXAMPLES["contact"]
    requests = wire(monkeypatch, reply)
    output = await node(config).execute({})
    assert output["status"] == "success" and output["data"] == reply
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/public/api/v1" + path
    assert request.url.host == "example.s1.quentn.com"
    assert request.headers["Authorization"] == "Bearer " + CREDS["api_key"]
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    assert CREDS["api_key"] not in str(output)
    if operation == "list_tags": assert output["has_more"] and output["next_offset"] == 17
    if operation == "list_users": assert output["next_range"] is None
    if operation == "get_contact_by_email": assert "%2B" in str(request.url) and "%40" in str(request.url)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": True, "message": "Invalid API key"}), (200, {"error": True, "message": "Permission denied"}), (429, {"message": "Rate limited"}), (200, {"success": False}), (200, {"success": "false"}), (302, {"message": "Redirect refused"})])
async def test_provider_errors_never_claim_success(monkeypatch, status, body):
    requests = wire(monkeypatch, body, status)
    output = await node({"operation": "list_tags"}).execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert "data" not in output and len(requests) == 1
    if "message" in body: assert output["message"] == body["message"]


@pytest.mark.asyncio
async def test_empty_connection_read_and_paging(monkeypatch):
    wire(monkeypatch, [])
    output = await node({"operation": "list_tags"}).execute({})
    assert output == {"status": "success", "data": [], "has_more": False, "next_offset": None}
    wire(monkeypatch, {"range": 0, "number_ranges": 3, "users": []})
    assert (await node({"operation": "list_users"}).execute({}))["next_range"] == 1


@pytest.mark.parametrize("url", ["http://example.s1.quentn.com/public/api/v1", "https://127.0.0.1/public/api/v1", "https://example.s1.quentn.com.evil.test/public/api/v1", "https://user@example.s1.quentn.com/public/api/v1", "https://example.s1.quentn.com/public/api/v1?secret=yes", "https://example.s1.quentn.com:443/public/api/v1"])
def test_credential_refuses_foreign_or_malformed_host(url):
    with pytest.raises(ValidationError):
        q.QuentnAPIKeyCredential.model_validate({**CREDS, "api_base_url": url})


@pytest.mark.parametrize("key", ["", "Bearer key", "https://example.com", "<token>", "secret\nvalue"])
def test_bad_key_refused_without_exposing_it(key):
    with pytest.raises(ValidationError):
        q.QuentnAPIKeyCredential.model_validate({**CREDS, "api_key": key})


def test_manual_connect_default_and_schema():
    credential = q.QuentnAPIKeyCredential.model_validate({"api_base_url": CREDS["api_base_url"] + "/", "api_key": "  synthetic-quentn-key  "})
    assert credential.credential_type == "quentn_api_key" and credential.api_base_url == CREDS["api_base_url"]
    assert credential.api_key == CREDS["api_key"]
    assert q.QuentnNode.connection_evidence.operation == "list_tags"
    assert len(q.ROUTES) == len(CASES) == 21


@pytest.mark.parametrize("config", [{"operation": "get_contact", "contact_id": 0}, {"operation": "create_contact", "contact": {}}, {"operation": "update_contact", "contact_id": 123, "contact": {}}, {"operation": "update_tag", "term_id": 123}, {"operation": "remove_contact_tags", "contact_id": 123, "tag_ids": []}, {"operation": "delete_contact_comments", "contact_id": 123, "comment_ids": []}, {"operation": "list_users", "limit": 21}, {"operation": "list_contact_comments", "contact_id": 123, "limit": 51}])
def test_invalid_operation_inputs_refused(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [row[0] for row in CASES if row[1] in {"PUT", "DELETE", "POST"} and row[0]["operation"] not in {"create_contact", "create_tag"}])
async def test_help_page_string_success_response_is_preserved(monkeypatch, config):
    reply = {**EXAMPLES["success_response"], **({"comment_id": 5} if config["operation"] == "add_contact_comment" else {})}
    wire(monkeypatch, reply)
    output = await node(config).execute({})
    assert output["status"] == "success" and output["data"] == reply


@pytest.mark.asyncio
async def test_email_lookup_preserves_all_documented_matches(monkeypatch):
    wire(monkeypatch, EXAMPLES["email_response"])
    output = await node({"operation": "get_contact_by_email", "email": "johndoe@example.com"}).execute({})
    assert output["data"] == EXAMPLES["email_response"] and len(output["data"]) == 2
