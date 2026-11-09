"""Penpot contract examples through the real factory; no provider account used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from jsonschema import RefResolver
from openapi_schema_validator import OAS30Validator, oas30_format_checker

from nodes import penpot_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/penpot/contract.json").read_text())
TOKEN = "synthetic-penpot-token-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="penpot-test", node_type="automation-penpot", node_data={
        "config": config, "credentials": credential or {"credential_type": "penpot_token", "access_token": TOKEN}})


def transport(monkeypatch, respond):
    seen = []
    client_class = httpx.AsyncClient
    def handler(request):
        seen.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return client_class(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_penpot_each_rpc_exact_route_body_and_documented_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    seen = transport(monkeypatch, lambda request: httpx.Response(200, json=example["response"]))
    result = await node({"operation": operation, **example["request"]}).execute({})
    assert result == {"status": "success", "data": example["response"]}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == example["url"]
    assert request.headers["authorization"] == "Token " + TOKEN
    assert request.headers["accept"] == "application/json"
    assert json.loads(request.content) == example["request"]
    contract = json.loads((Path(__file__).parent / "fixtures/penpot/request-schemas.json").read_text())
    schema = contract["schemas"][operation.replace("_", "-")]
    OAS30Validator(schema, resolver=RefResolver.from_schema(contract), format_checker=oas30_format_checker).validate(json.loads(request.content))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
async def test_penpot_errors_no_redirect_retry_or_token_leak(monkeypatch, status):
    seen = transport(monkeypatch, lambda request: httpx.Response(status, json={"hint": "Rejected " + TOKEN}, headers={"location": "https://example.test"}))
    result = await node({"operation": "get_profile"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(seen) == 1


@pytest.mark.asyncio
async def test_penpot_void_write_and_false_not_dropped(monkeypatch):
    seen = transport(monkeypatch, lambda request: httpx.Response(204))
    config = {"operation": "set_file_shared", "id": "3681d377-bc58-8110-8008-e76748b94999", "is_shared": False}
    assert (await node(config).execute({})) == {"status": "success", "data": None}
    assert json.loads(seen[0].content)["isShared"] is False


@pytest.mark.asyncio
async def test_penpot_html_and_malformed_json_fail(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ValueError, match="content type"):
        await node({"operation": "get_profile"}).execute({})
    transport(monkeypatch, lambda request: httpx.Response(200, content=b"{", headers={"content-type": "application/json"}))
    with pytest.raises(ValueError):
        await node({"operation": "get_profile"}).execute({})


@pytest.mark.asyncio
async def test_penpot_error_envelope_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"type": "authentication", "hint": "Token expired"}))
    result = await node({"operation": "get_profile"}).execute({})
    assert result == {"status": "error", "error": "Token expired"}


def test_penpot_schema_credential_manual_default_and_strict_operations():
    cred = native.PenpotTokenCredential(access_token=TOKEN)
    assert cred.credential_type == "penpot_token"
    assert native.PenpotNode.connection_evidence.operation == "get_teams"
    for config in [
        {"operation": "create_project", "name": "Design"},
        {"operation": "delete_file", "id": "../bad"},
        {"operation": "set_file_shared", "id": "3681d377-bc58-8110-8008-e76748b94999", "is_shared": "false"},
        {"operation": "login_with_password"},
    ]:
        with pytest.raises(ValueError):
            node(config)
    for token in ["https://example.test/token", "Token abc", "abc\nxyz"]:
        with pytest.raises(ValidationError):
            native.PenpotTokenCredential(access_token=token)
