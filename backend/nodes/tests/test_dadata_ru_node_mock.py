"""Transport-level Dadata contract tests; no provider credentials or sockets."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dadata_ru_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/dadata_ru/contract_examples.json").read_text())

CREDENTIAL = {"credential_type": "dadata_ru_api_key", "api_key": "synthetic-api-key", "secret_key": "synthetic-secret-key"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="dadata-fixture", node_type="automation-dadata-ru",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
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
@pytest.mark.parametrize("operation,method,url", [(op, *route) for op, route in native.ROUTES.items()])
async def test_every_fixed_operation_exact_route_auth_and_payload(monkeypatch, operation, method, url):
    config = {"operation": operation}
    if operation in {"get_balance", "get_daily_stats", "get_versions"}:
        body = EXAMPLES["balance"]["body"] if operation == "get_balance" else {"services": {}}
    elif operation == "clean_record":
        config.update(structure=["NAME", "PHONE"], data=[["Федотов Алексей", "8 916 823 3454"]])
        body = {"structure": ["NAME", "PHONE"], "data": [[{"result": "Федотов Алексей"}, {"phone": "+7 916 823-34-54"}]]}
    elif operation == "ip_locate_address":
        config["ip"] = "46.226.227.20"
        body = {"location": None}
    elif operation == "geo_locate_address":
        config.update(lat=55.878, lon=37.653)
        body = {"suggestions": []}
    else:
        config["query"] = "москва хабар" if operation == "suggest_address" else "7707083893"
        body = {"suggestions": [{"value": "Documented candidate", "data": {"inn": "7707083893"}}]}
    requests = transport(monkeypatch, body)
    output = await node(config).execute({})
    assert output["status"] == "success" and output["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url) == url
    assert request.headers["Authorization"] == "Token " + CREDENTIAL["api_key"]
    assert request.headers.get("X-Secret") == (None if request.url.host == "suggestions.dadata.ru" else CREDENTIAL["secret_key"])
    assert dict(request.url.params) == {}
    expected = node(config).config.config.model_dump(exclude={"operation"}, exclude_none=True)
    assert (json.loads(request.content) if method == "POST" else {}) == (expected if method == "POST" else {})


@pytest.mark.asyncio
@pytest.mark.parametrize("data_type", ["address", "name", "phone", "birthdate", "email", "vehicle", "passport"])
async def test_cleaning_lowercase_route_and_top_level_array(monkeypatch, data_type):
    requests = transport(monkeypatch, [{"source": "sample", "result": "parsed", "qc": 0}])
    output = await node({"operation": "clean_data", "data_type": data_type, "data": ["sample"]}).execute({})
    assert output["status"] == "success"
    assert str(requests[0].url) == "https://cleaner.dadata.ru/api/v1/clean/" + data_type
    assert json.loads(requests[0].content) == ["sample"]
    assert requests[0].headers["X-Secret"] == CREDENTIAL["secret_key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_provider_rejections_do_not_succeed_or_leak_secrets(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + CREDENTIAL["api_key"] + CREDENTIAL["secret_key"]}, status)
    output = await node({"operation": "get_balance"}).execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert "Rejected" in output["message"] and len(requests) == 1
    assert all(secret not in str(output) for secret in (CREDENTIAL["api_key"], CREDENTIAL["secret_key"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"balance": True}, {"balance": "9922.30"}, {"error": "bad"}])
async def test_balance_evidence_requires_numeric_account_balance(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "get_balance"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_connection_evidence_and_optional_filters(monkeypatch):
    transport(monkeypatch, {"balance": 0})
    result = await node({"operation": "get_balance"}).execute({})
    assert result["items"] == [{"label": "Balance: 0 RUB"}]
    assert native.DadataRuNode.connection_evidence.operation == "get_balance"
    requests = transport(monkeypatch, {"suggestions": []})
    config = {"operation": "find_party", "query": "7707083893", "kpp": "773601001", "type": "LEGAL", "branch_type": ["MAIN"], "status": ["ACTIVE"], "count": 2}
    assert (await node(config).execute({}))["status"] == "success"
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}


@pytest.mark.parametrize("config", [
    {"operation": "geo_locate_address", "lat": 91, "lon": 0},
    {"operation": "ip_locate_address", "ip": "https://evil.test"},
    {"operation": "suggest_address", "query": "x", "count": 21},
    {"operation": "clean_data", "data_type": "../address", "data": ["x"]},
    {"operation": "clean_record", "structure": ["NAME"], "data": [["x", "y"]]},
])
def test_invalid_inputs_rejected_before_transport(config):
    with pytest.raises(ValueError):
        node(config)


def test_credential_manual_fields_and_default_type():
    credential = native.DadataRuCredential(api_key=" synthetic-api-key ", secret_key="synthetic-secret-key")
    assert credential.credential_type == "dadata_ru_api_key" and credential.api_key == "synthetic-api-key"
    assert set(native.DadataRuCredential.model_fields) == {"credential_type", "api_key", "secret_key"}
    with pytest.raises(ValidationError):
        native.DadataRuCredential(api_key="https://dadata.ru/key", secret_key="synthetic-secret-key")
