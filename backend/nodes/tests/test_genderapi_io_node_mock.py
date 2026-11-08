"""Provider-authored V2 examples plus request/auth/error regression coverage."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import genderapi_io_node as native
from nodes.core.registry import NodeFactory

TOKEN = "a12345678901234567890123b"
FIXTURES = Path(__file__).parent / "fixtures/genderapi-io"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())["body"]


def node(config):
    return NodeFactory.create_node(node_id="genderapi-test", node_type="automation-genderapi-io",
        node_data={"config": config, "credentials": {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,response", [
    ("predict_name", {"value": "Sophia", "country": "US"}, "POST", "/api/v2/gender", "prediction-dataset"),
    ("predict_email", {"value": "alice.smith@example.com"}, "POST", "/api/v2/gender", "prediction-dataset"),
    ("predict_username", {"value": "prenses", "forceToGenderize": True}, "POST", "/api/v2/gender", "prediction-alias"),
    ("predict_gender_get", {"value": "Sophia", "forceToGenderize": False, "ai_mode": "off"}, "GET", "/api/v2/gender", "prediction-unknown"),
    ("predict_batch", {"items": [{"type": "name", "value": "Sophia", "id": "contact-1"}]}, "POST", "/api/v2/gender/batch", "batch-batch"),
    ("validate_phone", {"number": "+905321234567"}, "POST", "/api/v2/phone/validate", "phone-phone"),
    ("get_usage", {}, "GET", "/api/v2/usage", "usage-usage"),
    ("get_capabilities", {}, "GET", "/api/v2", None),
    ("get_error_catalog", {}, "GET", "/api/v2/errors", None),
    ("get_openapi", {}, "GET", "/api/v2/openapi.json", None),
])
async def test_all_ten_actions_exact_routes_and_provider_examples(monkeypatch, operation, config, method, path, response):
    payload = fixture(response) if response else {"version": "2.0.0"}
    requests = transport(monkeypatch, payload)
    result = await node({"operation": operation, **config}).execute({})
    assert result["success"] is True and result["response"] == payload
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path and req.url.host == "api.genderapi.io"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert "key" not in req.url.params and TOKEN not in str(result)
    if operation in {"predict_name", "predict_email", "predict_username"}:
        body = json.loads(req.content)
        assert body["type"] == operation.removeprefix("predict_")
        assert body["value"] == config["value"]
        assert "operation" not in body and "options" not in body and "id" not in body
    elif operation == "predict_gender_get":
        assert dict(req.url.params) == {"type": "name", "value": "Sophia", "forceToGenderize": "false", "ai_mode": "off"}
    elif method == "POST":
        assert json.loads(req.content) == config


@pytest.mark.asyncio
async def test_free_connect_probe_refuses_trial_and_requires_explicit_account_mode(monkeypatch):
    body = fixture("usage-usage")
    requests = transport(monkeypatch, body)
    result = await node({"operation": "get_usage", "verify_api_key": True}).execute({})
    assert result["status"] == "error" and result["error"] == "API-key authentication failed: api_key_missing"
    assert requests[0].url.path == "/api/v2/usage" and len(requests) == 1
    body["meta"]["access"] = {"mode": "api_key", "reason": None}
    transport(monkeypatch, body)
    result = await node({"operation": "get_usage", "verify_api_key": True}).execute({})
    assert result["success"] is True and result["api_key_verified"] is True
    del body["meta"]["access"]
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="omitted account-key"):
        await node({"operation": "get_usage", "verify_api_key": True}).execute({})
    assert native.GenderapiIoNode.connection_evidence.operation_arguments == {"verify_api_key": True}


@pytest.mark.asyncio
async def test_nested_ai_options_ids_unknown_and_mixed_batch_are_preserved(monkeypatch):
    body = fixture("prediction-unknown")
    requests = transport(monkeypatch, body)
    result = await node({"operation": "predict_name", "value": "zzzxxyy", "id": "contact-1", "options": {"ai_mode": "off"}}).execute({})
    assert result["data"]["gender"] is None and result["success"] is True
    assert json.loads(requests[0].content) == {"type": "name", "value": "zzzxxyy", "id": "contact-1", "options": {"ai_mode": "off"}}
    batch = {"data": [{"index": 0, "data": body["data"]}, {"index": 1, "error": {"code": "input_invalid"}}], "meta": body["meta"]}
    transport(monkeypatch, batch)
    result = await node({"operation": "predict_batch", "items": [{"type": "name", "value": "zzzxxyy"}, {"type": "email", "value": "alice@example.com"}]}).execute({})
    assert result["has_item_errors"] is True and result["data"] == batch["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 422, 429, 500])
async def test_problem_errors_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Denied " + TOKEN, "code": "api_key_invalid", "meta": {"usage": {"billing_status": "unconfirmed"}}}, status)
    result = await node({"operation": "get_usage"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == "Denied [redacted]" and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_timeout_never_retries_billable_request(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("timeout " + TOKEN))
    with pytest.raises(ValueError, match="outcome is unknown"):
        await node({"operation": "predict_name", "value": "Sophia"}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "predict_name", "value": " "},
    {"operation": "predict_name", "value": "Sophia\n"},
    {"operation": "predict_email", "value": "invalid"},
    {"operation": "predict_name", "value": "Sophia", "country": "ZZ"},
    {"operation": "predict_username", "value": "prenses", "forceToGenderize": True, "options": {"ai_mode": "off"}},
    {"operation": "predict_gender_get", "value": "prenses", "forceToGenderize": True, "ai_mode": "always"},
    {"operation": "predict_batch", "items": []},
    {"operation": "predict_batch", "items": [{"type": "name", "value": "Sophia", "id": "same"}] * 2},
    {"operation": "predict_batch", "items": [{"type": "name", "value": "Sophia"}] * 51},
    {"operation": "validate_phone", "number": "5321234567"},
    {"operation": "validate_phone", "number": "+90532123x567"},
    {"operation": "get_usage", "url": "https://attacker.example"},
])
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


@pytest.mark.parametrize("key", ["https://example.com", "Bearer abc", "abc\nInjected: yes", "<token>"])
def test_credential_shape_rejects_url_header_and_placeholder(key):
    with pytest.raises((ValidationError, ValueError)):
        native.GenderapiIoAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,reason,reachable", [("ip_trial", "api_key_missing", False), ("ip_trial", "api_key_invalid", False), ("ip_trial", "api_key_not_found", False), ("api_key", None, True)])
async def test_connection_evidence_classifies_trial_as_rejected(monkeypatch, mode, reason, reachable):
    from nodes.core import connection_evidence as ce
    body = fixture("usage-usage")
    body["meta"]["access"] = {"mode": mode, "reason": reason}
    requests = transport(monkeypatch, body)
    async def run_operation(**kwargs):
        assert kwargs["operation"] == "get_usage"
        assert kwargs["arguments"] == {"verify_api_key": True}
        return await node({"operation": kwargs["operation"], **kwargs["arguments"]}).execute({})
    monkeypatch.setattr("nodes.core.run_op.run_node_operation", run_operation)
    result = await ce.collect_evidence(node_type="automation-genderapi-io", credential_id=None,
        credential_data={"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}, user_id="fixture")
    assert result.reachable is reachable and len(requests) == 1
    if reason:
        assert reason in result.error
