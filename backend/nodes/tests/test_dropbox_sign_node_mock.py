"""Offline transport tests using provider-authored v3 contract examples."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from nodes import dropbox_sign_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-dropbox-sign-key"
CASES = json.loads((Path(__file__).parent / "fixtures/dropbox-sign/examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id="sign-test", node_type="automation-dropbox-sign",
        node_data={"config": config, "credentials": {"credential_type": "dropbox_sign_api_key", "api_key": TOKEN, **credentials}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_provider_examples_through_native_factory(monkeypatch, case):
    requests = transport(monkeypatch, case["body"])
    result = await node(case["config"]).execute({})
    assert result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url).split("?")[0] == "https://api.hellosign.com/v3" + case["path"]
    assert request.headers["authorization"] == "Basic " + base64.b64encode((TOKEN + ":").encode()).decode()
    assert TOKEN not in str(result)
    for key, value in case["body"].items():
        assert result[key] == value
    if case["method"] == "GET":
        assert request.content == b""
    if case["config"]["operation"] == "send_signature_request":
        payload = json.loads(request.content)
        assert payload["signers"][0] == {"email_address": "jack@example.com", "name": "Jack", "order": 0}
        assert payload["file_urls"] == json.loads(case["config"]["file_urls"])
        assert payload["test_mode"] is True
        assert "signature_request_id" not in payload
    if case["config"]["operation"] == "send_with_template":
        payload = json.loads(request.content)
        assert payload["template_ids"] == json.loads(case["config"]["template_ids"])
        assert payload["ccs"][0]["role"] == "Accounting"
        assert payload["custom_fields"][0]["required"] is True
    if case["config"]["operation"] == "update_signature_request":
        assert json.loads(request.content) == {"email_address": "john@example.com", "signature_id": "2f9781e1a8e2045224d808c153c2e1d3df6f8f2f"}


@pytest.mark.asyncio
async def test_list_preserves_pagination_and_exact_query(monkeypatch):
    page = {"signature_requests": [], "list_info": {"num_pages": 7, "num_results": 124, "page": 2, "page_size": 20}}
    requests = transport(monkeypatch, page)
    result = await node({"operation": "list_signature_requests", "page": 2, "query": "title:Acme + NDA", "account_id": "all"}).execute({})
    assert result["list_info"] == page["list_info"]
    assert dict(requests[0].url.params) == {"page": "2", "page_size": "20", "query": "title:Acme + NDA", "account_id": "all"}


@pytest.mark.asyncio
async def test_expression_arrays_are_normalized_before_sending(monkeypatch):
    requests = transport(monkeypatch, {"signature_request": {"signature_request_id": "abc123"}})
    result = await node({"operation": "send_signature_request",
        "file_urls": ["https://example.com/contract.pdf"],
        "signers": [{"name": "Jack", "email_address": "jack@example.com", "order": "0"}]}).execute({})
    assert result["success"] is True
    assert json.loads(requests[0].content)["signers"] == [{"name": "Jack", "email_address": "jack@example.com", "order": 0}]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,id_field", [("cancel_signature_request", "signature_request_id"), ("remove_signature_request_access", "signature_request_id"), ("delete_template", "template_id")])
async def test_documented_empty_acknowledgements(monkeypatch, operation, id_field):
    transport(monkeypatch, lambda _: httpx.Response(200, content=b""))
    result = await node({"operation": operation, id_field: "abc123"}).execute({})
    assert result["acknowledged"] is True
    assert "deleted" not in result and "cancelled" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429])
async def test_provider_errors_are_failures_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"error": {"error_msg": "Key refused: " + TOKEN, "error_name": "unauthorized"}}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["success"] is False and result["http_status"] == status
    assert result["error"] == "Key refused: [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(302, headers={"location": "https://example.com/steal"}), httpx.Response(200, json={}), httpx.Response(200, json=[]), httpx.Response(200, text="<html>oops</html>")])
async def test_rejects_redirects_and_malformed_resource(monkeypatch, reply):
    requests = transport(monkeypatch, lambda _: reply)
    result = await node({"operation": "get_account"}).execute({})
    assert result["success"] is False and len(requests) == 1


@pytest.mark.asyncio
async def test_ambiguous_write_does_not_retry(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("private request", request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "remind_signature_request", "signature_request_id": "abc123", "email_address": "john@example.com"}).execute({})
    assert result["status"] == "unknown" and result["success"] is False
    assert len(requests) == 1 and "private request" not in str(result)


@pytest.mark.parametrize("config", [
    {"operation": "get_template", "template_id": "../../account"},
    {"operation": "get_signature_request", "signature_request_id": "a?query=b"},
    {"operation": "list_templates", "page_size": 101},
    {"operation": "update_signature_request", "signature_request_id": "a", "signature_id": "b"},
    {"operation": "send_signature_request", "file_urls": "{}", "signers": "[]"},
    {"operation": "send_with_template", "template_ids": '["x"]', "signers": '[{"name":"Jack","email_address":"jack@example.com"}]'},
])
def test_invalid_inputs_fail_before_network(config):
    assert native.DropboxSignNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("key", ["https://example.com/key", "<token>", "key:password", "Basic abc", ""])
def test_manual_credential_validation(key):
    with pytest.raises(ValueError):
        native.DropboxSignAPIKeyCredential(api_key=key)


def test_credential_and_safe_send_defaults():
    assert native.DropboxSignAPIKeyCredential(api_key="  " + TOKEN + "  ").api_key == TOKEN
    case = next(c for c in CASES if c["config"]["operation"] == "send_signature_request")
    config = {k: v for k, v in case["config"].items() if k != "test_mode"}
    assert node(config).config.config.test_mode is True
    assert native.DropboxSignNode.connection_evidence.operation == "list_signature_requests"
    with pytest.raises(ValueError):
        node({"operation": "get_account"}, credential_type="dropbox_token")
    with pytest.raises(ValueError):
        native._CustomField(name="Cost", required=True)
