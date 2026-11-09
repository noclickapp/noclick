"""CallerAPI wire mappings and provider-envelope regressions; no live account.

The lookup fixture preserves the official example's null complaints and absent
carrier_info: https://docs.callerapi.com/spam-score-hlr-19887237e0
The provider's response schema currently contradicts that published example.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import callerapi_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/callerapi/operations.json").read_text())
TOKEN = "callerapi-test-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="callerapi-test", node_type="automation-callerapi",
        node_data={"config": config, "credentials": {"credential_type": "callerapi_api_key", "api_key": TOKEN}})


def mock_client(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response
    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", factory)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_callerapi_exact_wire_contract_and_response(monkeypatch, case):
    requests = mock_client(monkeypatch, httpx.Response(200, json=case["response"]))
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result == {**case["response"], "status": "success", "http_status": 200}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.callerapi.com"
    assert request.url.path == case["path"]
    assert request.headers["X-Auth"] == TOKEN
    assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in case["params"].items()}
    assert (json.loads(request.content) if request.content else None) == case["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(401, {"error": "Invalid API key"}), (429, {"status": "error", "message": "too many writes"}), (200, {"status": "error", "message": "not accepted"}), (302, {"message": "redirect"})])
async def test_callerapi_rejection_is_not_success(monkeypatch, code, body):
    requests = mock_client(monkeypatch, httpx.Response(code, json=body, headers={"Location": "https://other.example.test"}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == code
    assert result["error"] == body.get("error", body.get("message"))
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_callerapi_non_json_and_secret_redaction(monkeypatch):
    mock_client(monkeypatch, httpx.Response(502, text="<html>Bad Gateway</html>"))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    mock_client(monkeypatch, httpx.Response(401, json={"error": "Rejected " + TOKEN}))
    result = await node({"operation": "get_account"}).execute({})
    assert TOKEN not in str(result) and "[redacted]" in result["error"]


@pytest.mark.parametrize("config", [
    {"operation": "lookup_phone", "phone": "../me"},
    {"operation": "get_number", "phone": "+123?secret=1"},
    {"operation": "get_voice_session", "session_id": "../me"},
    {"operation": "list_numbers", "limit": 101},
    {"operation": "scan_transcript", "transcript": "hello", "report": True},
    {"operation": "set_schedule"},
    {"operation": "set_schedule", "times": ["29:00"]},
    {"operation": "set_schedule", "weekdays": [0]},
    {"operation": "set_schedule", "timezone": "Invalid/Zone"},
    {"operation": "set_schedule", "mode": "interval", "times": ["08:00"]},
    {"operation": "save_webhook", "url": "http://hooks.example.test"},
    {"operation": "save_webhook", "url": "https://user:pass@hooks.example.test"},
    {"operation": "save_webhook", "url": "https://hooks.example.test:8080"},
])
def test_callerapi_rejects_invalid_input(config):
    with pytest.raises(ValidationError):
        native.CallerapiFullConfig(config=config)


def test_callerapi_manual_credential_and_evidence():
    credential = native.CallerapiAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "callerapi_api_key"
    assert native.CallerapiNode.connection_evidence.identity_operation == "get_account"


@pytest.mark.asyncio
async def test_callerapi_account_requires_identity(monkeypatch):
    mock_client(monkeypatch, httpx.Response(200, json={"status": "success"}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and "email" in result["error"]
