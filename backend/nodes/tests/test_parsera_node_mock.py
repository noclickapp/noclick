"""Parsera request and response regressions using synthetic provider fixtures.

These exercise the real factory and manual credential models without a live
account, including asynchronous acceptance, errors, redaction and path refusal.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import parsera_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-parsera-key-42"
CASES = json.loads((Path(__file__).parent / "fixtures/parsera/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="parsera-fixture", node_type="automation-parsera",
        node_data={"config": config, "credentials": {"credential_type": "parsera_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_each_operation_exact_wire_and_raw_result(monkeypatch, case):
    requests = transport(monkeypatch, lambda _: httpx.Response(case["status"], json=case["response"]))
    config = {"operation": case["operation"], **case["config"]}
    result = await node(config).execute({})
    assert result == {"status": "success", "http_status": case["status"], "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url == native.BASE_URL + case["path"]
    assert request.headers["X-API-KEY"] == TOKEN and not request.url.query
    if request.content:
        body = json.loads(request.content)
        expected = {k: v for k, v in case["config"].items() if k not in {"task_id", "run_id", "scraper_id"}}
        assert all(body[k] == value for k, value in expected.items())
        assert "operation" not in body
    else:
        assert not case["config"] or case["method"] in {"GET", "DELETE"} or case["operation"] == "stop_agent_extraction"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_errors_and_redirects_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={"detail": "Rejected " + TOKEN}, headers={"Location": "https://example.com"}))
    result = await node({"operation": "create_classic_scraper"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Rejected" in result["message"] and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "Invalid API key"}, [{"id": "x"}], [{"id":"x","name":"X","type":"other"}]])
async def test_list_requires_documented_account_records(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({"operation": "list_scrapers"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_empty_account_and_nested_secret_redaction(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    assert (await node({"operation": "list_scrapers"}).execute({}))["data"] == []
    transport(monkeypatch, lambda _: httpx.Response(200, json={"items": [TOKEN]}))
    assert TOKEN not in str(await node({"operation": "get_classic_scraper", "scraper_id": "id"}).execute({}))


@pytest.mark.asyncio
async def test_transport_failure_and_invalid_json_are_not_success(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("secret " + TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "create_agent_scraper"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(requests) == 1
    transport(monkeypatch, lambda _: httpx.Response(200, text="<html>not json</html>"))
    assert (await node({"operation": "list_scrapers"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("operation,field", [("get_classic_scraper", "scraper_id"), ("get_agent_extraction_status", "task_id"), ("get_scraper_run_status", "run_id"), ("run_scraper", "template_id")])
@pytest.mark.parametrize("identifier", ["../other", "a/b", "x?token=oops", "x#y", "x%2fy"])
def test_path_injection_refused(operation, field, identifier):
    with pytest.raises(ValueError):
        node({"operation": operation, field: identifier})


def test_manual_credential_default_and_missing_credentials():
    assert native.ParseraAPIKeyCredential(api_key=TOKEN).credential_type == "parsera_api_key"
    with pytest.raises(ValidationError):
        native.ParseraAPIKeyCredential(api_key="bad key")
    schema = native.ParseraNode.get_config_schema()
    assert schema["$defs"]["ParseraAPIKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    assert len(CASES) == len(native.ROUTES) == 19
