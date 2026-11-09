"""Exercise DoorLoop routes, account evidence, list paging and typed writes offline.

These tests pin wire behavior and failures that a permissive provider schema
alone cannot prove, including secret handling and task notification choices.
"""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import doorloop_node as native
from nodes.core.registry import NodeFactory

ID = "507f191e810c19729de860ea"
TOKEN = "synthetic-doorloop-key"
CREDENTIAL = {"credential_type": "doorloop_api_key", "api_key": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=CREDENTIAL):
    return NodeFactory.create_node(node_id="doorloop-test", node_type="automation-doorloop",
        node_data={"config": config, "credentials": credential})


def transport(monkeypatch, body=None, status=200, raw=None):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if raw is None else httpx.Response(status, content=raw)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_bearer_auth_identity_and_manual_default(monkeypatch):
    requests = transport(monkeypatch, {"id": ID, "loginEmail": "manager@example.com", "active": True, "role": "Admin", "firstName": "Ada", "lastName": "Lovelace"})
    result = await node({"operation": "get_current_user"}).execute({})
    assert requests[0].url == "https://app.doorloop.com/api/users/me"
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN
    assert result["data"]["loginEmail"] == "manager@example.com"
    assert TOKEN not in str(result)
    assert native.DoorLoopAPIKeyCredential.model_validate({"api_key": TOKEN}).credential_type == "doorloop_api_key"
    assert native.DoorLoopNode.connection_evidence.identity_operation == "get_current_user"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,field", [
    ("get_property", "properties", "propertyId"), ("get_unit", "units", "unitId"),
    ("get_lease", "leases", "leaseId"), ("get_tenant", "tenants", "tenantId"),
    ("get_task", "tasks", "taskId"), ("get_owner", "owners", "ownerId"),
    ("get_vendor", "vendors", "vendorId"), ("get_lease_payment", "lease-payments", "leasePaymentId"),
    ("get_note", "notes", "noteId")])
async def test_resource_routes(monkeypatch, operation, path, field):
    requests = transport(monkeypatch, {"id": ID})
    result = await node({"operation": operation, field: ID}).execute({})
    assert result["data"]["id"] == ID
    assert requests[0].method == "GET" and requests[0].url.path == "/api/" + path + "/" + ID
    assert not requests[0].url.query and not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [
    ("list_properties", "properties"), ("list_units", "units"), ("list_leases", "leases"),
    ("list_tenants", "tenants"), ("list_tasks", "tasks"), ("list_owners", "owners"),
    ("list_vendors", "vendors"), ("list_lease_payments", "lease-payments"), ("list_notes", "notes")])
async def test_lists_have_explicit_disjoint_pages(monkeypatch, operation, path):
    requests = transport(monkeypatch, {"total": 105, "data": [{"id": ID}]})
    result = await node({"operation": operation, "page_number": 2, "page_size": 50}).execute({})
    assert len(requests) == 1 and requests[0].url.path == "/api/" + path
    assert dict(requests[0].url.params) == {"page_number": "2", "page_size": "50"}
    assert result["items"] == [{"id": ID}] and result["next_page_number"] == 3 and result["has_more"]
    result = await node({"operation": operation, "page_number": 3, "page_size": 50}).execute({})
    assert result["next_page_number"] is None and result["has_more"] is False


@pytest.mark.asyncio
async def test_query_encoding_boolean_date_and_false_filter(monkeypatch):
    requests = transport(monkeypatch, {"total": 0, "data": []})
    await node({"operation": "list_owners", "filter_active": False, "filter_text": "Ada + café", "filter_management_ends_before": "2026-12-31"}).execute({})
    assert requests[0].url.params["filter_active"] == "false"
    assert requests[0].url.params["filter_text"] == "Ada + café"
    assert requests[0].url.params["filter_management_ends_before"] == "2026-12-31"
    await node({"operation": "list_units", "filter_active": "all"}).execute({})
    assert requests[1].url.params["filter_active"] == "all"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("create_prospect", "tenants"), ("create_owner", "owners")])
async def test_person_write_shape(monkeypatch, operation, path):
    requests = transport(monkeypatch, {"id": ID})
    await node({"operation": operation, "firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.com", "phone": "+15555550100"}).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/api/" + path
    assert json.loads(requests[0].content) == {"firstName": "Ada", "lastName": "Lovelace", "emails": [{"type": "Primary", "address": "ada@example.com"}], "phones": [{"type": "Mobile", "number": "+15555550100"}], **({"active": True} if operation == "create_owner" else {})}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path", [("create_task", "POST", "/api/tasks"), ("update_task", "PUT", "/api/tasks/" + ID)])
async def test_task_write_has_required_fields_and_notification_opt_in(monkeypatch, operation, method, path):
    requests = transport(monkeypatch, {"id": ID})
    config = {"operation": operation, "subject": "Inspect faucet", "requestedByUser": ID, "dueDate": "2026-12-01", "assignedToUsers": [ID]}
    if operation == "update_task": config["taskId"] = ID
    await node(config).execute({})
    assert requests[0].method == method and requests[0].url.path == path
    assert json.loads(requests[0].content) == {"type": "INTERNAL_TASK", "subject": "Inspect faucet", "status": "NOT_STARTED", "requestedByUser": ID, "dueDate": "2026-12-01", "assignedToUsers": [ID], "notifyAssignees": False}
    await node({**config, "notifyAssignees": True}).execute({})
    assert json.loads(requests[1].content)["notifyAssignees"] is True


@pytest.mark.asyncio
async def test_note_relationship_and_tag_uniqueness(monkeypatch):
    requests = transport(monkeypatch, {"id": ID})
    await node({"operation": "create_note", "title": "Inspection", "body": "Complete", "resource_id": ID, "resource_type": "PROPERTY", "tags": [ID, ID]}).execute({})
    assert requests[0].method == "POST" and requests[0].url.path == "/api/notes"
    assert json.loads(requests[0].content) == {"title": "Inspection", "body": "Complete", "linkedResource": {"resourceId": ID, "resourceType": "PROPERTY"}, "tags": [ID]}


@pytest.mark.asyncio
async def test_delete_no_body_and_empty_success(monkeypatch):
    requests = transport(monkeypatch, status=204, raw=b"")
    result = await node({"operation": "delete_task", "taskId": ID}).execute({})
    assert requests[0].method == "DELETE" and requests[0].url.path == "/api/tasks/" + ID
    assert not requests[0].content
    assert result == {"status": "success", "deleted": True, "task_id": ID}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 405, 429, 500])
async def test_provider_rejection_is_not_success_and_redacts_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Access denied " + TOKEN}, status=status)
    result = await node({"operation": "get_current_user"}).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Access denied [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body,operation", [([], "get_current_user"), ({}, "get_current_user"), ({"error": "denied"}, "get_current_user"), ({"data": {} , "total": 1}, "list_properties"), ({"data": []}, "list_properties")])
async def test_malformed_success_is_not_connection_proof(monkeypatch, body, operation):
    transport(monkeypatch, body)
    with pytest.raises(ValueError): await node({"operation": operation}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_property", "propertyId": "../users/me"},
    {"operation": "list_units", "page_size": 1001},
    {"operation": "list_units", "page_number": 0},
    {"operation": "list_units", "filter_active": "sometimes"},
    {"operation": "create_task", "subject": "Inspect"},
    {"operation": "update_task", "taskId": ID, "requestedByUser": ID},
    {"operation": "create_owner", "firstName": "Ada"},
])
def test_invalid_config_is_rejected(config):
    with pytest.raises((ValidationError, ValueError)): node(config)


@pytest.mark.parametrize("key", ["Bearer some-key", "https://example.com", "key\nheader", "<token>"])
def test_invalid_manual_secret_is_rejected(key):
    with pytest.raises(ValidationError): native.DoorLoopAPIKeyCredential(api_key=key)
