"""Offline GorillaDesk wire regressions; no live account is used."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import gorilladesk_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/gorilladesk/responses.json").read_text())
TOKEN = "synthetic-gorilladesk-key"


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="gorilladesk-test", node_type="automation-gorilladesk",
        node_data={"config": config, "credentials": credentials or {"credential_type": "gorilladesk_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200, headers=None):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [[{'operation': 'get_company'}, 'GET', '/company'], [{'operation': 'list_users'}, 'GET', '/users'], [{'operation': 'get_user', 'user_id': '0nk8PGvAO'}, 'GET', '/users/0nk8PGvAO'], [{'operation': 'list_customers'}, 'GET', '/customers'], [{'operation': 'get_customer', 'customer_id': '0nk8PGvAO'}, 'GET', '/customers/0nk8PGvAO'], [{'operation': 'create_customer', 'first_name': 'John', 'location': {'address_line_1': '523 East 72nd Street', 'city': 'New York', 'state': 'NY', 'zip': '10021'}}, 'POST', '/customers'], [{'operation': 'update_customer', 'customer_id': '0nk8PGvAO', 'first_name': 'John'}, 'PUT', '/customers/0nk8PGvAO'], [{'operation': 'add_customer_location', 'customer_id': '0nk8PGvAO', 'address_line_1': '523 East 72nd Street', 'city': 'New York', 'state': 'NY', 'zip': '10021'}, 'POST', '/customers/0nk8PGvAO/locations'], [{'operation': 'create_customer_note', 'customer_id': '0nk8PGvAO', 'content': 'Lorem, ipsum dolor sit amet consectetur adipisicing elit'}, 'POST', '/customers/0nk8PGvAO/notes'], [{'operation': 'list_leads'}, 'GET', '/leads'], [{'operation': 'list_jobs'}, 'GET', '/jobs'], [{'operation': 'get_job', 'job_id': '0nk8PGvAO'}, 'GET', '/jobs/0nk8PGvAO'], [{'operation': 'list_job_activities', 'job_id': '0nk8PGvAO'}, 'GET', '/jobs/0nk8PGvAO/activities'], [{'operation': 'list_invoices'}, 'GET', '/invoices'], [{'operation': 'get_invoice', 'invoice_id': '0nk8PGvAO'}, 'GET', '/invoices/0nk8PGvAO'], [{'operation': 'list_estimates'}, 'GET', '/estimates'], [{'operation': 'get_estimate', 'estimate_id': '0nk8PGvAO'}, 'GET', '/estimates/0nk8PGvAO'], [{'operation': 'list_payments'}, 'GET', '/payments'], [{'operation': 'get_payment', 'payment_id': '0nk8PGvAO'}, 'GET', '/payments/0nk8PGvAO'], [{'operation': 'list_schedules'}, 'GET', '/schedules'], [{'operation': 'get_schedule', 'schedule_id': '0nk8PGvAO'}, 'GET', '/schedules/0nk8PGvAO'], [{'operation': 'list_services'}, 'GET', '/services'], [{'operation': 'list_branches'}, 'GET', '/branches'], [{'operation': 'list_sources'}, 'GET', '/sources'], [{'operation': 'list_job_statuses'}, 'GET', '/job-statuses']]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES)
async def test_gorilladesk_one_documented_request_per_operation(monkeypatch, config, method, path):
    listing = config["operation"].startswith("list_")
    response = {"data": [{"id": "0nk8PGvAO"}], "has_more": False} if listing else FIXTURE["company"] if config["operation"] == "get_company" else FIXTURE["write"]
    requests = transport(monkeypatch, response)
    output = await node(config).execute({})
    assert output["data"] == response["data"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + path
    assert request.url.host == "api.gorilladesk.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method in {"POST", "PUT"}:
        if config["operation"] == "create_customer_note":
            assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
            assert b'name="content"' in request.content and config["content"].encode() in request.content
        else:
            expected = {k: v for k, v in config.items() if k not in {"operation", "customer_id"}}
            assert json.loads(request.content) == expected


@pytest.mark.asyncio
async def test_gorilladesk_pagination_and_filter_wire_names(monkeypatch):
    requests = transport(monkeypatch, {"data": [{"id": "0nk8PGvAO"}], "has_more": True})
    output = await node({"operation": "list_jobs", "limit": 1, "offset": 20, "customer_id": "0nk8PGvAO", "date_gte": "2026-07-01T00:00:00+00:00", "keyword": "a + b"}).execute({})
    assert output["next_offset"] == 21
    assert dict(requests[0].url.params) == {"limit": "1", "offset": "20", "customer_id": "0nk8PGvAO", "date[gte]": "2026-07-01T00:00:00+00:00", "keyword": "a + b"}


@pytest.mark.asyncio
async def test_gorilladesk_company_connect_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, FIXTURE["company"])
    result = await collect_evidence(node_type="automation-gorilladesk", user_id="gorilladesk-test", credential_data={"credential_type": "gorilladesk_api_key", "api_key": TOKEN})
    assert result.reachable is True and result.account_label == "Pest Control"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_gorilladesk_errors_do_not_retry_or_leak_key(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Rejected " + TOKEN}, status=status, headers={"x-rate-limit-reset": "10"})
    with pytest.raises(ValueError) as caught:
        await node({"operation": "get_company"}).execute({})
    assert TOKEN not in str(caught.value) and str(status) in str(caught.value)
    assert len(requests) == 1
    if status == 429: assert "retry after 10 seconds" in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "rejected"}, {"data": []}, {"data": None}, {}])
async def test_gorilladesk_bad_company_envelope_fails(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError): await node({"operation": "get_company"}).execute({})


@pytest.mark.asyncio
async def test_gorilladesk_bad_page_cannot_spin(monkeypatch):
    transport(monkeypatch, {"data": [], "has_more": True})
    with pytest.raises(ValueError): await node({"operation": "list_customers"}).execute({})


@pytest.mark.parametrize("resource_id", ["../company", "a/b", "x?include=contacts", "x#", " x "])
def test_gorilladesk_rejects_path_injection(resource_id):
    with pytest.raises(ValueError): node({"operation": "get_customer", "customer_id": resource_id})


@pytest.mark.parametrize("config", [
    {"operation": "create_customer", "first_name": "John"},
    {"operation": "add_customer_location", "customer_id": "0nk8PGvAO", "city": "New York"},
    {"operation": "update_customer", "customer_id": "0nk8PGvAO"},
    {"operation": "list_customers", "limit": 101},
    {"operation": "list_jobs", "offset": -1},
    {"operation": "create_customer_note", "customer_id": "0nk8PGvAO", "content": ""},
])
def test_gorilladesk_contract_required_fields(config):
    with pytest.raises(ValueError): node(config)


def test_gorilladesk_wrong_credential_family_refused():
    with pytest.raises(ValueError):
        native.GorillaDeskAPIKeyCredential.model_validate({"credential_type": "other_key", "api_key": TOKEN})


@pytest.mark.asyncio
async def test_gorilladesk_rejected_key_connect_verdict(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"message": "Invalid API key"}, status=401)
    result = await collect_evidence(node_type="automation-gorilladesk", user_id="gorilladesk-test",
        credential_data={"credential_type": "gorilladesk_api_key", "api_key": TOKEN})
    assert result.reachable is False and "Invalid API key" in result.error
