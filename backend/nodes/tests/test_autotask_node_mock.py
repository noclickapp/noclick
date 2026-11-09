"""Autotask wire contracts, manual connection and documented response regressions.

All credentials are synthetic; no requests reach a provider account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import autotask_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {
    "credential_type": "autotask_api_key", "username": "apiuser@example.com",
    "secret": "synthetic-autotask-secret-42", "api_integration_code": "synthetic-tracking-id-42",
}
FIXTURE = Path(__file__).parent / "fixtures/autotask/documented.json"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="autotask-test", node_type="automation-autotask",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, body=None, *, status=200, headers=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def page(items=None, next_url=None):
    return {"items": [{"id": 4, "companyName": "A Company"}] if items is None else items,
        "pageDetails": {"count": 1, "requestCount": 100, "prevPageUrl": None, "nextPageUrl": next_url}}


CREATES = {
    "create_ticket": {"company_id": 4, "title": "Printer offline", "priority": 1, "status": 1,
        "due_date_time": "2026-11-10T12:00:00.000Z", "assigned_resource_id": 5},
    "create_company": {"company_name": "A Company", "company_type": 1, "owner_resource_id": 4, "phone": "5555555555"},
    "create_contact": {"company_id": 4, "first_name": "Tom", "last_name": "Smith"},
    "create_time_entry": {"ticket_id": 4, "resource_id": 5, "role_id": 6, "date_worked": "2026-11-09T00:00:00.000Z",
        "hours_worked": 0.5, "summary_notes": "Replaced toner"},
    "create_ticket_note": {"ticket_id": 4, "title": "Progress", "description": "Toner replaced", "note_type": 1, "publish": 1},
}
UPDATES = {
    "update_ticket": {"id": 4, "status": 5, "resolution": "Fixed"},
    "update_company": {"id": 4, "phone": "5555555555", "is_active": False},
    "update_contact": {"id": 4, "company_id": 4, "email_address": "tom@example.com", "is_active": 0},
    "update_time_entry": {"id": 4, "hours_worked": 0.75, "is_non_billable": False},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(native.ROUTES))
async def test_factory_all_twenty_operations_one_request_exact_route_and_headers(monkeypatch, operation):
    method, path, kind = native.ROUTES[operation]
    cfg = {"operation": operation}
    if kind == "item":
        cfg["id"] = 4
        body = {"item": {"id": 4}}
    elif kind == "write":
        cfg.update({**CREATES, **UPDATES}[operation])
        body = {"itemId": 4}
    else:
        if operation == "list_ticket_notes":
            cfg["ticket_id"] = 4
            body = page([{"id": 4, "ticketID": 4, "title": "Progress"}])
        else:
            body = page()
    requests = transport(monkeypatch, body)
    result = await node(cfg).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "webservices5.autotask.net"
    assert request.url.path == "/ATServicesRest" + path.format(**cfg)
    assert request.headers["UserName"] == CREDENTIAL["username"]
    assert request.headers["Secret"] == CREDENTIAL["secret"]
    assert request.headers["ApiIntegrationCode"] == CREDENTIAL["api_integration_code"]
    assert "authorization" not in request.headers
    if kind == "write":
        sent = json.loads(request.content)
        assert "operation" not in sent
        assert "id" not in sent or operation in UPDATES
        assert "maxRecords" not in sent
        if operation in {"create_contact", "update_contact"}:
            assert request.url.path == "/ATServicesRest/V1.0/Companies/4/Contacts"
        if operation == "update_contact":
            assert "companyID" not in sent
        for key, value in cfg.items():
            if key != "operation" and not (operation == "update_contact" and key == "company_id"):
                assert sent[native.WIRE_FIELDS[key]] == value
        if operation == "create_contact":
            assert sent["isActive"] == 1
    elif kind == "list" and operation != "list_ticket_notes":
        assert json.loads(request.content) == {"maxRecords": 100, "filter": [{"op": "exist", "field": "id"}]}
    else:
        assert request.content == b""
    assert CREDENTIAL["secret"] not in str(result)


@pytest.mark.asyncio
async def test_documented_scalar_filter_and_explicit_paging_without_following_url(monkeypatch):
    response = page(next_url="https://webservices5.autotask.net/ATServicesRest/V1.0/Companies/query/next?paging=opaque")
    requests = transport(monkeypatch, response)
    result = await node({"operation": "list_companies", "max_records": 10,
        "filter_json": '[{"op":"eq","field":"CompanyName","value":"ACME Corp"}]'}).execute({})
    assert result["has_more"] and result["next_after_id"] == 4
    assert len(requests) == 1
    assert json.loads(requests[0].content)["filter"][0]["value"] == "ACME Corp"
    requests = transport(monkeypatch, page([]))
    result = await node({"operation": "list_companies", "filter_json": '[{"op":"gt","field":"id","value":4}]'}).execute({})
    assert not result["has_more"] and result["items"] == []
    assert json.loads(requests[0].content)["filter"][0]["value"] == 4


@pytest.mark.asyncio
async def test_documented_mutation_id_fixture(monkeypatch):
    fixture = json.loads(FIXTURE.read_text())
    transport(monkeypatch, fixture["mutation"]["body"])
    result = await node({"operation": "create_company", **CREATES["create_company"]}).execute({})
    assert result == {"status": "success", "item_id": 4}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_rejection_errors_preserved_and_secrets_redacted_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"errors": ["Denied for " + CREDENTIAL["secret"]]}, status=status,
        headers={"Location": "https://foreign.example/"})
    result = await node({"operation": "create_company", **CREATES["create_company"]}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Denied for [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"items": []}, {"items": [], "pageDetails": {}},
    {"items": ["bad"], "pageDetails": {"nextPageUrl": None}}, page([], "https://example.com/next")])
async def test_missing_or_malformed_page_never_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_companies"}).execute({})


@pytest.mark.asyncio
async def test_error_envelope_wrong_item_and_note_parent(monkeypatch):
    transport(monkeypatch, {"errors": ["Insufficient permissions"]})
    assert (await node({"operation": "list_companies"}).execute({}))["status"] == "error"
    transport(monkeypatch, {"item": {"id": 5}})
    with pytest.raises(ValueError, match="different record"):
        await node({"operation": "get_ticket", "id": 4}).execute({})
    transport(monkeypatch, page([{"id": 8, "ticketID": 5}]))
    with pytest.raises(ValueError, match="different ticket"):
        await node({"operation": "list_ticket_notes", "ticket_id": 4}).execute({})
    transport(monkeypatch, {"itemId": {}})
    with pytest.raises(ValueError, match="confirm"):
        await node({"operation": "create_company", **CREATES["create_company"]}).execute({})


def test_manual_credential_defaults_and_regional_url_validation():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential("autotask_api_key", {k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert not errors
    assert resolved is not None
    assert native.AutotaskAPIKeyCredential.model_validate(shaped).credential_type == "autotask_api_key"
    cred = native.AutotaskAPIKeyCredential(**CREDENTIAL, api_base_url="https://webservices3.autotask.net/atservicesrest/")
    assert cred.api_base_url == "https://webservices3.autotask.net/ATServicesRest"
    for url in ["http://webservices5.autotask.net/ATServicesRest", "https://webservices5.autotask.net.evil.test/ATServicesRest",
        "https://webservices5.autotask.net:443/ATServicesRest", "https://127.0.0.1/ATServicesRest",
        "https://webservices5.autotask.net/ATServicesRest?redirect=evil", "https://x@webservices5.autotask.net/ATServicesRest"]:
        with pytest.raises(ValidationError):
            native.AutotaskAPIKeyCredential(**CREDENTIAL, api_base_url=url)
    with pytest.raises(ValidationError):
        native.AutotaskAPIKeyCredential(**{**CREDENTIAL, "secret": "bad\r\nInjected: yes"})


@pytest.mark.parametrize("cfg", [
    {"operation": "update_ticket", "id": 4}, {"operation": "get_company", "id": -1},
    {"operation": "list_tickets", "max_records": 501}, {"operation": "list_companies", "filter_json": "{}"},
    {"operation": "list_companies", "filter_json": '[{"op":"eq","field":"id"}]'},
    {"operation": "list_companies", "filter_json": '[{"op":"eq","field":"id","value":{}}]'},
    {"operation": "create_ticket", **CREATES["create_ticket"], "due_date_time": "tomorrow"},
    {"operation": "create_time_entry", **CREATES["create_time_entry"], "hours_worked": -1},
    {"operation": "create_company", **CREATES["create_company"], "raw_body": {"anything": True}},
])
def test_invalid_configs_rejected_before_io(cfg):
    with pytest.raises((ValidationError, ValueError)):
        node(cfg)


@pytest.mark.asyncio
async def test_provider_company_example_nullable_paging_udfs_and_utc_normalization(monkeypatch):
    fixture = json.loads(FIXTURE.read_text())
    transport(monkeypatch, fixture["company_page"]["body"])
    result = await node({"operation": "list_companies"}).execute({})
    assert result["items"][0]["companyName"] == " Union Second Market Bank"
    assert result["items"][1]["userDefinedFields"][1]["value"] == 50
    assert result["has_more"] is False
    requests = transport(monkeypatch, {"itemId": 4})
    await node({"operation": "create_ticket", **CREATES["create_ticket"],
        "due_date_time": "2023-10-09T02:00:00.00"}).execute({})
    assert json.loads(requests[0].content)["dueDateTime"] == "2023-10-09T02:00:00.000Z"
