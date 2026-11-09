"""Offline Caspio v4 request, response and manual-connect regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import caspio_node as native
from nodes.core.registry import NodeFactory

TOKEN = "caspio-test-access-value-42"
CREDENTIAL = {"credential_type": "caspio_bearer_token", "api_base_url": "https://demo.caspio.com/integrations/rest", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/caspio/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="caspio-test", node_type="automation-caspio",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    requests = []

    def handle(request):
        requests.append(request)
        return response(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_caspio_published_operation_requests(monkeypatch, case):
    requests = transport(monkeypatch, lambda _: httpx.Response(case.get("status", 200), json=case["response"]))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/integrations/rest/v4" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.url.host == "demo.caspio.com"
    assert TOKEN not in str(result)
    if "body" in case:
        assert json.loads(request.content) == case["body"]
        assert request.headers["content-type"] == "application/json"
    else:
        assert not request.content
    for key, value in case["response"].items():
        assert result[key] == value


@pytest.mark.asyncio
async def test_caspio_record_query_case_and_composite_view_id(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={"data": [], "pagination": {"totalCount": 0, "pageNumber": 2, "pageSize": 10}}))
    await node({"operation": "list_table_records", "table_id": "abc123", "page_number": 2, "page_size": 10,
                "select": "Status,COUNT(*)", "where": "LastName=N'O''Brien'", "order_by": "Status ASC", "group_by": "Status"}).execute({})
    assert dict(requests[0].url.params) == {"PageNumber": "2", "PageSize": "10", "Select": "Status,COUNT(*)",
                                           "Where": "LastName=N'O''Brien'", "OrderBy": "Status ASC", "GroupBy": "Status"}
    await node({"operation": "get_view_record", "view_id": "abc123", "record_pk_id": "12,34"}).execute({})
    assert requests[1].url.path.endswith("/views/abc123/records/12,34")


@pytest.mark.parametrize("endpoint", [
    "http://abc123.caspio.com/rest", "https://caspio.com/rest", "https://abc123.caspio.com.evil.test/rest",
    "https://user@abc123.caspio.com/rest", "https://abc123.caspio.com:443/rest", "https://127.0.0.1/rest",
    "https://abc123.caspio.com/rest?token=bad", "https://abc123.caspio.com/rest#fragment",
    "https://abc123.caspio.com/rest/v4", "https://abc123.caspio.com/integrations/rest",
])
def test_caspio_refuses_untrusted_or_wrong_resource_endpoints(endpoint):
    with pytest.raises(ValidationError):
        native.CaspioBearerTokenCredential(**{**CREDENTIAL, "api_base_url": endpoint})


def test_caspio_manual_credential_default_and_explicit_token_instructions():
    shaped = native.CaspioBearerTokenCredential(api_base_url=" https://abc123.caspio.com/rest/ ", access_token=" " + TOKEN + " ")
    assert shaped.credential_type == "caspio_bearer_token"
    assert shaped.api_base_url == "https://abc123.caspio.com/rest"
    assert shaped.access_token == TOKEN
    assert native.CaspioNode.connection_evidence.operation == "list_tables"
    assert "24 hours" in native.CaspioBearerTokenCredential.model_json_schema()["x-credential-instructions"]


@pytest.mark.parametrize("changes", [{"table_id": "../../evil"}, {"record_pk_id": "1/2"}, {"values": {"PK_ID": 1}}, {"values": {}}, {"values": {"Value": float("nan")}}])
def test_caspio_rejects_invalid_write_config(changes):
    with pytest.raises(ValidationError):
        native.UpdateTableRecord.model_validate({"table_id": "abc123", "record_pk_id": "12", "values": {"Status": "Active"}, **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_caspio_failure_is_not_connection_evidence_and_never_retries(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, text="Rejected " + TOKEN))
    result = await node({"operation": "list_tables"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_caspio_write_timeout_is_ambiguous_and_not_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("sensitive details", request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "create_table_record", "table_id": "abc123", "values": {"Name": "Example"}}).execute({})
    assert result["status"] == "error" and "may have completed" in result["error"]
    assert "sensitive" not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [lambda: httpx.Response(200, text="<html>sign in</html>"),
                                  lambda: httpx.Response(200, json={"errors": ["Rejected"]}),
                                  lambda: httpx.Response(200, json=[{"name": "wrong shape"}])])
async def test_caspio_unexpected_response_is_not_success(monkeypatch, reply):
    transport(monkeypatch, lambda _: reply())
    assert (await node({"operation": "list_tables"}).execute({}))["status"] == "error"
