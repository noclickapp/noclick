"""GetAccept request contract regressions; synthetic responses, no live account."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import getaccept_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

TOKEN = "synthetic-getaccept-access-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="getaccept-fixture", node_type="automation-getaccept",
        node_data={"config": config, "credentials": {"credential_type": native.FAMILY, "access_token": TOKEN}})


CASES = [
    ({"operation": "list_documents", "filter": "signed", "offset": 100, "limit": 50}, "GET", "/documents", None, [{"id": "doc1", "name": "Proposal", "status": "signed"}]),
    ({"operation": "get_document", "document_id": "doc1", "with_stats": True}, "GET", "/documents/doc1", None, {"id": "doc1"}),
    ({"operation": "get_document_by_external_id", "external_id": "deal 42"}, "GET", "/documents/external/deal%2042", None, {"id": "doc1"}),
    ({"operation": "create_document", "name": "Proposal", "template_id": "tpl1", "recipients": [{"email": "buyer@example.com"}]}, "POST", "/documents", {"name": "Proposal", "template_id": "tpl1", "recipients": [{"email": "buyer@example.com", "role": "signer"}], "is_signing": True, "is_automatic_sending": False}, {"id": "doc1"}),
    ({"operation": "update_document", "document_id": "doc1", "tags": "sales,proposal", "value": 0}, "PUT", "/documents/doc1", {"tags": "sales,proposal", "value": 0.0}, {}),
    ({"operation": "send_document", "document_id": "doc1"}, "POST", "/documents/doc1/send", {}, {"id": "doc1"}),
    ({"operation": "send_reminder", "document_id": "doc1", "text": "Please review", "not_signed": True}, "POST", "/documents/doc1/reminders", {"type": "email", "text": "Please review", "not_signed": True}, {}),
    ({"operation": "create_comment", "document_id": "doc1", "text": "Thanks"}, "POST", "/documents/doc1/comments", {"text": "Thanks"}, {"comment_id": "c1"}),
    ({"operation": "list_contacts", "search": "Acme"}, "GET", "/contacts", None, {"contacts": [{"contact_id": "ct1", "email": "buyer@example.com"}]}),
    ({"operation": "create_contact", "email": "buyer@example.com", "first_name": "Buyer"}, "POST", "/contacts", {"email": "buyer@example.com", "first_name": "Buyer"}, {"contact_id": "ct1"}),
    ({"operation": "delete_contact", "contact_id": "ct1"}, "DELETE", "/contacts/ct1", None, None),
    ({"operation": "list_templates", "showall": "true"}, "GET", "/templates", None, {"templates": [{"id": "tpl1", "name": "Proposal"}]}),
    ({"operation": "list_folders", "type": "template"}, "GET", "/folders", None, {"folders": []}),
    ({"operation": "get_user", "user_id": "u1"}, "GET", "/users/u1", None, {"id": "u1", "email": "owner@example.com"}),
    ({"operation": "get_document_status", "document_id": "doc1"}, "GET", "/documents/doc1/status", None, {"status": "signed"}),
    ({"operation": "list_recipients", "document_id": "doc1"}, "GET", "/documents/doc1/recipients", None, {"recipients": []}),
    ({"operation": "list_comments", "document_id": "doc1"}, "GET", "/documents/doc1/comments", None, []),
    ({"operation": "list_events", "document_id": "doc1"}, "GET", "/documents/doc1/events", None, []),
    ({"operation": "list_users"}, "GET", "/users", None, {"users": []}),
    ({"operation": "list_attachments"}, "GET", "/attachments", None, {"attachments": []}),
    ({"operation": "test_authentication"}, "GET", "/test", None, {"entity_id": "ent1", "user_id": "u1"}),
]


def transport(monkeypatch, reply):
    real_client = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,response", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_getaccept_factory_request_contract(monkeypatch, config, method, path, body, response):
    requests = transport(monkeypatch, lambda req: httpx.Response(204) if response is None else httpx.Response(200, json=response))
    result = await node(config).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert str(req.url).split("?")[0] == native.BASE + path
    assert req.headers["authorization"] == "Bearer " + TOKEN
    assert json.loads(req.content) == body if body is not None else not req.content
    if method == "GET":
        expected = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if k != "operation" and "{" + k + "}" not in native.ROUTES[config["operation"]][1]}
        if config["operation"] in {"list_documents", "list_contacts"}:
            expected = {"offset": "0", "limit": "100", **expected}
        assert dict(req.url.params) == expected
    assert result["http_status"] == (204 if response is None else 200)
    if config["operation"].startswith("list_"):
        assert result["records"] == (response[native.LIST_KEYS[config["operation"]]] if config["operation"] in native.LIST_KEYS else response)
    elif response is not None:
        assert result["data"] == response
    else:
        assert result["acknowledged"] is True
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_getaccept_http_failures_redact_token_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, text="Rejected " + TOKEN))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_documents"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"error": "invalid token"}, {"records": []}, ["unexpected"]])
async def test_getaccept_malformed_list_or_error_envelope_fails(monkeypatch, response):
    transport(monkeypatch, lambda req: httpx.Response(200, json=response))
    with pytest.raises(ValueError):
        await node({"operation": "list_documents"}).execute({})


@pytest.mark.parametrize("token", ["", "Bearer abc", "https://example.com/key", "abc\n123"])
def test_getaccept_credential_validation(token):
    with pytest.raises(ValidationError):
        native.GetAcceptAccessToken(access_token=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_document", "document_id": "../users"},
    {"operation": "get_document", "document_id": ".."},
    {"operation": "get_user", "user_id": "u1?bad"},
    {"operation": "list_documents", "limit": 0},
    {"operation": "list_contacts", "offset": -1},
    {"operation": "create_document", "name": "New", "template_id": "tpl1", "recipients": []},
    {"operation": "update_document", "document_id": "doc1"},
])
def test_getaccept_invalid_config_is_rejected(config):
    with pytest.raises(ConfigValidationError):
        node(config)


def test_getaccept_all_operations_have_request_regressions():
    assert set(native.ROUTES) == {c[0]["operation"] for c in CASES}
    assert native.GetAcceptAccessToken(access_token=TOKEN).credential_type == native.FAMILY
