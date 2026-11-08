"""Exercise Rentman through the real factory with HTTP intercepted at transport.

The tests pin the published single-request routes, required write fields,
pagination boundaries and provider errors without using a live account.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import rentman_node as rentman
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "rentman_api_token", "api_token": "fixture-rentman-token"}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload) if payload is not None else httpx.Response(code)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(rentman, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(config, auth=AUTH):
    return NodeFactory.create_node(node_id="rentman-test", node_type="automation-rentman",
        node_data={"config": config, "credentials": auth})


CASES = [
    ("list_contacts", {}, "GET", "/contacts", None),
    ("get_contact", {"contact_id": 42}, "GET", "/contacts/42", None),
    ("list_contactpersons", {}, "GET", "/contactpersons", None),
    ("get_contact_person", {"contact_person_id": 42}, "GET", "/contactpersons/42", None),
    ("list_crew", {}, "GET", "/crew", None),
    ("get_crew_member", {"crew_member_id": 42}, "GET", "/crew/42", None),
    ("list_equipment", {}, "GET", "/equipment", None),
    ("get_equipment", {"equipment_id": 42}, "GET", "/equipment/42", None),
    ("list_projects", {}, "GET", "/projects", None),
    ("get_project", {"project_id": 42}, "GET", "/projects/42", None),
    ("list_tasks", {}, "GET", "/tasks", None),
    ("get_task", {"task_id": 42}, "GET", "/tasks/42", None),
    ("list_invoices", {}, "GET", "/invoices", None),
    ("get_invoice", {"invoice_id": 42}, "GET", "/invoices/42", None),
    ("list_quotes", {}, "GET", "/quotes", None),
    ("get_quote", {"quote_id": 42}, "GET", "/quotes/42", None),
    ("create_contact", {"name": "Rental Client", "email_1": "client@example.test"}, "POST", "/contacts",
        {"name": "Rental Client", "email_1": "client@example.test", "type": "company"}),
    ("update_contact", {"contact_id": 42, "phone_1": "123"}, "PUT", "/contacts/42", {"phone_1": "123"}),
    ("create_project", {"name": "Festival", "reference": "EXT-42"}, "POST", "/projects", {"name": "Festival", "reference": "EXT-42"}),
    ("create_task", {"name": "Pack", "color": "#ff0000"}, "POST", "/tasks", {"name": "Pack", "color": "#ff0000"}),
    ("update_task", {"task_id": 42, "color": "#00ff00", "priority": "high_priority"}, "PUT", "/tasks/42", {"color": "#00ff00", "priority": "high_priority"}),
    ("delete_task", {"task_id": 42}, "DELETE", "/tasks/42", None),
    ("list_project_equipment", {"project_id": 42}, "GET", "/projects/42/projectequipment", None),
]


@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_every_operation_one_documented_request(transport, operation, config, method, path, body):
    requests, replies = transport
    data = [{"id": 42, "name": "Rental Item"}] if operation.startswith("list_") else {"id": 42, "name": "Rental Item"}
    envelope = {"data": data, "itemCount": 1, "limit": 100, "offset": 0}
    replies.append((204, None) if method == "DELETE" else (201 if method == "POST" else 200, envelope))
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.rentman.net"
    assert request.headers["Authorization"] == "Bearer fixture-rentman-token"
    assert request.headers["Content-Type"] == "application/json"
    assert AUTH["api_token"] not in str(request.url) and AUTH["api_token"] not in json.dumps(result)
    assert (json.loads(request.content) if request.content else None) == body
    if operation.startswith("list_"):
        assert dict(request.url.params) == {"limit": "100"}
    if method == "DELETE":
        assert result["deleted_id"] == 42 and result["http_status"] == 204
    else:
        assert result["data"] == data and result["itemCount"] == 1


async def test_continuation_url_preserved_and_one_page_only(transport):
    requests, replies = transport
    following = "https://api.rentman.net/contacts?country=gb&cursor=opaque-token"
    replies.extend([(200, {"data": [{"id": 1}], "next_page_url": following}), (200, {"data": [], "next_page_url": None})])
    first = await node({"operation": "list_contacts", "limit": 10}).execute({})
    assert first["next_page_url"] == following and len(requests) == 1
    result = await node({"operation": "list_contacts", "next_page_url": following}).execute({})
    assert str(requests[-1].url) == following and result["data"] == []


@pytest.mark.parametrize("url", [
    "https://foreign.test/contacts?cursor=abc", "http://api.rentman.net/contacts?cursor=abc",
    "https://api.rentman.net.evil.test/contacts?cursor=abc", "https://api.rentman.net/tasks?cursor=abc",
    "https://user@api.rentman.net/contacts?cursor=abc", "https://api.rentman.net/contacts?cursor=a&cursor=b",
    "https://api.rentman.net/contacts?limit=10", "https://api.rentman.net/contacts?cursor=a#bad",
])
async def test_untrusted_page_urls_rejected_before_http(transport, url):
    with pytest.raises(ValueError, match="next_page_url"):
        await node({"operation": "list_contacts", "next_page_url": url}).execute({})
    assert transport[0] == []


@pytest.mark.parametrize("code", [301, 400, 401, 403, 404, 429, 500])
async def test_provider_rejection_is_not_success_and_is_verbatim(transport, code):
    transport[1].append((code, {"message": "Rentman says rejected"}))
    with pytest.raises(ValueError, match=f"Rentman HTTP {code}.*Rentman says rejected"):
        await node({"operation": "list_projects"}).execute({})
    assert len(transport[0]) == 1


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": ["wrong"]}])
async def test_malformed_collection_is_not_connection_evidence(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../42"},
    {"operation": "get_contact", "contact_id": 0},
    {"operation": "create_task", "name": "Pack"},
    {"operation": "update_task", "task_id": 42},
    {"operation": "update_contact", "contact_id": 42},
    {"operation": "list_projects", "limit": 1501},
])
def test_invalid_config_rejected(config):
    assert rentman.RentmanNode.validate_config({"config": config, "credentials": AUTH})["valid"] is False


@pytest.mark.parametrize("token", ["https://example.test/key", "<token>", "Bearer abc", "abc\ndef", "é"])
def test_manual_credential_rejects_placeholder_url_and_header(token):
    with pytest.raises(ValidationError):
        rentman.RentmanAPITokenCredential(api_token=token)


async def test_task_datetime_serialized_in_json(transport):
    transport[1].append((200, {"data": {"id": 42}}))
    await node({"operation": "update_task", "task_id": 42, "color": "red", "deadline": "2026-11-08T12:00:00Z"}).execute({})
    assert json.loads(transport[0][0].content)["deadline"] == "2026-11-08T12:00:00Z"


@pytest.mark.parametrize("tag", ["other_api_token", None, "", 7])
def test_foreign_credential_family_rejected(tag):
    data = {"config": {"operation": "list_projects"}, "credentials": {**AUTH, "credential_type": tag}}
    assert rentman.RentmanNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError, match="Rentman API token credential"):
        rentman.RentmanNode.parse_config(data)
