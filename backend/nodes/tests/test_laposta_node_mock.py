"""Laposta's native factory and pinned v2 wire contract, using no live account."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import laposta_node as native
from nodes.core.registry import NodeFactory

KEY = "laposta-unit-test-key-8293"
ROUTES = json.loads((Path(__file__).parent / "fixtures/laposta/routes.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def config(operation):
    values = {"operation": operation, "list_id": "BaImMu3JZA", "member_id": "ZKfjhLJHfl",
        "field_id": "VfQ6fVjP0L", "campaign_id": "GDrmIezLsn", "name": "Newsletter",
        "email": "relatie@example.net", "ip": "198.51.100.10", "required": False,
        "html": "<p>Hello subscribers</p>"}
    model = next(c for c in native.LapostaConfig.__args__[0].__args__
        if c.model_fields["operation"].default == operation)
    return {k: v for k, v in values.items() if k in model.model_fields}


def node(cfg, credentials=None):
    return NodeFactory.create_node(node_id="laposta-fixture", node_type="automation-laposta",
        node_data={"config": cfg, "credentials": credentials or {"credential_type": "laposta_api_key", "api_key": KEY}})


def mock(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ROUTES)
async def test_every_operation_makes_one_exact_contract_request(monkeypatch, operation):
    route = ROUTES[operation]
    cfg = config(operation)
    body = {route["envelope"]: {"name": "Newsletter", "list_id": "BaImMu3JZA"}}
    if operation.startswith("list_"):
        body = {"data": [body]}
    status = 201 if route["method"] == "POST" and "{" not in route["path"] else 200
    requests = mock(monkeypatch, lambda req: httpx.Response(status, json=body))
    result = await node(cfg).run({})
    assert result["status"] == "success" and len(requests) == 1
    req = requests[0]
    assert req.method == route["method"]
    assert req.url.host == "api.laposta.nl" and req.url.path == "/v2" + route["path"].format(**cfg)
    assert req.headers["Authorization"] == "Basic " + base64.b64encode((KEY + ":").encode()).decode()
    assert dict(req.url.params) == {k: str(cfg[k]) for k in route["query"] if k in cfg}
    if req.method == "POST":
        fields = node(cfg).config.config.model_dump(exclude_none=True, exclude={"operation"})
        for key in cfg:
            if "{" + key + "}" in route["path"]:
                fields.pop(key)
        assert json.loads(req.content) == fields
    else:
        assert not req.content
    assert KEY not in str(result)


@pytest.mark.asyncio
async def test_custom_fields_preserve_arrays_and_scalar_values(monkeypatch):
    requests = mock(monkeypatch, lambda req: httpx.Response(201, json={"member": {"member_id": "ZKfjhLJHfl"}}))
    cfg = {**config("create_member"), "custom_fields": {"labels": ["Customer"], "city": "Zutphen", "points": 0}}
    assert (await node(cfg).execute({}))["status"] == "success"
    assert json.loads(requests[0].content)["custom_fields"] == cfg["custom_fields"]


@pytest.mark.asyncio
async def test_connection_evidence_lists_account_owned_names_and_empty_accounts(monkeypatch):
    assert native.LapostaNode.connection_evidence.operation == "list_lists"
    mock(monkeypatch, lambda req: httpx.Response(200, json={"data": [{"list": {"list_id": "BaImMu3JZA", "name": "Customers"}}]}))
    assert (await node({"operation": "list_lists"}).execute({}))["items"][0]["name"] == "Customers"
    mock(monkeypatch, lambda req: httpx.Response(200, json={"data": []}))
    assert (await node({"operation": "list_lists"}).execute({}))["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_errors_preserve_provider_words_and_redact_secret(monkeypatch, status):
    requests = mock(monkeypatch, lambda req: httpx.Response(status, json={"error": {"message": "Invalid API key " + KEY}}, headers={"Location": "https://other.example/"}))
    result = await node({"operation": "list_lists"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Invalid API key [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": {}}, {"data": [None]}, {"data": [{"list": None}]}, {"error": "Rejected", "data": []}])
async def test_malformed_success_responses_never_become_connection_proof(monkeypatch, body):
    mock(monkeypatch, lambda req: httpx.Response(200, json=body))
    assert (await node({"operation": "list_lists"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_timeouts_and_html_do_not_claim_success(monkeypatch):
    def timeout(req):
        raise httpx.ReadTimeout("timed out", request=req)
    mock(monkeypatch, timeout)
    assert (await node(config("update_member")).execute({}))["status"] == "error"
    mock(monkeypatch, lambda req: httpx.Response(200, text="<html>login</html>"))
    assert (await node(config("get_list")).execute({}))["status"] == "error"


@pytest.mark.parametrize("key", ["https://example.net/key", "<token>", "Basic abc", "abc:def"])
def test_invalid_credentials_are_rejected_without_echoing(key):
    with pytest.raises(ValueError):
        native.LapostaAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("cfg", [
    {"operation": "get_list", "list_id": "../outside"},
    {"operation": "create_member", "list_id": "BaImMu3JZA", "email": "bad", "ip": "198.51.100.10"},
    {"operation": "create_member", "list_id": "BaImMu3JZA", "email": "relatie@example.net", "ip": "bad"},
    {"operation": "get_list"},
    {"operation": "list_lists", "url": "https://example.net/"},
])
def test_configuration_rejects_wrong_paths_missing_inputs_and_unknown_fields(cfg):
    with pytest.raises((ValueError, ValidationError)):
        node(cfg)


DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/laposta/documented_responses.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", DOCUMENTED)
async def test_parser_accepts_provider_published_examples(monkeypatch, operation):
    fixture = DOCUMENTED[operation]
    assert fixture["source"].startswith("https://docs.laposta.org/")
    route = ROUTES[operation]
    status = 201 if route["method"] == "POST" and "{" not in route["path"] else 200
    mock(monkeypatch, lambda req: httpx.Response(status, json=fixture["body"]))
    result = await node(config(operation)).execute({})
    assert result["status"] == "success"
    if operation.startswith("list_"):
        assert result["items"] == [row[route["envelope"]] for row in fixture["body"]["data"]]
    else:
        assert result[route["envelope"]] == fixture["body"][route["envelope"]]


def test_invalid_operation_does_not_expose_attached_api_key():
    with pytest.raises(ValueError) as error:
        node({"operation": "unsupported"})
    assert KEY not in str(error.value)
