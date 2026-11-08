"""Contract route, payload and account-evidence regressions; no live credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import streamtime_node as native
from nodes.core.registry import NodeFactory

TOKEN = "streamtime-unit-test-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="streamtime-test", node_type="automation-streamtime",
        node_data={"config": config, "credentials": {
            "credential_type": "streamtime_api_token", "api_token": TOKEN,
        }})


def mock_client(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_organisation"}, "GET", "/organisation"),
    ({"operation": "list_users"}, "GET", "/users"),
    ({"operation": "list_branches"}, "GET", "/branches"),
    ({"operation": "list_rate_cards"}, "GET", "/rate_cards"),
    ({"operation": "create_company", "name": "Acme Corporation", "isClient": True}, "POST", "/companies"),
    ({"operation": "get_company", "company_id": 2001}, "GET", "/companies/2001"),
    ({"operation": "update_company", "company_id": 2001, "notes": None, "isSupplier": False}, "PUT", "/companies/2001"),
    ({"operation": "list_company_contacts", "company_id": 2001}, "GET", "/companies/2001/contacts"),
    ({"operation": "create_contact", "company_id": 2001, "firstName": "Jane"}, "POST", "/companies/2001/contacts"),
    ({"operation": "get_contact", "contact_id": 501}, "GET", "/contacts/501"),
    ({"operation": "update_contact", "contact_id": 501, "email": "jane.doe@example.com"}, "PUT", "/contacts/501"),
    ({"operation": "create_job", "name": "Website Redesign", "rateCardId": 7}, "POST", "/jobs"),
    ({"operation": "get_job", "job_id": 601}, "GET", "/jobs/601"),
    ({"operation": "update_job", "job_id": 601, "jobStatus": {"id": 5}}, "PUT", "/jobs/601"),
    ({"operation": "update_job_status", "job_id": 601, "job_status_id": 2}, "PUT", "/jobs/601/job_status"),
    ({"operation": "list_job_items", "job_id": 601}, "GET", "/jobs/601/job_items"),
    ({"operation": "get_invoice", "invoice_id": 3456}, "GET", "/invoices/3456"),
    ({"operation": "get_quote", "quote_id": 42}, "GET", "/quotes/42"),
    ({"operation": "create_logged_time", "userId": 789, "date": "2025-08-15", "minutes": 90}, "POST", "/logged_times"),
    ({"operation": "get_logged_time", "logged_time_id": 12345}, "GET", "/logged_times/12345"),
    ({"operation": "update_logged_time", "logged_time_id": 12345, "minutes": 0, "private": False}, "PUT", "/logged_times/12345"),
    ({"operation": "delete_logged_time", "logged_time_id": 12345}, "DELETE", "/logged_times/12345"),
    ({"operation": "get_search_setup", "search_view": "jobs"}, "GET", "/search/setup"),
    ({"operation": "search_records", "search_view": "jobs", "query": 'job_status = "complete"', "limit": 30, "offset": 30}, "POST", "/search"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=[case[0]["operation"] for case in CASES])
async def test_published_routes_and_wire_payload(monkeypatch, config, method, path):
    payload = [{"id": 1, "name": "Account record"}] if config["operation"].startswith("list_") or config["operation"] == "search_records" else {"name": "Account record"}
    requests = mock_client(monkeypatch, payload)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": payload}
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.host, request.url.path) == (method, "api.streamtime.net", "/v2" + path)
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    query = {k: str(config[k]) for k in ("job_status_id", "search_view") if k in config}
    assert dict(request.url.params) == query
    if method in {"POST", "PUT"} and config["operation"] != "update_job_status":
        expected = {k: v for k, v in config.items() if k != "operation" and k not in query and not k.endswith("_id")}
        if config["operation"] == "search_records":
            expected.update(sortAscending=True, additionalData=[])
        assert json.loads(request.content) == expected
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_documented_account_response_and_evidence(monkeypatch):
    payload = json.loads((Path(__file__).parent / "fixtures/streamtime/organisation.json").read_text())
    mock_client(monkeypatch, payload)
    result = await node({"operation": "get_organisation"}).execute({})
    assert result["data"]["name"] == "Acme Ltd"
    assert native.StreamtimeNode.connection_evidence.operation == "list_users"
    assert native.StreamtimeNode.connection_evidence.identity_operation == "get_organisation"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_failure_is_not_success_and_redacts_token(monkeypatch, status):
    mock_client(monkeypatch, {"error": "Denied " + TOKEN}, status)
    result = await node({"operation": "get_organisation"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Denied" in result["error"] and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_empty_update_never_reaches_provider(monkeypatch):
    requests = mock_client(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one"):
        await node({"operation": "update_job", "job_id": 601}).execute({})
    assert requests == []


@pytest.mark.parametrize("config", [
    {"operation": "get_company", "company_id": "../users"},
    {"operation": "get_job", "job_id": 0},
    {"operation": "update_company", "company_id": 1, "branchId": 2},
    {"operation": "update_job_status", "job_id": 1, "job_status_id": 99},
    {"operation": "search_records", "search_view": "jobs", "query": "a", "limit": 1001},
])
def test_invalid_or_read_only_fields_are_rejected(config):
    assert native.StreamtimeNode.validate_config({"config": config})["valid"] is False


@pytest.mark.parametrize("token", ["Bearer secret", "https://example.com/key", "abc\nheader", "<token>"])
def test_invalid_token_shape(token):
    with pytest.raises((ValueError, ValidationError)):
        native.StreamtimeTokenCredential(api_token=token)
