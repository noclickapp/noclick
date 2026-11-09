"""HTTP-boundary tests for Text Request's published v3 contract; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import text_request_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-text-request-key"
DASHBOARD = 121
PHONE = "14239309346"
UUID = "eb2a0cc2-5b88-468b-b3f4-926b07bcb275"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="text-request-test", node_type="automation-text-request",
        node_data={"config": config, "credentials": {"credential_type": "text_request_api_key", "api_key": TOKEN}})


def mock_http(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Explicit endpoint expectations, independent of the implementation's dispatch table.
CASES = [
    ("list_dashboards", "GET", "/dashboards", {}),
    ("get_dashboard", "GET", "/dashboards/121", {"dashboard_id": DASHBOARD}),
    ("list_contacts", "GET", "/dashboards/121/contacts", {"dashboard_id": DASHBOARD}),
    ("get_contact", "GET", "/dashboards/121/contacts/14239309346", {"dashboard_id": DASHBOARD, "phone_number": PHONE}),
    ("upsert_contact", "POST", "/dashboards/121/contacts/14239309346", {"dashboard_id": DASHBOARD, "phone_number": PHONE, "first_name": "John", "last_name": "Smith", "contact_tags": []}),
    ("delete_contact", "DELETE", "/dashboards/121/contacts/14239309346", {"dashboard_id": DASHBOARD, "phone_number": PHONE}),
    ("send_message", "POST", "/dashboards/121/contacts/14239309346/messages", {"dashboard_id": DASHBOARD, "phone_number": PHONE, "body": "Your appointment is tomorrow at 9am."}),
    ("list_conversations", "GET", "/dashboards/121/conversations", {"dashboard_id": DASHBOARD}),
    ("list_contact_messages", "GET", "/dashboards/121/contacts/14239309346/messages", {"dashboard_id": DASHBOARD, "phone_number": PHONE}),
    ("list_messages", "GET", "/dashboards/121/messages", {"dashboard_id": DASHBOARD}),
    ("archive_conversation", "PUT", "/dashboards/121/contacts/14239309346/conversations/archive", {"dashboard_id": DASHBOARD, "phone_number": PHONE}),
    ("unarchive_conversation", "PUT", "/dashboards/121/contacts/14239309346/conversations/unarchive", {"dashboard_id": DASHBOARD, "phone_number": PHONE}),
    ("list_groups", "GET", "/dashboards/121/groups", {"dashboard_id": DASHBOARD}),
    ("get_group", "GET", "/dashboards/121/groups/1", {"dashboard_id": DASHBOARD, "group_id": 1}),
    ("create_group", "POST", "/dashboards/121/groups", {"dashboard_id": DASHBOARD, "name": "Employees"}),
    ("update_group", "PUT", "/dashboards/121/groups/1", {"dashboard_id": DASHBOARD, "group_id": 1, "name": "Employees"}),
    ("delete_group", "DELETE", "/dashboards/121/groups/1", {"dashboard_id": DASHBOARD, "group_id": 1}),
    ("list_tags", "GET", "/dashboards/121/tags", {"dashboard_id": DASHBOARD}),
    ("get_tag", "GET", "/dashboards/121/tags/tag-1", {"dashboard_id": DASHBOARD, "tag_id": "tag-1"}),
    ("create_tag", "POST", "/dashboards/121/tags", {"dashboard_id": DASHBOARD, "tag": "Partners", "tag_color": "#1EB1C4"}),
    ("update_tag", "PUT", "/dashboards/121/tags/tag-1", {"dashboard_id": DASHBOARD, "tag_id": "tag-1", "tag": "Partners", "tag_color": "#1EB1C4"}),
    ("delete_tag", "DELETE", "/dashboards/121/tags/tag-1", {"dashboard_id": DASHBOARD, "tag_id": "tag-1"}),
    ("list_scheduled_messages", "GET", "/dashboards/121/scheduledmessages", {"dashboard_id": DASHBOARD}),
    ("get_scheduled_message", "GET", "/dashboards/121/scheduledmessages/" + UUID, {"dashboard_id": DASHBOARD, "message_id": UUID}),
    ("cancel_scheduled_message", "DELETE", "/dashboards/121/scheduledmessages/" + UUID, {"dashboard_id": DASHBOARD, "message_id": UUID}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config", CASES)
async def test_text_request_single_contract_request(monkeypatch, operation, method, path, config):
    response = httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={"id": 121})
    requests = mock_http(monkeypatch, response)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.textrequest.com"
    assert request.url.path == "/api/v3" + path
    assert request.headers["x-api-key"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"page": "0", "page_size": "100"}
    if operation == "send_message":
        assert json.loads(request.content) == {"body": config["body"]}
    if operation == "upsert_contact":
        assert json.loads(request.content) == {"first_name": "John", "last_name": "Smith", "contact_tags": []}


@pytest.mark.asyncio
async def test_text_request_documented_dashboard_response_and_next_page(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures/text-request/dashboards.json").read_text())
    mock_http(monkeypatch, httpx.Response(200, json=fixture["body"]))
    result = await node({"operation": "list_dashboards", "page_size": 1}).execute({})
    assert result["data"]["items"][0]["name"] == "Marketing"
    assert result["data"]["meta"]["total_items"] == 276
    assert result["next_page"] == 1


@pytest.mark.asyncio
async def test_text_request_empty_204_read(monkeypatch):
    mock_http(monkeypatch, httpx.Response(204))
    result = await node({"operation": "list_conversations", "dashboard_id": DASHBOARD}).execute({})
    assert result == {"status": "success", "http_status": 204, "data": None}


@pytest.mark.asyncio
async def test_text_request_provider_rejection_preserves_message_redacts_key(monkeypatch):
    mock_http(monkeypatch, httpx.Response(401, json={"status": 401, "errorCode": None, "message": "Invalid key " + TOKEN}))
    result = await node({"operation": "list_dashboards"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert result["error"] == "Invalid key [redacted]"


@pytest.mark.asyncio
async def test_text_request_query_false_and_page_not_dropped(monkeypatch):
    requests = mock_http(monkeypatch, httpx.Response(200, json={"items": [], "meta": {"page": 2, "page_size": 10, "total_items": 20}}))
    result = await node({"operation": "list_contacts", "dashboard_id": DASHBOARD, "is_blocked": False, "page": 2, "page_size": 10}).execute({})
    assert dict(requests[0].url.params) == {"page": "2", "page_size": "10", "is_blocked": "false"}
    assert result["next_page"] is None


@pytest.mark.asyncio
async def test_text_request_scheduled_send_preserves_utc(monkeypatch):
    requests = mock_http(monkeypatch, httpx.Response(200, json={"status": "scheduled", "message_id": UUID}))
    cfg = {"operation": "send_message", "dashboard_id": DASHBOARD, "phone_number": PHONE,
        "body": "Reminder", "schedule_date_utc": "2030-08-15T14:00:00Z"}
    result = await node(cfg).execute({})
    assert json.loads(requests[0].content) == {"body": "Reminder", "schedule_date_utc": "2030-08-15T14:00:00Z"}
    assert result["data"]["status"] == "scheduled"


def test_text_request_manual_key_default_and_required_field():
    value = native.TextRequestAPIKeyCredential(api_key=TOKEN)
    assert value.credential_type == "text_request_api_key"
    assert native.TextRequestNode.connection_evidence.operation == "list_dashboards"
    with pytest.raises(ValidationError):
        native.TextRequestAPIKeyCredential(api_key="https://app.textrequest.com/key")


@pytest.mark.parametrize("changes", [{"page": -1}, {"page_size": 0}, {"page_size": 101}])
def test_text_request_invalid_pagination(changes):
    with pytest.raises(ValidationError):
        native.ListDashboards(**changes)
