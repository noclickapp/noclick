"""Contract-derived Hostfully wire requests; no account or network required."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hostfully_node as native
from nodes.core.registry import NodeFactory

TOKEN = "hostfully-test-secret-7d2"
CREDENTIAL = {"credential_type": "hostfully_api_key", "api_key": TOKEN, "agency_uid": "agency-1", "environment": "sandbox"}
CASES = json.loads((Path(__file__).parent / "fixtures/hostfully/requests.json").read_text())["cases"]


def node(config, credential=None):
    return NodeFactory.create_node(node_id="hostfully-test", node_type="automation-hostfully",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_exact_contract_request_and_resource(monkeypatch, case):
    def respond(request):
        return httpx.Response(case["status"], json=case["response"]) if case["response"] is not None else httpx.Response(case["status"])
    requests = transport(monkeypatch, respond)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "sandbox-api.hostfully.com"
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["X-HOSTFULLY-APIKEY"] == TOKEN
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert TOKEN not in str(result)
    if case["response"] is not None:
        key = next(k for k in case["response"] if not k.startswith("_"))
        assert result["data"] == case["response"][key]


@pytest.mark.asyncio
async def test_cursor_is_returned_without_following_links(monkeypatch):
    requests = transport(monkeypatch, {"properties": [], "_paging": {"_nextCursor": "opaque+/="}, "_metadata": {"totalCount": 500}})
    result = await node({"operation":"list_properties"}).execute({})
    assert result["has_more"] and result["next_cursor"] == "opaque+/="
    assert len(requests) == 1
    assert result["_metadata"]["totalCount"] == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 400, 401, 403, 404, 409, 429, 500])
async def test_rejection_redacts_key_and_does_not_retry_mutation(monkeypatch, code):
    requests = transport(monkeypatch, lambda r: httpx.Response(code, json={"message": "Rejected " + TOKEN}, headers={"Location":"https://other.example/"}))
    result = await node({"operation":"cancel_lead", "lead_uid":"lead-1"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"agency":[]}, {"agency":{}, "errors":["no"]}, []])
async def test_invalid_success_envelope_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation":"get_agency"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_production_and_block_request(monkeypatch):
    requests = transport(monkeypatch, {"lead":{"uid":"block-1"}})
    await node({"operation":"create_lead", "property_uid":"prop-1", "status":"BLOCKED", "check_in_date":"2026-11-10", "check_out_date":"2026-11-12"}, {**CREDENTIAL, "environment":"production"}).execute({})
    assert requests[0].url.host == "api.hostfully.com"
    assert "guestInformation" not in json.loads(requests[0].content)


@pytest.mark.parametrize("config", [
    {"operation":"get_lead", "lead_uid":"../other"},
    {"operation":"get_property", "property_uid":"prop?other=1"},
    {"operation":"update_property", "property_uid":"prop-1"},
    {"operation":"create_lead", "property_uid":"prop-1", "check_in_date":"2026-11-12", "check_out_date":"2026-11-10", "email":"guest@example.com"},
    {"operation":"create_lead", "property_uid":"prop-1", "check_in_date":"2026-11-10", "check_out_date":"2026-11-12"},
    {"operation":"list_jobs", "from_date":"2026-11-10", "to_date":"2026-11-12"},
    {"operation":"list_properties", "limit":101},
    {"operation":"custom_request", "url":"https://other.example"},
])
def test_invalid_config_is_rejected(config):
    with pytest.raises(ValueError):
        native.HostfullyNode.parse_config({"config":config, "credentials":CREDENTIAL})


@pytest.mark.asyncio
async def test_documented_zero_duration_job_and_invalid_job_range(monkeypatch):
    transport(monkeypatch, {"job": {"uid": "job-1"}})
    config = {"operation": "create_job", "property_uid": "propertyUid", "service_uid": "serviceUid",
        "start_local_date_time": "2026-04-20T11:52:36", "end_local_date_time": "2026-04-20T11:52:36"}
    assert (await node(config).execute({}))["status"] == "success"
    with pytest.raises(ValueError):
        native.HostfullyNode.parse_config({"config": {**config, "end_local_date_time": "2026-04-19T11:52:36"}, "credentials": CREDENTIAL})


def test_manual_credential_and_account_evidence():
    credential = native.HostfullyAPIKeyCredential.model_validate({"api_key":TOKEN, "agency_uid":"agency-1"})
    assert credential.credential_type == "hostfully_api_key"
    assert native.HostfullyNode.connection_evidence.identity_operation == "get_agency"
    with pytest.raises(ValidationError):
        native.HostfullyAPIKeyCredential.model_validate({**CREDENTIAL, "environment":"https://evil.example"})
    with pytest.raises(ValidationError) as error:
        native.HostfullyAPIKeyCredential.model_validate({**CREDENTIAL, "api_key":"bad\n" + TOKEN})
    assert TOKEN not in str(error.value)
