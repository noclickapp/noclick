"""Real factory and HTTP-boundary tests; all credentials and account data are synthetic."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import pocketsmith_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-pocketsmith-developer-key"
CASES = json.loads((Path(__file__).parent / "fixtures/pocketsmith/operations.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="pocketsmith-fixture", node_type="automation-pocketsmith",
        node_data={"config": config, "credentials": {"credential_type": "pocketsmith_developer_key", "developer_key": TOKEN}})


def transport(monkeypatch, respond):
    requests = []
    def handle(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_provider_contract_requests_and_unwrapped_responses(monkeypatch, case):
    requests = transport(monkeypatch, lambda req: httpx.Response(case["status"], **({"json": case["response"]} if case["status"] != 204 else {})))
    result = await node(case["config"]).run({})
    assert result["status"] == "success" and result["http_status"] == case["status"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == "/v2" + case["path"]
    assert request.url.host == "api.pocketsmith.com" and request.url.scheme == "https"
    assert request.headers["X-Developer-Key"] == TOKEN and "authorization" not in request.headers
    if case["method"] == "GET":
        assert dict(request.url.params) == case.get("query", {}) and not request.content
    elif case["method"] in {"POST", "PUT"}:
        assert json.loads(request.content) == case["body"]
    else:
        assert not request.content and result["deleted_id"] == 42 and result["deletion_acknowledged"]
    if case["status"] != 204:
        assert result["data"] == case["response"]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_paginated_transactions_preserve_filters_without_following_links(monkeypatch):
    link = native.BASE + "/users/42/transactions?page=3&search=Paypal&start_date=2016-11-01&end_date=2016-11-30"
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[{"id": 42}], headers={"Link": f'<{link}>; rel="next"', "Per-Page": "30", "Total": "91"}))
    result = await node({"operation": "list_transactions", "user_id": 42, "page": 2, "search": "Paypal", "start_date": "2016-11-01", "end_date": "2016-11-30"}).run({})
    assert result["next_page"] == 3 and result["has_more"] and len(requests) == 1
    assert requests[0].url.params["page"] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["https://evil.example/v2/users/42/transactions?page=2", native.BASE + "/users/43/transactions?page=2", native.BASE + "/users/42/transactions?page=1", native.BASE + "/users/42/transactions?page=2&search=other", native.BASE + "/users/42/transactions?page=2&page=3"])
async def test_changed_or_stalled_page_is_rejected_without_follow(monkeypatch, link):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[], headers={"Link": f'<{link}>; rel="next"'}))
    with pytest.raises(ValueError, match="pagination"):
        await node({"operation": "list_transactions", "user_id": 42}).run({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_error_status_preserves_provider_rejection_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"error": "Rejected " + TOKEN}, headers={"Location": "https://evil.example"}))
    result = await node({"operation": "get_me"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["message"] and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], "html", {"error": "bad"}, {"errors": []}, {}])
async def test_connection_cannot_succeed_without_account_identity(monkeypatch, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({"operation": "get_me"}).run({})


@pytest.mark.asyncio
async def test_network_failure_never_retries_a_write(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout(TOKEN, request=req)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect writes") as error:
        await node({"operation": "create_category", "user_id": 42, "title": "Food"}).run({})
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_zero_false_and_nested_redaction_survive_serialization(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={"id": 42, "note": TOKEN, "nested": [TOKEN]}))
    result = await node({"operation": "update_transaction", "transaction_id": 42, "amount": 0, "needs_review": False}).run({})
    assert json.loads(requests[0].content) == {"amount": 0, "needs_review": False}
    assert result["data"]["nested"] == ["[redacted]"] and TOKEN not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "get_transaction", "transaction_id": "../42"},
    {"operation": "get_transaction", "transaction_id": True},
    {"operation": "get_transaction", "transaction_id": 0},
    {"operation": "list_transactions", "user_id": 42, "start_date": "2016-11-01"},
    {"operation": "list_transactions", "user_id": 42, "start_date": "2016-11-30", "end_date": "2016-11-01"},
    {"operation": "create_transaction", "transaction_account_id": 42, "payee": "Tex Otago", "amount": float("nan"), "date": "2018-02-27"},
    {"operation": "update_transaction", "transaction_id": 42},
    {"operation": "update_category", "category_id": 42},
    {"operation": "update_transaction_account", "transaction_account_id": 42},
    {"operation": "create_category", "user_id": 42, "title": "Food", "colour": "red"},
    {"operation": "create_category", "user_id": 42, "title": "Food", "url": "https://evil.example"},
])
def test_invalid_configuration_fails_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        native.PocketSmithNode.parse_config({"config": config})


@pytest.mark.parametrize("value", [None, {}, "<token>", "https://example.com", "key\r\nHeader: injected", "nonascii☃"])
def test_invalid_credentials_rejected(value):
    with pytest.raises(ValidationError):
        native.PocketSmithDeveloperKeyCredential(developer_key=value)


def test_credential_can_be_shaped_without_type_tag_and_evidence_needs_no_inputs():
    credential, errors, _ = shape_credential("pocketsmith_developer_key", {"developer_key": " " + TOKEN + "\n"})
    assert not errors and credential["developer_key"] == TOKEN
    assert native.PocketSmithDeveloperKeyCredential.model_validate(credential).credential_type == "pocketsmith_developer_key"
    assert native.PocketSmithNode.connection_evidence.identity_operation == "get_me"
    assert native.GetMe().operation == "get_me"
