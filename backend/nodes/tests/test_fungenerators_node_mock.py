"""Official examples copied from https://fungenerators.com/api/uuid/ and v1.5 YAML."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fungenerators_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures/fungenerators"
TOKEN = "synthetic-fungenerators-test-token"
UUID = "018f53b0-7387-717b-ae74-d3a326ba16cd"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def node(config):
    return NodeFactory.create_node(node_id="uuid-test", node_type=native.FungeneratorsNode.integration_type,
        node_data={"config": config, "credentials": {"credential_type": "fungenerators_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://other.example.test/"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, "0", "1", "2", "3", "4", "5", "6", "7"])
async def test_documented_generation_wire_and_rows(monkeypatch, version):
    calls = transport(monkeypatch, fixture("generate"))
    config = {"operation": "get_uuids", "limit": 2, "version": version}
    result = await node(config).execute({})
    assert result == {"status": "success", "count": 2, "items": fixture("generate")["contents"]}
    assert len(calls) == 1
    assert calls[0].method == "GET" and calls[0].url.host == "api.fungenerators.com"
    assert calls[0].url.path == "/uuid"
    assert dict(calls[0].url.params) == {"limit": "2", **({"version": version} if version is not None else {})}
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(calls[0].url) and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_parse_uses_current_get_query_and_provider_validity(monkeypatch):
    calls = transport(monkeypatch, fixture("parse"))
    result = await node({"operation": "parse_uuid", "uuid": UUID}).execute({})
    assert result == {"status": "success", "count": 1, "items": [{"uuid": UUID, "version": 7, "valid": True}]}
    assert calls[0].method == "GET" and calls[0].url.path == "/uuid/parse"
    assert dict(calls[0].url.params) == {"uuid": UUID} and calls[0].content == b""
    transport(monkeypatch, {"contents": {"valid": False}})
    result = await node({"operation": "parse_uuid", "uuid": "invalid + text"}).execute({})
    assert result["items"] == [{"uuid": "invalid + text", "valid": False}]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,name", [("get_uuids", "legacy_get"), ("parse_uuid", "legacy_post")])
async def test_published_legacy_envelopes(monkeypatch, operation, name):
    transport(monkeypatch, fixture(name))
    result = await node({"operation": operation, **({"uuid": UUID} if operation == "parse_uuid" else {})}).execute({})
    assert result["status"] == "success" and result["count"] == len(fixture(name)["contents"]["uuid"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
async def test_http_failure_is_not_success_or_secret_echo(monkeypatch, status):
    calls = transport(monkeypatch, {"error": {"message": TOKEN}}, status)
    result = await node({"operation": "get_uuids"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"contents": []}, {"contents": [{}]}, {"contents": [None]}])
async def test_incomplete_response_fails(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_uuids"}).execute({})


@pytest.mark.asyncio
async def test_json_error_envelope_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, {"error": {"code": 401, "message": TOKEN}})
    result = await node({"operation": "get_uuids"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


def test_manual_credential_default_and_schema_validation():
    credential = native.FungeneratorsAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "fungenerators_api_key"
    for config in [{"operation": "get_uuids", "limit": 0}, {"operation": "get_uuids", "version": "8"}, {"operation": "parse_uuid"}]:
        with pytest.raises(ConfigValidationError, match="Invalid configuration"):
            node(config)
    for secret in ["Bearer abc", "https://example.com", "x\ny"]:
        with pytest.raises(ValidationError):
            native.FungeneratorsAPIKeyCredential(api_key=secret)
