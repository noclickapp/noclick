"""HTTP-boundary tests using SalesRobot's verbatim Postman saved responses."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import salesrobot_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-salesrobot-key-42"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/salesrobot/contract_cases.json").read_text())
CASES = FIXTURE["cases"]
CREDENTIAL = {"credential_type": "salesrobot_api_key", "api_key": TOKEN,
              "linkedin_account_uuid": FIXTURE["account_uuid"]}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="salesrobot-test", node_type="automation-salesrobot",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, responder):
    requests = []
    def respond(request):
        requests.append(request)
        return responder(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_salesrobot_published_request_and_saved_response(monkeypatch, case):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "operation": case["operation"], **case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "api.boomtechinc.com" and request.url.scheme == "https"
    assert dict(request.url.params) == case["query"]
    assert request.headers["X-API-KEY"] == TOKEN
    assert (json.loads(request.content) if request.content else None) == case["request_body"]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429, 500, 302])
async def test_salesrobot_http_failures_do_not_retry_or_expose_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json={"message": "Rejected " + TOKEN}))
    result = await node({"operation": "list_campaigns"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_salesrobot_rejected_envelope_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={"success": False, "message": "Invalid API key"}))
    result = await node({"operation": "list_campaigns"}).execute({})
    assert result["status"] == "error" and result["error"] == "Invalid API key"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"success": "true", "data": []},
    {"success": True}, {"success": True, "data": {}},
    {"success": True, "data": {"data": ["wrong shape"]}}])
async def test_salesrobot_malformed_list_never_proves_connection(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "list_campaigns"}).execute({})


@pytest.mark.asyncio
async def test_salesrobot_connection_evidence_shows_campaign_names(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    case = CASES[0]
    transport(monkeypatch, lambda req: httpx.Response(200, json=case["response"]))
    result = await collect_evidence(node_type="automation-salesrobot", user_id="salesrobot-test-user", credential_data=CREDENTIAL)
    assert result.reachable is True
    assert any("Test Campaign" in sample.label for sample in result.samples)


@pytest.mark.asyncio
async def test_salesrobot_page_selection_and_boolean_query(monkeypatch):
    case = next(c for c in CASES if c["operation"] == "list_prospects")
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=case["response"]))
    await node({**case["config"], "page": 3, "size": 25}).execute({})
    assert requests[0].url.params["page"] == "3" and requests[0].url.params["size"] == "25"
    case = next(c for c in CASES if c["operation"] == "pause_campaign")
    await node({**case["config"], "pause": False, "continue_started_campaign": True}).execute({})
    assert requests[1].url.params["pause"] == "false" and requests[1].url.params["continueStartedCampaign"] == "true"


@pytest.mark.parametrize("config", [
    {"operation": "list_prospects", "campaign_uuid": FIXTURE["account_uuid"], "page": 0},
    {"operation": "delete_prospect", "prospect_uuid": "not-a-uuid"},
    {"operation": "delete_prospects", "prospect_uuids": []},
    {"operation": "create_campaign", "campaign_name": ""},
    {"operation": "update_prospect", "prospect_uuid": FIXTURE["account_uuid"], "prospect": {}},
    {"operation": "update_quota", "quota": {}},
    {"operation": "update_quota", "quota": {"dailyViewQuota": -1}},
    {"operation": "send_message", "prospect_uuid": FIXTURE["account_uuid"], "message": ""},
    {"operation": "list_campaigns", "url": "https://example.com"},
])
def test_salesrobot_invalid_input_fails_before_network(config):
    with pytest.raises(ValueError):
        node(config)


def test_salesrobot_manual_credential_fields_and_default_type():
    credential = native.SalesrobotAPIKeyCredential(api_key="  " + TOKEN + "  ",
        linkedin_account_uuid=FIXTURE["account_uuid"])
    assert credential.credential_type == "salesrobot_api_key" and credential.api_key == TOKEN
    for invalid in ["https://example.com/key", "Bearer key", "<token>"]:
        with pytest.raises(ValidationError):
            native.SalesrobotAPIKeyCredential(api_key=invalid, linkedin_account_uuid=FIXTURE["account_uuid"])
    with pytest.raises(ValidationError):
        native.SalesrobotAPIKeyCredential(api_key=TOKEN)
