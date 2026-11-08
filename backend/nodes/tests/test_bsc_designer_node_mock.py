"""Request-level BSC Designer regressions; all credentials and responses are fake."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import bsc_designer_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-bsc-designer-secret"
CREDENTIAL = {"credential_type": "bsc_designer_api_token", "api_token": TOKEN}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/bsc-designer/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bsc-fixture", node_type="automation-bsc-designer",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config_for(operation):
    cfg = {"operation": operation}
    path = native.OPERATIONS[operation][1]
    if "{document_id}" in path:
        cfg["document_id"] = 123
    if "{indicator_guid}" in path:
        cfg["indicator_guid"] = "indicator-guid"
    if "{date}" in path:
        cfg["date"] = "2026-11-09"
    if "{map_id}" in path:
        cfg["map_id"] = "strategy-map-guid"
    if "{custom_field_id}" in path:
        cfg["custom_field_id"] = 101
    bodies = {
        "create_document": {"document": {"parentGroupId": 123}},
        "update_document": {"document": {"name": "Revenue", "sharedForPublic": False}},
        "update_indicator": {"indicator": {"name": "Monthly revenue", "indicatorType": "LEADING"}},
        "set_indicator_value": {"data": {"value": 0, "target": 100}},
        "get_selected_values": {"selection": {"guids": ["indicator-guid"]}},
        "set_selected_values": {"data": {"values": [{"item": {"guid": "indicator-guid"}, "value": 42}]}},
        "set_custom_value": {"data": {"text": "EMEA"}},
    }
    return {**cfg, **bodies.get(operation, {})}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURE)
async def test_each_operation_matches_one_contract_route_and_body(monkeypatch, operation):
    method, template, body_field, kind, _ = native.OPERATIONS[operation]
    cfg = config_for(operation)
    body = [] if kind == "array" else {"documents": []} if operation == "list_documents" else {"name": "Example"}
    requests = transport(monkeypatch, None if kind == "empty" else body)
    result = await node(cfg).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == FIXTURE[operation]["method"]
    expected = template
    for key, value in cfg.items():
        expected = expected.replace("{" + key + "}", str(value))
    assert request.url.path == expected
    assert request.url.host == "www.webbsc.com" and request.url.scheme == "https"
    assert not request.url.query and request.headers["token"] == TOKEN
    assert TOKEN not in str(result)
    if body_field:
        assert json.loads(request.content) == cfg[body_field]
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert not request.content
    if kind == "empty":
        assert result == {"acknowledged": True, "http_status": 200}
    else:
        assert result == {"data": body}


@pytest.mark.asyncio
async def test_create_empty_document_and_explicit_null_custom_value(monkeypatch):
    requests = transport(monkeypatch, {"id": 123})
    await node({"operation": "create_document", "document": {}}).execute({})
    assert json.loads(requests[0].content) == {}
    requests = transport(monkeypatch, {"text": None, "value": None})
    cfg = {**config_for("set_custom_value"), "data": {"value": None}}
    assert (await node(cfg).execute({}))["data"]["value"] is None
    assert json.loads(requests[0].content) == {"value": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_failure_not_retried_and_secret_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_documents"}).execute({})
    assert f"HTTP {status}" in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], None, {"error": "denied"}, {"errors": ["denied"]}])
async def test_bad_read_response_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        await node({"operation": "list_documents"}).execute({})


@pytest.mark.asyncio
async def test_omitted_and_blank_fields_preserve_zero_and_false(monkeypatch):
    requests = transport(monkeypatch, {"id": 123})
    await node({"operation": "update_document", "document_id": 123,
        "document": {"name": None, "sharedForPublic": False}}).execute({})
    assert json.loads(requests[0].content) == {"sharedForPublic": False}


@pytest.mark.asyncio
async def test_empty_write_refused_before_network_and_delete_204(monkeypatch):
    requests = transport(monkeypatch, None, 204)
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_document", "document_id": 123, "document": {}}).execute({})
    assert requests == []
    result = await node(config_for("delete_document")).execute({})
    assert result == {"acknowledged": True, "http_status": 204} and len(requests) == 1


def test_credential_default_password_widget_and_read_evidence():
    credential = native.BscDesignerAPITokenCredential(api_token="  " + TOKEN + "  ")
    assert credential.credential_type == CREDENTIAL["credential_type"] and credential.api_token == TOKEN
    schema = native.BscDesignerAPITokenCredential.model_json_schema()
    assert schema["properties"]["api_token"]["ui:widget"] == "password"
    assert native.BscDesignerNode.connection_evidence.operation == "list_documents"
    assert len(FIXTURE) == 23


@pytest.mark.parametrize("token", ["https://www.webbsc.com/", "bad\r\nheader", "<token>"])
def test_invalid_tokens(token):
    with pytest.raises(ValueError):
        native.BscDesignerAPITokenCredential(api_token=token)


@pytest.mark.parametrize("changes", [{"document_id": ".."}, {"indicator_guid": "."}, {"document_id": "../secret"}, {"document_id": "a/b"}, {"indicator_guid": "x?token=other"}, {"date": "2026-02-30"}])
def test_invalid_paths_and_dates(changes):
    with pytest.raises((ValidationError, ValueError)):
        node({**config_for("get_indicator_value"), **changes})
