"""Native factory request tests; synthetic responses, no provider account used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import leadmagic_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

TOKEN = "synthetic-leadmagic-key-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/leadmagic/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="leadmagic-test", node_type="automation-leadmagic",
        node_data={"config": config, "credentials": {"credential_type": "leadmagic_api_key", "api_key": TOKEN}})


def transport(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["config"]["operation"])
async def test_leadmagic_contract_routes_and_payloads(monkeypatch, case):
    requests = transport(monkeypatch, case.get("status", 200), case.get("response", {"result": []}))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case.get("response", {"result": []})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.leadmagic.io"
    assert request.url.path == case["path"]
    assert request.headers["X-API-Key"] == TOKEN
    assert "authorization" not in request.headers
    if case["method"] == "GET":
        assert not request.content
        assert dict(request.url.params) == case.get("query", {})
    else:
        assert json.loads(request.content) == case.get("body", {k: v for k, v in case["config"].items() if k != "operation"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 429, 500])
async def test_leadmagic_error_verbatim_redacted_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message": "Rejected key " + TOKEN})
    result = await node({"operation": "check_credits"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": {"message": "Rejected key [redacted]"}}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"credits": "not-a-number"}, {"credits": True}, []])
async def test_leadmagic_connection_requires_credit_balance(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError, match="credit balance"):
        await node({"operation": "check_credits"}).execute({})


@pytest.mark.asyncio
async def test_leadmagic_encoded_id_does_not_change_route(monkeypatch):
    requests = transport(monkeypatch, 200, {"batchId": "a/b?x=1"})
    await node({"operation": "get_batch", "batchId": "a/b?x=1"}).execute({})
    assert requests[0].url.raw_path == b"/v1/batch/a%2Fb%3Fx%3D1"


@pytest.mark.parametrize("config", [
    {"operation": "find_email", "first_name": "Alex"},
    {"operation": "get_company"}, {"operation": "get_email_profile"},
    {"operation": "find_mobile"}, {"operation": "find_role", "company_domain": "leadmagic.io"},
    {"operation": "detect_job_change", "profile_url": "alex-rivera"},
    {"operation": "submit_batch", "items": []},
    {"operation": "list_batches", "limit": 201}, {"operation": "list_batches", "offset": -1},
])
def test_leadmagic_rejects_incomplete_config(config):
    with pytest.raises(ConfigValidationError):
        node(config)


def test_leadmagic_manual_credential_defaults_and_secret():
    assert native.LeadmagicAPIKeyCredential(api_key=TOKEN).credential_type == "leadmagic_api_key"
    with pytest.raises(ValidationError):
        native.LeadmagicAPIKeyCredential(api_key="https://app.leadmagic.io")
