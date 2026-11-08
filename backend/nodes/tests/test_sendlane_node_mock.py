"""Run the native node through HTTP, without a Sendlane account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sendlane_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-sendlane-token"
CASES = json.loads((Path(__file__).parent / "fixtures/sendlane/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="sendlane-test", node_type="automation-sendlane",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "sendlane_api_token", "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_native_request_contract(monkeypatch, case):
    accepted = case["method"] == "DELETE" or case["config"]["operation"] == "add_list_contact"
    payload = {"data": {"message": "Successfully handled request"} if accepted else [{"id": 1}]}
    requests = transport(monkeypatch, httpx.Response(202 if accepted else 200, json=payload))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == payload["data"]
    assert result["accepted"] is accepted
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.sendlane.com"
    assert request.url.path == "/v2" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert (json.loads(request.content) if request.content else None) == case.get("body")
    assert request.headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_account_lists_evidence_preserves_empty_page_and_metadata(monkeypatch):
    payload = {"data": [], "links": {"next": None}, "meta": {"current_page": 2}}
    transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node({"operation": "list_lists", "page": 2, "limit": 3}).execute({})
    assert result["data"] == [] and result["links"] == payload["links"]
    assert result["meta"] == payload["meta"]
    assert native.SendlaneNode.connection_evidence.operation == "list_lists"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 422, 429, 500])
async def test_provider_errors_preserve_message_and_hide_token(monkeypatch, code):
    transport(monkeypatch, httpx.Response(code, json={"message": "Rejected " + TOKEN}))
    result = await node({"operation": "list_lists"}).execute({})
    assert result == {"status": "error", "http_status": code, "error": "Rejected [redacted]"}


@pytest.mark.asyncio
async def test_success_status_error_envelope_is_failure(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"errors": {"email": ["Invalid"]}}))
    assert (await node({"operation": "list_lists"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_campaign_report_fields_and_nested_redaction(monkeypatch):
    payload = {"data": {"campaign_id": 5, "sent": 10, "opens": 3,
        "automation": {"id": 1, "name": "Welcome"}, "note": TOKEN}}
    transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node({"operation": "get_campaign_report", "campaign_id": 5}).execute({})
    assert result["data"]["sent"] == 10 and result["data"]["opens"] == 3
    assert result["data"]["automation"] == {"id": 1, "name": "Welcome"}
    assert result["data"]["note"] == "[redacted]" and TOKEN not in str(result)


def test_full_config_validation_hides_secret_input():
    with pytest.raises(ValidationError) as caught:
        native.SendlaneFullConfig.model_validate({"config": {"operation": "list_lists"},
            "credentials": {"api_token": "Bearer private-token"}})
    assert "private-token" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://example.com"}),
    httpx.Response(200, text="<html>wrong host</html>"),
    httpx.Response(200, headers={"content-type": "application/json"}, content=b"invalid"),
    httpx.Response(200, json=[]), httpx.Response(200, json={}),
])
async def test_redirect_or_malformed_response_is_not_success(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_lists"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_no_silent_retry_after_write_timeout(monkeypatch):
    calls = []

    async def request(self, *args, **kwargs):
        calls.append(args)
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    transport(monkeypatch, httpx.Response(200, json={"data": []}))
    with pytest.raises(httpx.ReadTimeout):
        await node({"operation": "create_tag", "name": "VIP"}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../contacts"},
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "list_lists", "page": 0},
    {"operation": "add_contact_tags", "contact_id": 1, "tag_ids": []},
    {"operation": "add_list_contact", "list_id": 1, "email": "invalid"},
    {"operation": "add_list_contact", "list_id": 1, "email": "user@example.com", "email_consent": "true"},
    {"operation": "list_contacts", "base_url": "https://example.com"},
])
def test_invalid_input_rejected_before_execution(config):
    assert native.SendlaneNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("token", ["", "Bearer secret", "https://example.com", "<api-token>", "abc\nxyz", 123])
def test_invalid_token_rejected(token):
    with pytest.raises((ValidationError, ValueError)):
        native.SendlaneAPITokenCredential(api_token=token)
