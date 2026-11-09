"""Offline SimpleLocalize request/response, connection and error regressions."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import simple_localize_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "synthetic-simplelocalize-project-key"
CASES = json.loads((Path(__file__).parent / "fixtures/simple-localize/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="simple-localize-test", node_type="automation-simple-localize",
        node_data={"config": config, "credentials": credential or {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, reply):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,query,body,data", CASES, ids=[row[0]["operation"] for row in CASES])
async def test_simple_localize_wire_contract(monkeypatch, config, method, path, query, body, data):
    payload = {"msg": "OK", "status": 200, **({"data": data} if data is not None else {})}
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.host == "api.simplelocalize.io" and request.url.path == path
    assert dict(request.url.params) == query
    assert request.headers["X-SimpleLocalize-Token"] == TOKEN
    assert "Authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body
    if data is not None:
        assert result["data"] == data  # Includes all page metadata; no silent aggregation.
    else:
        assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_simple_localize_empty_text_and_false_not_dropped(monkeypatch):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, content=b""))
    result = await node({"operation": "update_translation", "key": "HOME", "language": "en", "text": ""}).execute({})
    assert result["acknowledged"] is True
    assert json.loads(calls[0].content)["text"] == ""
    result = await node({"operation": "update_translation_key", "key": "HOME", "lock": False, "tags": []}).execute({})
    assert result["status"] == "success"
    assert json.loads(calls[1].content) == {"lock": False, "tags": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 409, 429, 500])
async def test_simple_localize_provider_rejection_and_no_retry(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, json={"msg": "Provider says invalid key " + TOKEN, "status": status}))
    result = await node({"operation": "get_project"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Provider says invalid key [redacted]"
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"status": 403, "msg": "Not allowed"}),
    httpx.Response(200, json={"error": "Bad"}),
    httpx.Response(200, json={"status": 200, "data": []}),
    httpx.Response(200, json={"status": 200, "data": {}}),
    httpx.Response(200, text="<html>Sign in</html>"),
    httpx.Response(200, json={"status": 200}),
])
async def test_simple_localize_malformed_project_cannot_prove_connection(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    result = await node({"operation": "get_project"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_simple_localize_no_retry_network_failure(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)
    calls = transport(monkeypatch, fail)
    result = await node({"operation": "create_language", "key": "en"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(calls) == 1


def test_simple_localize_manual_connection_and_discovery():
    shaped, errors, _ = shape_credential(native.CREDENTIAL_TYPE, {"api_key": "  " + TOKEN + "  "})
    assert not errors and shaped["api_key"] == TOKEN
    assert native.SimpleLocalizeAPIKeyCredential.model_validate(shaped).credential_type == native.CREDENTIAL_TYPE
    assert native.SimpleLocalizeNode.connection_evidence.identity_operation == "get_project"
    assert len(native.ROUTES) == 21


@pytest.mark.parametrize("config", [
    {"operation": "list_translations", "size": 2501},
    {"operation": "list_translations", "page": -1},
    {"operation": "list_translations", "base_only": "false"},
    {"operation": "update_translation", "key": "HOME", "language": "en"},
    {"operation": "get_language", "language_key": ".."},
    {"operation": "get_customer", "customer_key": "."},
    {"operation": "create_translation_key", "key": "HOME", "tags": ["x"] * 6},
    {"operation": "create_tag", "name": "hello", "color": "#123456"},
    {"operation": "get_project", "url": "https://evil.test"},
])
def test_simple_localize_invalid_config(config):
    assert native.SimpleLocalizeNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("operation,extra", [("update_language", {"language_key": "en"}), ("update_tag", {"tag_name": "hello"}), ("update_customer", {"customer_key": "acme"}), ("update_translation_key", {"key": "HOME"})])
@pytest.mark.asyncio
async def test_simple_localize_empty_patch_refused(monkeypatch, operation, extra):
    calls = transport(monkeypatch, lambda _: pytest.fail("No request expected"))
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": operation, **extra}).execute({})
    assert not calls


@pytest.mark.asyncio
async def test_simple_localize_path_encoding_and_secret_redaction(monkeypatch):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json={"status": 200, "data": {"key": "a/b ?#", "apiKey": TOKEN, "name": TOKEN}}))
    result = await node({"operation": "get_customer", "customer_key": "a/b ?#"}).execute({})
    assert calls[0].url.raw_path == b"/api/v1/customers/a%2Fb%20%3F%23"
    assert TOKEN not in str(result) and "apiKey" not in result["data"]


def test_simple_localize_foreign_credential_refused():
    with pytest.raises(ValueError):
        node({"operation": "get_project"}, {"credential_type": "another_api_key", "api_key": TOKEN})


@pytest.mark.asyncio
async def test_simple_localize_provider_documented_translation_response(monkeypatch):
    # Verbatim response: https://simplelocalize.io/docs/api/read-translations/
    body = json.loads((Path(__file__).parent / "fixtures/simple-localize/translations-response.json").read_text())
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    result = await node({"operation": "list_translations", "language": "en", "key": "HELLO_WORLD"}).execute({})
    assert result["status"] == "success" and result["data"] == body["data"]


@pytest.mark.asyncio
async def test_simple_localize_flat_page_details_are_preserved(monkeypatch):
    page = {"totalElements": 101, "totalPages": 2, "currentPage": 0, "hasNext": True, "first": True, "last": False}
    transport(monkeypatch, lambda _: httpx.Response(200, json={"status": 200, "data": [], "pageDetails": page}))
    result = await node({"operation": "list_translations"}).execute({})
    assert result["status"] == "success" and result["pageDetails"] == page
