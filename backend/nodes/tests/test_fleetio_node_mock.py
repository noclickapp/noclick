"""Fleetio native factory and wire-contract regressions; no live account calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fleetio_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "fleetio_api_key", "api_key": "synthetic-fleetio-key", "account_token": "synthetic-fleetio-account"}
CASES = json.loads((Path(__file__).parent / "fixtures/fleetio/requests.json").read_text())["cases"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="fleetio-test", node_type="automation-fleetio",
        node_data={"config": config, "credentials": CREDENTIAL if credentials is None else credentials})


def transport(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == 30
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_contract_methods_paths_headers_queries_bodies_and_output(monkeypatch, case):
    listing = case["config"]["operation"].startswith("list_")
    body = {"records": [{"id": 42, "name": "Vehicle 42"}], "per_page": 25, "next_cursor": "next+cursor/=="} if listing else {"id": 42, "name": "Vehicle 42"}
    status = 201 if case["config"]["operation"] in {"create_vehicle", "create_contact", "create_issue"} else 200
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json=body))
    output = await node(case["config"]).execute({})
    assert output["status"] == "success" and output["http_status"] == status
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "secure.fleetio.com" and request.url.scheme == "https"
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Token " + CREDENTIAL["api_key"]
    assert request.headers["Account-Token"] == CREDENTIAL["account_token"]
    assert request.headers["X-Api-Version"] == "2025-05-05"
    assert request.headers["Accept"] == "application/json"
    assert all(CREDENTIAL[k] not in str(output) for k in ("api_key", "account_token"))
    if listing:
        assert output["records"] == body["records"]
        assert output["next_cursor"] == "next+cursor/==" and output["has_more"]
    else:
        assert output["data"] == body
        assert output.get("write_acknowledged", False) == (case["method"] != "GET")
        assert "readback_verified" not in output


@pytest.mark.asyncio
async def test_connect_reads_account_vehicles_and_accepts_empty_fleet(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"records": [], "next_cursor": None, "per_page": 50}))
    evidence = native.FleetioNode.connection_evidence
    assert evidence.operation == "list_vehicles" and evidence.proves == "account"
    result = await node({"operation": evidence.operation}).execute({})
    assert result["records"] == [] and result["has_more"] is False
    assert requests[0].url.path == "/api/vehicles"
    assert dict(requests[0].url.params) == {"per_page": "50"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_rejections_preserve_provider_detail_redact_secrets_and_never_retry(monkeypatch, status):
    detail = "Access denied: " + CREDENTIAL["api_key"] + " " + CREDENTIAL["account_token"]
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"detail": detail}, headers={"Location": "https://other.example/"}))
    result = await node({"operation": "close_issue", "issue_id": "42", "note": "Fixed"}).execute({})
    assert result == {"status": "error", "error": "Access denied: [redacted] [redacted]", "http_status": status}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_transport_failure_is_unverified_and_not_retried(monkeypatch):
    def failure(request):
        raise httpx.ReadTimeout("timeout", request=request)
    requests = transport(monkeypatch, failure)
    result = await node({"operation": "reopen_issue", "issue_id": "42"}).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unverified"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"records": {}}, {"records": ["invalid"]}, {"records": [], "next_cursor": 9}, {"error": "rejected"}])
async def test_malformed_pages_never_report_success(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "list_vehicles"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"id": "42"}, {"id": 42, "errors": ["failed"]}])
async def test_malformed_records_never_acknowledge_writes(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "create_vendor", "name": "Shop"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_vehicle", "vehicle_id": "../contacts"},
    {"operation": "get_contact", "contact_id": "42?x=1"},
    {"operation": "list_vehicles", "per_page": 101},
    {"operation": "list_vehicles", "arbitrary_url": "https://other.example"},
    {"operation": "update_vendor", "vendor_id": "42"},
    {"operation": "close_issue", "issue_id": "42"},
    {"operation": "create_vehicle", "name": "Truck"},
    {"operation": "create_issue", "asset_id": 42, "asset_type": "Vehicle", "summary": "Lamp", "reported_at": "not-a-date"},
])
def test_invalid_inputs_fail_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        native.FleetioNode.parse_config({"config": config, "credentials": CREDENTIAL})


@pytest.mark.parametrize("field", ["api_key", "account_token"])
@pytest.mark.parametrize("value", ["", "Token supplied-key", "https://secure.fleetio.com/api_keys", "<token>", "key\r\nInjected: x", 123])
def test_manual_secret_shape_and_hidden_values(field, value):
    with pytest.raises(ValidationError):
        native.FleetioApiKeyCredential.model_validate({**CREDENTIAL, field: value})


def test_manual_credential_defaults_and_schema():
    credential = native.FleetioApiKeyCredential(api_key=" synthetic-key ", account_token=" synthetic-account ")
    assert credential.credential_type == "fleetio_api_key"
    assert credential.api_key == "synthetic-key" and credential.account_token == "synthetic-account"
    schema = native.FleetioApiKeyCredential.model_json_schema()
    assert schema["required"] == ["api_key", "account_token"]
    for field in schema["required"]:
        assert schema["properties"][field]["ui:widget"] == "password"
    assert len(CASES) == 25 and {c["config"]["operation"] for c in CASES} == set(native.ROUTES)
