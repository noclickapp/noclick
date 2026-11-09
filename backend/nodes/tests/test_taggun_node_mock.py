"""Exercise every Taggun route through the native node factory.

Mock transports verify auth, JSON bodies, response preservation and rejected
connections without contacting Taggun or submitting billable receipt scans.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import taggun_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/taggun/requests.json").read_text())["configs"]
KEY = "taggun-test-secret-789"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="taggun-test", node_type="automation-taggun",
        node_data={"config": config, "credentials": credentials or {"credential_type": "taggun_api_key", "api_key": KEY}})


def mock_http(monkeypatch, status=200, body=None, content=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_taggun_operation_request_and_response(monkeypatch, operation):
    config = FIXTURES[operation]
    reply = {"receiptId": "receipt-123", "totalAmount": {"data": 23.3, "confidenceLevel": 0.99}, "futureField": [1, False, None]}
    requests = mock_http(monkeypatch, body=reply)
    result = await node({"operation": operation, **config}).execute({})
    assert result == {"status": "success", "data": reply, "http_status": 200}
    assert len(requests) == 1
    request = requests[0]
    method, path = native.ROUTES[operation]
    expected = dict(config)
    if "{campaignId}" in path:
        path = path.replace("{campaignId}", expected.pop("campaignId"))
    assert request.method == method
    assert str(request.url) == native.BASE_URL + path
    assert request.headers["apikey"] == KEY
    assert "authorization" not in request.headers
    if method in {"POST", "PUT"}:
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == expected
    else:
        assert not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [["loyalty-2026"], [], {"campaignIds": ["loyalty-2026"]}, "saved"])
async def test_taggun_campaign_response_shapes_preserved(monkeypatch, body):
    mock_http(monkeypatch, body=body)
    assert (await node({"operation": "list_campaign_settings"}).execute({}))["data"] == body


@pytest.mark.asyncio
async def test_taggun_connection_evidence_is_account_read(monkeypatch):
    evidence = native.TaggunNode.connection_evidence
    assert evidence.operation == "list_campaign_settings"
    requests = mock_http(monkeypatch, body=["loyalty-2026"])
    result = await node({"operation": evidence.operation}).execute({})
    assert result["data"] == ["loyalty-2026"]
    assert requests[0].method == "GET" and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_taggun_rejection_never_succeeds_or_retries(monkeypatch, status):
    requests = mock_http(monkeypatch, status, {"message": "Taggun refused " + KEY})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_campaign_settings"}).execute({})
    assert KEY not in str(exc.value)
    assert "Taggun refused" in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_taggun_empty_delete_and_malformed_json(monkeypatch):
    mock_http(monkeypatch, 204, content=b"")
    assert (await node({"operation": "delete_campaign_settings", "campaignId": "old"}).execute({}))["data"] is None
    mock_http(monkeypatch, content=b"<html>unexpected</html>")
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "list_campaign_settings"}).execute({})


@pytest.mark.asyncio
async def test_taggun_path_id_is_escaped_once(monkeypatch):
    requests = mock_http(monkeypatch, body={})
    await node({"operation": "get_campaign_settings", "campaignId": "special /?#% id"}).execute({})
    assert requests[0].url.raw_path.endswith(b"special%20%2F%3F%23%25%20id")
    assert not requests[0].url.query


def test_taggun_manual_key_defaults_and_schema():
    credential = native.TaggunAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "taggun_api_key"
    assert "credential_type" not in native.TaggunAPIKeyCredential.model_json_schema()["required"]
    assert set(FIXTURES) == set(native.ROUTES)
    assert native.TaggunNode.get_config_schema()


@pytest.mark.parametrize("config", [
    {"operation": "scan_simple_url", "url": "http://example.com/receipt.png"},
    {"operation": "scan_simple_url", "url": "https://user:secret@example.com/receipt.png"},
    {"operation": "scan_simple_encoded", "image": "not base64", "filename": "r.png", "contentType": "image/png"},
    {"operation": "get_campaign_settings", "campaignId": ".."},
    {"operation": "scan_simple_url", **FIXTURES["scan_simple_url"], "extractLineItems": True},
    {"operation": "add_receipt_feedback"},
    {"operation": "add_receipt_feedback", "referenceId": "r1", "date": "invalid"},
    {"operation": "create_campaign_settings", "campaignId": "x", "date": {}},
    {"operation": "update_campaign_settings", "campaignId": "x", "balanceOwing": {}},
])
def test_taggun_invalid_or_unsupported_input_rejected(config):
    assert not native.TaggunNode.validate_config({"config": config, "credentials": {"api_key": KEY}})["valid"]


@pytest.mark.parametrize("key", ["", "https://example.com/token", "bad\r\nkey", "Bearer key"])
def test_taggun_invalid_credential_rejected(key):
    with pytest.raises(ValidationError):
        native.TaggunAPIKeyCredential(api_key=key)
