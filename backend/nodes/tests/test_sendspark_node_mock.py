"""Exercise the native Sendspark node at its HTTP boundary, without an account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sendspark_node as native
from nodes.core.registry import NodeFactory

KEY, SECRET = "synthetic-sendspark-key", "synthetic-sendspark-secret"
CASES = json.loads((Path(__file__).parent / "fixtures/sendspark/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="sendspark-test", node_type="automation-sendspark",
        node_data={"config": config, "credentials": credentials or {
            "credential_type": "sendspark_api_key", "api_key": KEY, "api_secret": SECRET}})


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
async def test_sendspark_request_contract(monkeypatch, case):
    response = httpx.Response(204) if case["status"] == 204 else httpx.Response(case["status"], json=case["response"])
    requests = transport(monkeypatch, response)
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "operation": case["config"]["operation"],
        "http_status": case["status"], "data": None if case["status"] == 204 else case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api-gw.sendspark.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["x-api-key"] == KEY
    assert request.headers["x-api-secret"] == SECRET
    assert "Authorization" not in request.headers
    assert KEY not in str(request.url) and SECRET not in str(request.url)
    if case["config"]["operation"] == "get_prospect":
        assert b"%40" in request.url.raw_path


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 422, 429, 500])
async def test_provider_rejection_keeps_message_and_redacts_both_secrets(monkeypatch, code):
    transport(monkeypatch, httpx.Response(code, json={"error": "Unauthorized", "message": f"Rejected {KEY} {SECRET}"}))
    result = await node({"operation": "get_workspace_identifier"}).execute({})
    assert result == {"status": "error", "http_status": code, "status_code": code, "error": "Rejected [redacted] [redacted]"}


@pytest.mark.asyncio
async def test_error_envelope_on_200_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"error": "Unauthorized", "message": "Missing authentication"}))
    result = await node({"operation": "get_workspace_identifier"}).execute({})
    assert result["status"] == "error" and result["error"] == "Missing authentication"


@pytest.mark.asyncio
async def test_workspace_identity_and_untouched_transcript(monkeypatch):
    payload = {"workspaceId": "workspace-123"}
    transport(monkeypatch, httpx.Response(200, json=payload))
    assert (await node({"operation": "get_workspace_identifier"}).execute({}))["data"] == payload
    assert native.SendsparkNode.connection_evidence.identity_operation == "get_workspace_identifier"
    case = next(c for c in CASES if c["config"]["operation"] == "get_campaign_transcript")
    transport(monkeypatch, httpx.Response(200, json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result["data"]["segments"][0]["start"] == 0.78
    assert result["data"]["text"] == case["response"]["text"]


@pytest.mark.asyncio
async def test_recursive_response_redaction(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"workspaces": [{"name": KEY, SECRET: SECRET}]}))
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["data"] == {"workspaces": [{"name": "[redacted]", "[redacted]": "[redacted]"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://example.com"}),
    httpx.Response(200, text="<html>wrong host</html>"),
    httpx.Response(200, headers={"content-type": "application/json"}, content=b"invalid"),
    httpx.Response(200, json=[]), httpx.Response(200, json={}),
    httpx.Response(200, json={"workspaceId": ""}), httpx.Response(204),
])
async def test_malformed_identity_or_redirect_is_not_success(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "get_workspace_identifier"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_timeout_is_never_retried(monkeypatch):
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(timeout)))
    with pytest.raises(httpx.ReadTimeout):
        await node({"operation": "create_dynamic_campaign", "workspace_id": "workspace", "name": "My Dynamic Campaign"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("charge", [None, False, "true"])
def test_prospect_generation_requires_explicit_charge_authorization(charge):
    config = {"operation": "add_prospect", "workspace_id": "workspace", "dynamic_id": "campaign",
        "prospect": {"contactEmail": "johndoe@example.com"}}
    if charge is not None:
        config["processAndAuthorizeCharge"] = charge
    assert native.SendsparkNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("config", [
    {"operation": "get_dynamic_campaign", "workspace_id": "workspace", "dynamic_id": "settings"},
    {"operation": "get_dynamic_campaign", "workspace_id": "../workspaces", "dynamic_id": "campaign"},
    {"operation": "get_dynamic_campaign", "workspace_id": "workspace", "dynamic_id": "campaign?x=1"},
    {"operation": "get_prospect", "workspace_id": "workspace", "dynamic_id": "campaign", "contact_email": "invalid"},
    {"operation": "bulk_add_prospects", "workspace_id": "workspace", "dynamic_id": "campaign", "prospectList": []},
    {"operation": "add_prospect", "workspace_id": "workspace", "dynamic_id": "campaign", "prospect": {"contactEmail": "invalid"}},
    {"operation": "update_webhook", "workspace_id": "workspace", "webhook_id": "hook"},
    {"operation": "update_dynamic_campaign", "workspace_id": "workspace", "dynamic_id": "campaign"},
    {"operation": "create_webhook", "workspace_id": "workspace", "name": "Hook", "module": "global", "url": "javascript:alert(1)"},
    {"operation": "create_webhook", "workspace_id": "workspace", "name": "Hook", "module": "global", "url": "https://user:pass@example.com"},
    {"operation": "list_workspaces", "base_url": "https://example.com"},
])
def test_invalid_config_is_rejected(config):
    assert native.SendsparkNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("field", ["api_key", "api_secret"])
@pytest.mark.parametrize("value", ["", "Bearer secret", "https://example.com", "<api-token>", "abc\nxyz", 123])
def test_invalid_credential_values_are_hidden(field, value):
    with pytest.raises((ValidationError, ValueError)) as caught:
        native.SendsparkAPIKeyCredential(**{"api_key": KEY, "api_secret": SECRET, field: value})
    assert KEY not in str(caught.value) and SECRET not in str(caught.value)


def test_credential_shaping():
    credential = native.SendsparkAPIKeyCredential(api_key="  " + KEY + "  ", api_secret="  " + SECRET + "  ")
    assert credential.api_key == KEY and credential.api_secret == SECRET
    assert KEY not in repr(credential) and SECRET not in repr(credential)


@pytest.mark.asyncio
async def test_provider_documented_prospect_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/sendspark/add_prospect_response.json").read_text())
    case = next(c for c in CASES if c["config"]["operation"] == "add_prospect")
    transport(monkeypatch, httpx.Response(200, json=fixture["body"]))
    result = await node(case["config"]).execute({})
    assert result["data"] == fixture["body"]
    assert result["data"]["prospectList"][0]["contactEmail"] == "johndoe@example.com"
    assert result["data"]["prospectList"][0]["status"] == "saved"


@pytest.mark.asyncio
async def test_unsaved_credential_evidence_names_workspace(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    transport(monkeypatch, httpx.Response(200, json={"workspaceId": "workspace-123"}))

    async def run(**kwargs):
        assert kwargs["operation"] == "get_workspace_identifier"
        return await node({"operation": kwargs["operation"]}, kwargs["credential_data"]).execute({})

    monkeypatch.setattr(run_op, "run_node_operation", run)
    evidence = await collect_evidence(node_type="automation-sendspark", user_id="test-user", credential_data={
        "credential_type": "sendspark_api_key", "api_key": KEY, "api_secret": SECRET})
    assert evidence.reachable is True
    assert evidence.account_label == "workspace-123"


@pytest.mark.asyncio
async def test_provider_documented_transcript_response(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/sendspark/transcript_response.json").read_text())
    case = next(c for c in CASES if c["config"]["operation"] == "get_campaign_transcript")
    transport(monkeypatch, httpx.Response(200, json=fixture["body"]))
    assert (await node(case["config"]).execute({}))["data"] == fixture["body"]


@pytest.mark.asyncio
async def test_provider_status_makes_connection_rejection_definitive(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    transport(monkeypatch, httpx.Response(401, json={"message": "Request refused"}))

    async def run(**kwargs):
        return await node({"operation": kwargs["operation"]}, kwargs["credential_data"]).execute({})

    monkeypatch.setattr(run_op, "run_node_operation", run)
    evidence = await collect_evidence(node_type="automation-sendspark", user_id="test-user", credential_data={
        "credential_type": "sendspark_api_key", "api_key": KEY, "api_secret": SECRET})
    assert evidence.reachable is False
    assert "Request refused" in evidence.error
