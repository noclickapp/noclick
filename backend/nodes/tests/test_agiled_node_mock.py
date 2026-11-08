"""Request-boundary tests against Agiled's documented v1 routes and bodies."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.agiled_node import AgiledAPITokenCredential, AgiledNode

CREDENTIAL = {"credential_type": "agiled_api_token", "api_token": "agiled-test-secret", "brand_url": "https://team.agiled.app"}
WRITES = json.loads((Path(__file__).parent / "fixtures/agiled/write_examples.json").read_text())
LISTS = [("contacts", "/contacts"), ("accounts", "/accounts"), ("projects", "/projects"),
    ("tasks", "/tasks"), ("deals", "/crm/deals"), ("pipelines", "/crm/pipelines"),
    ("pipeline_stages", "/crm/pipeline-stages"), ("invoices", "/invoices"),
    ("products", "/products"), ("currencies", "/currencies"), ("users", "/users")]
CASES = [({"operation": "list_" + kind}, "GET", path, None) for kind, path in LISTS]
for kind, body in WRITES.items():
    path = "/crm/deals" if kind == "deal" else "/" + kind + "s"
    CASES.append(({"operation": "create_" + kind, **body}, "POST", path, body))
    update = {k: v for k, v in body.items() if not (kind == "project" and k == "status")}
    CASES.append(({"operation": "update_" + kind, kind + "_id": 42, **update}, "PUT", path + "/42", update))
for kind in ("project", "task"):
    CASES.append(({"operation": "get_" + kind, kind + "_id": 42}, "GET", "/" + kind + "/42", None))


def node(config):
    data = {"config": config, "credentials": CREDENTIAL}
    return AgiledNode("test", "automation-agiled", data, config=AgiledNode.parse_config(data))


def fake_client(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr("nodes.agiled_node.guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_agiled_contract_requests(monkeypatch, config, method, path, body):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == method
        assert request.url.host == "my.agiled.app"
        assert request.url.path == "/api/v1" + path
        assert dict(request.url.params) == {"api_token": CREDENTIAL["api_token"]}
        assert request.headers["Brand"] == CREDENTIAL["brand_url"]
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200 if method == "GET" else 201, json={"data": [{"id": 42}], "links": {"next": None}})
    fake_client(monkeypatch, handler)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == {"data": [{"id": 42}], "links": {"next": None}}
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": "agiled-test-secret"}), (429, {}), (302, {}), (200, {"errors": ["rejected"]}), (200, "bad shape")])
async def test_agiled_errors_are_safe(monkeypatch, status, body):
    fake_client(monkeypatch, lambda r: httpx.Response(status, json=body))
    result = await node({"operation": "list_contacts"}).execute({})
    assert result["status"] == "error"
    assert CREDENTIAL["api_token"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_agiled_redacts_user_tokens_and_does_not_follow_pages(monkeypatch):
    fake_client(monkeypatch, lambda r: httpx.Response(200, json={"data": [{"api_token": "other-secret", "email": "test@example.com"}], "next": "https://evil.example/?token=agiled-test-secret"}))
    result = await node({"operation": "list_users"}).execute({})
    assert result["data"]["data"] == [{"email": "test@example.com"}]
    assert "secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_agiled_transport_error_hides_token(monkeypatch):
    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)
    fake_client(monkeypatch, fail)
    result = await node({"operation": "create_contact", "first_name": "John"}).execute({})
    assert result["status"] == "error"
    assert CREDENTIAL["api_token"] not in json.dumps(result)


@pytest.mark.parametrize("field,value", [("brand_url", ""), ("brand_url", "http://team.agiled.app"), ("brand_url", "https://user:pass@team.agiled.app"), ("api_token", "https://example.com"), ("api_token", "a\nb")])
def test_agiled_rejects_invalid_credentials(field, value):
    with pytest.raises(ValidationError):
        AgiledAPITokenCredential.model_validate({**CREDENTIAL, field: value})


def test_agiled_connection_evidence_is_credential_only_read():
    evidence = AgiledNode.connection_evidence
    assert evidence.operation == "list_contacts"
    assert node({"operation": evidence.operation}).config.config.operation == "list_contacts"


def test_agiled_requires_write_fields_and_safe_ids():
    for config in ({"operation": "create_task", "heading": "Test"}, {"operation": "get_task", "task_id": "../users"}, {"operation": "create_contact", "first_name": "John", "unknown": True}):
        with pytest.raises(ValueError):
            node(config)
